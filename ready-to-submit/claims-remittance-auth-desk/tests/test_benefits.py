"""Benefit math, stop-loss, and cumulative deductible checks."""

from conftest import connection, run_cli, scalar


def test_deductible_then_coinsurance_on_first_authorization() -> None:
    """POL-STD must apply remaining deductible before coinsurance on the charge."""
    assert run_cli("OPEN", "REQ-B01", "CL-B01", "POL-STD", "100000").returncode == 0
    # deductible 10000, coinsurance 20% on remainder 40000 -> patient 8000, plan 32000
    authorized = run_cli(
        "AUTHORIZE", "REQ-B02", "CL-B01", "1", "REM-B01", "50000"
    )
    assert authorized.returncode == 0
    assert "|patient=000000018000|plan=000000032000|" in authorized.stdout
    assert scalar("SELECT remaining_deductible FROM claim") == 0
    assert scalar("SELECT patient_cents FROM remittance") == 18000
    assert scalar("SELECT plan_cents FROM remittance") == 32000
    assert scalar("SELECT deductible_applied FROM remittance") == 10000


def test_second_authorization_uses_remaining_deductible_and_patient_paid() -> None:
    """Later remittances must not re-apply exhausted deductible or ignore patient paid."""
    assert run_cli("OPEN", "REQ-B11", "CL-B11", "POL-STD", "100000").returncode == 0
    assert run_cli(
        "AUTHORIZE", "REQ-B12", "CL-B11", "1", "REM-B11", "50000"
    ).returncode == 0
    second = run_cli(
        "AUTHORIZE", "REQ-B13", "CL-B11", "2", "REM-B12", "30000"
    )
    assert second.returncode == 0
    # remaining deductible 0, coinsurance 20% of 30000 -> patient 6000, plan 24000
    # cumulative patient 18000+6000=24000, plan 32000+24000=56000
    assert "|patient=000000024000|plan=000000056000|" in second.stdout
    with connection() as conn:
        row = conn.execute(
            "SELECT patient_paid, plan_paid, remaining_deductible FROM claim"
        ).fetchone()
    assert row == (24000, 56000, 0)


def test_authorization_respects_remaining_billed_capacity() -> None:
    """pay-cents may not exceed billed minus patient and plan already paid."""
    # POL-FULL puts the first slice entirely on the patient, so ignoring
    # cumulative patient_paid would incorrectly treat the claim as still open.
    assert run_cli("OPEN", "REQ-E01", "CL-E01", "POL-FULL", "10000").returncode == 0
    assert run_cli(
        "AUTHORIZE", "REQ-E02", "CL-E01", "1", "REM-E01", "7000"
    ).returncode == 0
    assert scalar("SELECT patient_paid FROM claim") == 7000
    assert scalar("SELECT plan_paid FROM claim") == 0
    over = run_cli(
        "AUTHORIZE", "REQ-E03", "CL-E01", "2", "REM-E02", "4000"
    )
    assert over.returncode == 1
    assert "code=EXCEEDS_BILLED" in over.stdout
    assert scalar("SELECT count(*) FROM remittance") == 1


def test_stop_loss_caps_plan_share() -> None:
    """Plan share that would exceed remaining stop-loss capacity must fail closed."""
    assert run_cli("OPEN", "REQ-S01", "CL-S01", "POL-FULL", "200000").returncode == 0
    # POL-FULL: deductible 0, coinsurance 100%, stop_loss 100000
    # first auth 100000 -> plan_share 0, patient 100000 (within stop-loss)
    assert run_cli(
        "AUTHORIZE", "REQ-S02", "CL-S01", "1", "REM-S01", "100000"
    ).returncode == 0

    assert run_cli("OPEN", "REQ-S03", "CL-S03", "POL-ZERO", "300000").returncode == 0
    # POL-ZERO: coinsurance 0, stop_loss 250000 — charge 260000 would put plan at 260000
    over = run_cli(
        "AUTHORIZE", "REQ-S04", "CL-S03", "1", "REM-S03", "260000"
    )
    assert over.returncode == 1
    assert "code=EXCEEDS_STOP_LOSS" in over.stdout
    assert scalar("SELECT count(*) FROM remittance WHERE claim_id='CL-S03'") == 0


def test_clawback_respects_remaining_clawable_plan_amount() -> None:
    """Partial clawbacks accumulate and must not reclaim more than plan paid on that remittance."""
    assert run_cli("OPEN", "REQ-K11", "CL-K11", "POL-ZERO", "50000").returncode == 0
    assert run_cli(
        "AUTHORIZE", "REQ-K12", "CL-K11", "1", "REM-K11", "50000"
    ).returncode == 0
    first = run_cli("CLAWBACK", "REQ-K13", "CL-K11", "2", "REM-K11", "20000")
    second = run_cli("CLAWBACK", "REQ-K14", "CL-K11", "3", "REM-K11", "30000")
    third = run_cli("CLAWBACK", "REQ-K15", "CL-K11", "4", "REM-K11", "1")
    assert first.returncode == second.returncode == 0
    assert "|plan=000000030000|" in first.stdout
    assert "|plan=000000000000|" in second.stdout
    assert third.returncode == 1
    assert "code=EXCEEDS_CLAWBACK" in third.stdout
    assert scalar("SELECT plan_paid FROM claim") == 0
    assert scalar("SELECT clawed_cents FROM remittance") == 50000
