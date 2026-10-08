# Claims remittance terminal operations contract

This document describes the operator protocol, benefit math, and transaction rules for the claims remittance authorization terminal. It is a protocol reference, not a guide to the implementation. The system authorizes plan remittances against open claims using seeded policy deductible, coinsurance, and stop-loss limits.

## Connection and build

`/app/claims/bin/build-claims` must rebuild the application from the submitted COBOL sources without downloading anything. `/app/claims/bin/claimsctl` runs one terminal transaction against the PostgreSQL connection named by `CLAIMS_DB`, `CLAIMS_DB_USER`, and `CLAIMS_DB_PASSWORD`.

This is a native COBOL database application, not a batch file exercise. The command path must execute the GnuCOBOL binary and its embedded OCESQL statements rather than delegate the behavior to another language.

Commands and responses use ASCII. Command names and enumerated values are uppercase. Identifiers are case-sensitive and contain only uppercase letters, digits, and hyphens. Request IDs are 3-24 characters, claim IDs 3-16, policy IDs 3-16, and remittance IDs 3-24. Revisions and cent amounts are unsigned decimal arguments without signs or padding. Cent amounts are 1 through 999999999999.

## Commands

| Command | Arguments after command |
|---|---|
| `HEALTH` | none |
| `OPEN` | `request-id claim-id policy-id billed-cents` |
| `AUTHORIZE` | `request-id claim-id expected-revision remittance-id pay-cents` |
| `CLAWBACK` | `request-id claim-id expected-revision remittance-id claw-cents` |
| `CLOSE` | `request-id claim-id expected-revision` |
| `STATUS` | `claim-id` |
| `AUDIT` | `claim-id` |

`pay-cents` is the billed charge slice being remitted in this authorization. `claw-cents` is the plan amount being reclaimed from a prior accepted remittance.

## Benefit math

Each seeded policy has `deductible_cents`, `coinsurance_pct` (0 through 100), and `stop_loss_cents`. A claim stores `billed_cents`, `patient_paid`, `plan_paid`, and `remaining_deductible`.

On `AUTHORIZE`, let `remaining_billed = billed_cents - patient_paid - plan_paid`. Reject with `EXCEEDS_BILLED` when `pay-cents` is greater than `remaining_billed`. Reject with `REMITTANCE_EXISTS` when the remittance ID already exists on any claim.

Compute the split against current remaining balances, not the original policy deductible alone:

1. `deductible_take = min(pay-cents, remaining_deductible)`
2. `after_deductible = pay-cents - deductible_take`
3. `patient_coinsurance = floor(after_deductible * coinsurance_pct / 100)` using integer arithmetic
4. `plan_share = after_deductible - patient_coinsurance`

Reject with `EXCEEDS_STOP_LOSS` when `plan_share` is greater than `stop_loss_cents - plan_paid`. Otherwise accept and update:

- `patient_paid = patient_paid + deductible_take + patient_coinsurance`
- `plan_paid = plan_paid + plan_share`
- `remaining_deductible = remaining_deductible - deductible_take`
- insert one remittance row recording `pay-cents`, `plan_share`, patient portion, and deductible applied, with `clawed_cents = 0`
- first successful authorization moves `OPEN` to `ACTIVE`; later authorizations keep `ACTIVE`
- claim revision increases by exactly one

Partial authorizations may continue while `remaining_billed` and remaining stop-loss capacity allow.

On `CLAWBACK`, the remittance must belong to the claim. Let `clawable = remittance.plan_cents - remittance.clawed_cents`. Reject with `UNKNOWN_REMITTANCE` when the remittance is missing for that claim. Reject with `EXCEEDS_CLAWBACK` when `claw-cents` is greater than `clawable`. Validation and caps must finish before any claim total changes. On accept: increase `clawed_cents` by `claw-cents`, decrease `plan_paid` by `claw-cents`, and increase claim revision by one. Patient totals are unchanged by clawback. Clawback is allowed only while the claim is `ACTIVE`.

## Response lines

Every invocation writes only its response to stdout and ends each line with LF. Mutation success is one line in this exact field order:

`OK|request=<id>|command=<name>|claim=<id>|remittance=<id-or-NONE>|revision=<six digits>|state=<state>|patient=<twelve digits>|plan=<twelve digits>|audit=<ten digits>`

Business rejection is one line:

`ERR|request=<id-or-NONE>|command=<name>|code=<reason>`

`HEALTH` returns `HEALTH|database=READY|schema=1`. `STATUS` returns one line:

`STATUS|claim=<id>|policy=<id>|revision=<six digits>|state=<state>|billed=<twelve digits>|patient=<twelve digits>|plan=<twelve digits>|deductible=<twelve digits>`

`AUDIT` returns zero or more lines ordered by audit sequence:

`AUDIT|sequence=<ten digits>|request=<id>|claim=<id>|action=<command>|from=<state>|to=<state>|revision=<six digits>`

Usage or malformed argument errors return exit 2 and an `ERR` line on stderr. Database or build failures return a nonzero exit and an `ERR` line on stderr. Business rejections return exit 1. Successful mutations, replays, health, status, and audit return exit 0.

## State rules

`OPEN` creates revision 1 in state `OPEN` with `patient_paid = 0`, `plan_paid = 0`, and `remaining_deductible` equal to the policy deductible. Claim IDs are unique. Unknown policies return `UNKNOWN_POLICY`. Duplicate claim IDs return `CLAIM_EXISTS`.

`AUTHORIZE` requires state `OPEN` or `ACTIVE` and the exact current revision. `CLAWBACK` requires `ACTIVE` and the exact current revision. `CLOSE` requires `OPEN` or `ACTIVE` and the exact current revision, then moves the claim to `CLOSED`. Other transitions return `INVALID_STATE`. Every accepted transition raises the claim revision exactly once.

## Atomicity, concurrency, and retries

The request record, claim or remittance change, and audit event form one PostgreSQL transaction. A failed validation, remittance conflict, stale revision, SQL retry, process termination, or database error must not expose a partial state change.

Concurrent first use of the same remittance ID must leave at most one accepted remittance row. Concurrent first use of the same request ID must converge on one recorded result. Deadlock and serialization failures are internal retry conditions, not business responses; retry the complete transaction a bounded number of times. Unrelated claims must remain independent.

## Request identity

For mutation commands the request fingerprint is the command name plus every parsed argument in public argument order. The first completed use of a request ID is permanent, including a business rejection. An identical retry returns the exact recorded response and performs no SQL state or audit change. Reuse with any different parsed argument returns `REQUEST_CONFLICT` and leaves the original record untouched. Simultaneous identical uses converge on one recorded result.

## Audit control

Every accepted mutation has one audit event in the same transaction. Audit sequences begin at 1, have no gaps among committed audit events, and reflect the order in which the audit counter was reserved inside committed transactions. Rejected requests and rolled-back attempts consume no audit sequence. Replays create no audit event.

## Rejection precedence

After request-identity handling, use this public precedence where several failures apply: `UNKNOWN_CLAIM`, `STALE_REVISION`, `INVALID_STATE`, `UNKNOWN_POLICY`, `REMITTANCE_EXISTS`, `UNKNOWN_REMITTANCE`, `EXCEEDS_BILLED`, `EXCEEDS_STOP_LOSS`, then `EXCEEDS_CLAWBACK`. `OPEN` reports `CLAIM_EXISTS` for an existing claim and `UNKNOWN_POLICY` for a missing policy. Malformed command arguments are usage errors rather than recorded business requests.
