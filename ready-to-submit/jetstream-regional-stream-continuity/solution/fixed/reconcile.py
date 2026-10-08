"""Journal-to-archive identity reconciliation."""

from __future__ import annotations

import hashlib
import json

from .model import (
    ContractError,
    Finding,
    FindingSeverity,
    GenerationStatus,
    ReconcileStatus,
    ReconciliationSummary,
    contiguous_floor,
)


class ReconcileMixin:
    def reconcile_region(self, region: str, generation: int) -> ReconciliationSummary:
        run_id = self.store.create_reconciliation_run(mode="DRY_RUN")
        generation_record = self.store.generation(region, generation)
        if generation_record is None or generation_record.status is not GenerationStatus.CONFIRMED:
            raise ContractError(
                f"reconciliation requires confirmed generation {region}/{generation}"
            )
        confirmed_watermark = generation_record.last_observed_sequence
        journal_by_id = {
            event.identity.event_id: event
            for event in self.store.iter_events(region=region, generation=generation)
        }
        archive_rows = self.store.execute(
            "SELECT event_id,region,generation,origin_sequence,hub_stream_sequence,"
            "payload_sha256,archived_at,source_stream,source_domain,"
            "duplicate_observation_count FROM archive_index "
            "WHERE region=? AND generation=? ORDER BY origin_sequence,event_id",
            (region, generation),
        ).fetchall()
        archive_by_id = {str(row["event_id"]): row for row in archive_rows}
        journal_ids = set(journal_by_id)
        archive_ids = set(archive_by_id)
        missing_ids = sorted(journal_ids - archive_ids)
        unexpected_ids = sorted(archive_ids - journal_ids)
        findings: list[Finding] = []
        metadata_mismatch_count = 0
        region_row = self.store.region(region)
        expected_source_stream = str(region_row["physical_stream"])
        expected_source_domain = str(region_row["jetstream_domain"])

        for event_id in missing_ids:
            event = journal_by_id[event_id]
            findings.append(
                Finding(
                    severity=FindingSeverity.ERROR,
                    finding_type="MISSING_ARCHIVE_EVENT",
                    message="accepted edge event is absent from the hub archive",
                    region=region,
                    generation=generation,
                    origin_sequence=event.identity.origin_sequence,
                    event_id=event_id,
                    expected_value="present",
                    observed_value="missing",
                    remediation_hint="replay this stable event identity after validating its origin generation",
                )
            )
        for event_id in unexpected_ids:
            row = archive_by_id[event_id]
            findings.append(
                Finding(
                    severity=FindingSeverity.BLOCKER,
                    finding_type="UNEXPECTED_ARCHIVE_EVENT",
                    message="hub raw archive contains an event outside the edge journal authority",
                    region=region,
                    generation=generation,
                    origin_sequence=int(row["origin_sequence"]),
                    event_id=event_id,
                    expected_value="absent",
                    observed_value="present",
                    remediation_hint="identify the local/raw write path before continuing replay",
                )
            )
        for event_id in sorted(journal_ids & archive_ids):
            event = journal_by_id[event_id]
            row = archive_by_id[event_id]
            mismatches: list[str] = []
            if str(row["region"]) != event.identity.region:
                mismatches.append("region")
            if int(row["generation"]) != event.identity.generation:
                mismatches.append("generation")
            if int(row["origin_sequence"]) != event.identity.origin_sequence:
                mismatches.append("origin_sequence")
            if str(row["payload_sha256"]).lower() != event.payload_sha256.lower():
                mismatches.append("payload_sha256")
            if str(row["source_stream"]) != expected_source_stream:
                mismatches.append("source_stream")
            if str(row["source_domain"]) != expected_source_domain:
                mismatches.append("source_domain")
            if mismatches:
                metadata_mismatch_count += 1
                findings.append(
                    Finding(
                        severity=FindingSeverity.BLOCKER,
                        finding_type="ARCHIVE_METADATA_MISMATCH",
                        message="archive event identity metadata disagrees with its edge journal authority",
                        region=region,
                        generation=generation,
                        origin_sequence=event.identity.origin_sequence,
                        event_id=event_id,
                        expected_value=",".join(mismatches),
                        observed_value="mismatch",
                        remediation_hint="hold the affected generation and repair source identity propagation",
                    )
                )

        duplicate_count = sum(int(row["duplicate_observation_count"]) for row in archive_rows)
        if duplicate_count:
            findings.append(
                Finding(
                    severity=FindingSeverity.WARNING,
                    finding_type="DUPLICATE_OBSERVATIONS",
                    message="the archive observed duplicate deliveries for stable event identities",
                    region=region,
                    generation=generation,
                    expected_value="0",
                    observed_value=str(duplicate_count),
                    remediation_hint="retain stable message ids and application idempotency; server duplicate windows are not replay authority",
                )
            )

        archive_sequences = [int(row["origin_sequence"]) for row in archive_rows]
        archive_floor = contiguous_floor(archive_sequences)
        if archive_floor < confirmed_watermark:
            findings.append(
                Finding(
                    severity=FindingSeverity.ERROR,
                    finding_type="ARCHIVE_WATERMARK_LAG",
                    message="hub archive has not reached the confirmed origin watermark",
                    region=region,
                    generation=generation,
                    origin_sequence=archive_floor,
                    expected_value=str(confirmed_watermark),
                    observed_value=str(archive_floor),
                    remediation_hint="reconcile and replay missing origin identities before declaring convergence",
                )
            )

        required_consumer_progress: dict[str, int] = {}
        for consumer_name in self.store.required_consumers():
            checkpoint = self.store.checkpoint(consumer_name, region, generation)
            required_consumer_progress[consumer_name] = (
                0 if checkpoint is None else checkpoint.application_sequence
            )
        consumer_findings = self._required_consumer_lag(region, generation, confirmed_watermark)
        findings.extend(consumer_findings)

        digest = hashlib.sha256()
        for row in sorted(archive_rows, key=lambda value: str(value["event_id"])):
            stable = (
                str(row["region"]),
                int(row["generation"]),
                int(row["origin_sequence"]),
                str(row["event_id"]),
                str(row["payload_sha256"]).lower(),
                str(row["source_stream"]),
                str(row["source_domain"]),
            )
            digest.update(json.dumps(stable, separators=(",", ":")).encode("utf-8"))
            digest.update(b"\n")
        checksum = digest.hexdigest()

        blocking = [
            finding
            for finding in findings
            if finding.severity in {FindingSeverity.ERROR, FindingSeverity.BLOCKER}
        ]
        summary = ReconciliationSummary(
            run_id=run_id,
            status=ReconcileStatus.CONVERGED if not blocking else ReconcileStatus.DIVERGED,
            journal_event_count=len(journal_by_id),
            archive_event_count=len(archive_by_id),
            missing_count=len(missing_ids),
            unexpected_count=len(unexpected_ids),
            duplicate_count=duplicate_count,
            metadata_mismatch_count=metadata_mismatch_count,
            consumer_lag_count=len(consumer_findings),
            highest_contiguous_archive_origin_sequence=archive_floor,
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
            checksum=checksum,
            summary=summary.as_dict(),
        )
        return summary

    def missing_event_ids(self, region: str, generation: int) -> tuple[str, ...]:
        journal_ids = {
            event.identity.event_id
            for event in self.store.iter_events(region=region, generation=generation)
        }
        archive_ids = self.store.archive_identity_set(region, generation)
        return tuple(sorted(journal_ids - archive_ids))
