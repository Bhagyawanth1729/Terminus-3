BEGIN;

CREATE TABLE policy (
    policy_id char(16) PRIMARY KEY,
    deductible_cents bigint NOT NULL CHECK (deductible_cents >= 0),
    coinsurance_pct smallint NOT NULL CHECK (coinsurance_pct BETWEEN 0 AND 100),
    stop_loss_cents bigint NOT NULL CHECK (stop_loss_cents >= 0)
);

CREATE TABLE claim (
    claim_id char(16) PRIMARY KEY,
    policy_id char(16) NOT NULL REFERENCES policy(policy_id),
    billed_cents bigint NOT NULL CHECK (billed_cents > 0),
    patient_paid bigint NOT NULL DEFAULT 0 CHECK (patient_paid >= 0),
    plan_paid bigint NOT NULL DEFAULT 0 CHECK (plan_paid >= 0),
    remaining_deductible bigint NOT NULL CHECK (remaining_deductible >= 0),
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    state char(12) NOT NULL DEFAULT 'OPEN',
    CHECK (state IN ('OPEN', 'ACTIVE', 'CLOSED'))
);

CREATE TABLE remittance (
    remittance_id char(24) PRIMARY KEY,
    claim_id char(16) NOT NULL REFERENCES claim(claim_id),
    request_id char(24) NOT NULL,
    charge_cents bigint NOT NULL CHECK (charge_cents > 0),
    plan_cents bigint NOT NULL CHECK (plan_cents >= 0),
    patient_cents bigint NOT NULL CHECK (patient_cents >= 0),
    deductible_applied bigint NOT NULL CHECK (deductible_applied >= 0),
    clawed_cents bigint NOT NULL DEFAULT 0 CHECK (clawed_cents >= 0),
    CHECK (clawed_cents <= plan_cents)
);

CREATE INDEX remittance_by_claim ON remittance(claim_id);

CREATE TABLE request_record (
    request_id char(24) PRIMARY KEY,
    command_name char(12) NOT NULL,
    fingerprint char(240) NOT NULL,
    response_line char(500) NOT NULL,
    claim_id char(16),
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp()
);

CREATE TABLE audit_counter (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    next_value bigint NOT NULL CHECK (next_value > 0)
);

CREATE TABLE audit_event (
    audit_sequence bigint PRIMARY KEY,
    request_id char(24) NOT NULL UNIQUE REFERENCES request_record(request_id) DEFERRABLE INITIALLY DEFERRED,
    claim_id char(16) NOT NULL REFERENCES claim(claim_id),
    action char(12) NOT NULL,
    prior_state char(12) NOT NULL,
    new_state char(12) NOT NULL,
    resulting_revision integer NOT NULL,
    CHECK (resulting_revision > 0)
);

INSERT INTO audit_counter(singleton, next_value) VALUES (true, 1);

INSERT INTO policy(policy_id, deductible_cents, coinsurance_pct, stop_loss_cents) VALUES
    ('POL-STD', 10000, 20, 500000),
    ('POL-HD', 50000, 10, 1000000),
    ('POL-ZERO', 0, 0, 250000),
    ('POL-FULL', 0, 100, 100000),
    ('POL-SPLIT', 25000, 30, 750000);

COMMIT;
