"""Behavioural checks for the depot transfer ledger CLI.

Expected reports come from tests/reference_ledger.py (contract-derived). The
agent binary under /app/x/bin/depot-ledger is exercised on sample and sealed
holdout batches; /app/output from the agent run is also checked.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from reference_ledger import REPORTS, run_ledger

ROOT = Path("/app")
LEDGER = ROOT / "x"
BINARY = LEDGER / "bin" / "depot-ledger"
AGENT_OUTPUT = ROOT / "output"
TEST_DIR = Path(__file__).resolve().parent
FIXTURES = TEST_DIR / "fixtures"


def _run_cli(
    parts: Path,
    stock: Path,
    events: Path,
    output: Path,
    timeout: int = 60,
    *,
    wipe: bool = True,
):
    if wipe and output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [
            str(BINARY),
            "--parts",
            str(parts),
            "--stock",
            str(stock),
            "--events",
            str(events),
            "--output",
            str(output),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
    )


def _read_report(directory: Path, name: str) -> str:
    path = directory / name
    assert path.is_file(), f"missing report {path}"
    data = path.read_bytes()
    assert b"\r" not in data, f"CR found in {path}"
    return data.decode("ascii")


def _assert_reports_match(directory: Path, expected) -> None:
    assert expected.exit_code == 0
    assert _read_report(directory, "closing-stock.dat") == expected.closing
    assert _read_report(directory, "open-transit.dat") == expected.transit
    assert _read_report(directory, "exceptions.dat") == expected.exceptions
    assert _read_report(directory, "summary.dat") == expected.summary


def _fixture_paths(name: str) -> tuple[Path, Path, Path]:
    base = FIXTURES / name
    return base / "parts.dat", base / "stock.dat", base / "events.dat"


@pytest.fixture(scope="module")
def binary_ready() -> Path:
    """Require the agent-built ledger launcher and native binary."""
    assert BINARY.is_file(), f"missing CLI launcher at {BINARY}"
    native = LEDGER / "build" / "depot-ledger-bin"
    assert native.is_file(), f"missing native binary at {native}"
    return BINARY


def test_binary_exists(binary_ready: Path) -> None:
    """Agent must leave a runnable /app/x/bin/depot-ledger after rebuilding."""
    assert binary_ready.is_file()
    assert (LEDGER / "build" / "depot-ledger-bin").is_file()


def test_agent_sample_output_matches_reference(binary_ready: Path) -> None:
    """Primary /app/output from the sample batch must match the contract reference."""
    parts, stock, events = _fixture_paths("sample")
    expected = run_ledger(parts, stock, events)
    assert expected.exit_code == 0
    for name in REPORTS:
        assert (AGENT_OUTPUT / name).is_file(), f"agent missing /app/output/{name}"
    _assert_reports_match(AGENT_OUTPUT, expected)


def test_sample_cli_rerun_matches_reference(binary_ready: Path, tmp_path: Path) -> None:
    """Re-invoking the CLI on sample masters must reproduce the reference reports."""
    parts, stock, events = _fixture_paths("sample")
    expected = run_ledger(parts, stock, events)
    out = tmp_path / "sample_out"
    proc = _run_cli(parts, stock, events, out)
    assert proc.returncode == 0, proc.stdout
    _assert_reports_match(out, expected)


def test_sort_order_holdout(binary_ready: Path, tmp_path: Path) -> None:
    """Out-of-order events must process by date, then sequence, then event ID."""
    parts, stock, events = _fixture_paths("sort_order")
    expected = run_ledger(parts, stock, events)
    out = tmp_path / "sort_out"
    proc = _run_cli(parts, stock, events, out)
    assert proc.returncode == 0, proc.stdout
    _assert_reports_match(out, expected)
    # Sort correctness shows up in transit IDs (business order) and stock draws.
    transit = _read_report(out, "open-transit.dat").splitlines()
    ids = [line[:12] for line in transit]
    assert ids == sorted(ids)
    assert "EVT00000000A" in ids
    assert "EVT00000000B" not in ids
    exceptions = _read_report(out, "exceptions.dat")
    assert "EVT00000000B|INSUFFICIENT_STOCK" in exceptions
    assert "EVT00000000A|" not in exceptions
    # Same-date seq/id ordering still applied for the gasket pair.
    assert "EVT00000000L" in ids
    assert "EVT00000000M" in ids


def test_duplicates_holdout(binary_ready: Path, tmp_path: Path) -> None:
    """Exact field duplicates increment DUPLICATE_COUNT; field mismatches conflict."""
    parts, stock, events = _fixture_paths("duplicates")
    expected = run_ledger(parts, stock, events)
    out = tmp_path / "dup_out"
    proc = _run_cli(parts, stock, events, out)
    assert proc.returncode == 0, proc.stdout
    _assert_reports_match(out, expected)
    summary = _read_report(out, "summary.dat")
    assert "DUPLICATE_COUNT=1" in summary
    exceptions = _read_report(out, "exceptions.dat")
    assert "DUP000000001|DUPLICATE_CONFLICT" in exceptions


def test_voids_receipts_active_and_excess(binary_ready: Path, tmp_path: Path) -> None:
    """Void receipt restores transit; active receipts block void dispatch; excess rejects."""
    parts, stock, events = _fixture_paths("voids_and_excess")
    expected = run_ledger(parts, stock, events)
    out = tmp_path / "void_out"
    proc = _run_cli(parts, stock, events, out)
    assert proc.returncode == 0, proc.stdout
    _assert_reports_match(out, expected)
    exceptions = _read_report(out, "exceptions.dat")
    assert "TRN000000005|RECEIPTS_ACTIVE" in exceptions
    assert "TRN000000006|EXCESS_RECEIPT" in exceptions
    transit = _read_report(out, "open-transit.dat")
    # After void-receipt restore and later partial receive, 15 remains open.
    assert "TRN000000001" in transit
    assert transit.strip().endswith("000000015")


def test_fatal_duplicate_part_leaves_no_reports(binary_ready: Path, tmp_path: Path) -> None:
    """Fatal master errors return exit 2 and must not leave the four reports."""
    parts, stock, events = _fixture_paths("fatal_dup_part")
    expected = run_ledger(parts, stock, events)
    assert expected.exit_code == 2
    out = tmp_path / "fatal_out"
    # Seed stale reports that a correct run must clear on fatal.
    out.mkdir(parents=True, exist_ok=True)
    for name in REPORTS:
        (out / name).write_text("stale\n", encoding="ascii")
    proc = _run_cli(parts, stock, events, out, wipe=False)
    assert proc.returncode == 2, proc.stdout
    for name in REPORTS:
        assert not (out / name).exists(), f"fatal run left {name}"


def test_metamorphic_identical_rerun(binary_ready: Path, tmp_path: Path) -> None:
    """Running the same holdout batch twice must yield byte-identical reports."""
    parts, stock, events = _fixture_paths("voids_and_excess")
    out1 = tmp_path / "meta1"
    out2 = tmp_path / "meta2"
    proc1 = _run_cli(parts, stock, events, out1)
    proc2 = _run_cli(parts, stock, events, out2)
    assert proc1.returncode == 0, proc1.stdout
    assert proc2.returncode == 0, proc2.stdout
    for name in REPORTS:
        assert (out1 / name).read_bytes() == (out2 / name).read_bytes()


def test_summary_count_reconciliation(binary_ready: Path, tmp_path: Path) -> None:
    """INPUT_COUNT must equal accepted + duplicate + rejected for a normal batch."""
    parts, stock, events = _fixture_paths("duplicates")
    out = tmp_path / "reconcile"
    proc = _run_cli(parts, stock, events, out)
    assert proc.returncode == 0, proc.stdout
    values = {}
    for line in _read_report(out, "summary.dat").splitlines():
        key, value = line.split("=", 1)
        values[key] = int(value)
    assert values["INPUT_COUNT"] == (
        values["ACCEPTED_COUNT"] + values["DUPLICATE_COUNT"] + values["REJECTED_COUNT"]
    )
