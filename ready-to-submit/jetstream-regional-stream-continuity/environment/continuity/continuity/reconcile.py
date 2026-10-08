"""Journal-to-archive identity reconciliation."""

from __future__ import annotations

from .model import (
    Finding,
    FindingSeverity,
    ReconcileStatus,
    ReconciliationSummary,
    contiguous_floor,
    sha256_text,
)


class ReconcileMixin:
    def reconcile_region(self, region: str, generation: int) -> ReconciliationSummary:
        run_id = self.store.create_reconciliation_run(mode="DRY_RUN")
        journal = list(self.store.iter_events(region=region, generation=generation))
        archive = list(self.store.iter_archive(region=region, generation=generation))
        findings: list[Finding] = []
        journal_count = len(journal)
        archive_count = len(archive)
        missing_count = max(journal_count - archive_count, 0)
        duplicate_count = sum(record.duplicate_observation_count for record in archive)
        if journal_count != archive_count:
            findings.append(
                Finding(
                    severity=FindingSeverity.ERROR,
                    finding_type="COUNT_MISMATCH",
                    message="journal and archive counts differ",
                    region=region,
                    generation=generation,
                    expected_value=str(journal_count),
                    observed_value=str(archive_count),
                    remediation_hint="replay the trailing archive gap",
                )
            )
        highest_journal = max((event.identity.origin_sequence for event in journal), default=0)
        highest_hub = max((record.hub_stream_sequence for record in archive), default=0)
        required_consumer_progress: dict[str, int] = {}
        for consumer_name in self.store.required_consumers():
            checkpoint = self.store.checkpoint(consumer_name, region, generation)
            required_consumer_progress[consumer_name] = (
                0 if checkpoint is None else checkpoint.application_sequence
            )
        if highest_hub < highest_journal:
            findings.append(
                Finding(
                    severity=FindingSeverity.ERROR,
                    finding_type="SEQUENCE_LAG",
                    message="hub aggregate sequence is behind the edge sequence",
                    region=region,
                    generation=generation,
                    expected_value=str(highest_journal),
                    observed_value=str(highest_hub),
                )
            )
        checksum = sha256_text(f"{region}:{generation}:{journal_count}:{archive_count}:{highest_hub}")
        status = ReconcileStatus.CONVERGED if not findings else ReconcileStatus.DIVERGED
        summary = ReconciliationSummary(
            run_id=run_id,
            status=status,
            journal_event_count=journal_count,
            archive_event_count=archive_count,
            missing_count=missing_count,
            unexpected_count=max(archive_count - journal_count, 0),
            duplicate_count=duplicate_count,
            metadata_mismatch_count=0,
            consumer_lag_count=0,
            highest_contiguous_archive_origin_sequence=contiguous_floor(
                record.hub_stream_sequence for record in archive
            ),
            required_consumer_progress=required_consumer_progress,
            checksum=checksum,
            findings=tuple(findings),
        )
        for finding in findings:
            self.store.add_finding(run_id, finding)
        self.store.finish_reconciliation_run(
            run_id,
            status=summary.status.value,
            journal_event_count=summary.journal_event_count,
            archive_event_count=summary.archive_event_count,
            missing_count=summary.missing_count,
            duplicate_count=summary.duplicate_count,
            metadata_mismatch_count=summary.metadata_mismatch_count,
            consumer_lag_count=summary.consumer_lag_count,
            checksum=summary.checksum,
            summary=summary.as_dict(),
        )
        return summary

    def missing_event_ids(self, region: str, generation: int) -> tuple[str, ...]:
        archive_count = self.store.archive_count(region)
        values = [
            event.identity.event_id
            for event in self.store.iter_events(region=region, generation=generation)
            if event.identity.origin_sequence > archive_count
        ]
        return tuple(values)
