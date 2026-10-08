# claims-remittance-auth-desk

Human notes only. Agents never see this file.

## What the task is

A real GnuCOBOL + Open COBOL ESQL + PostgreSQL claims remittance /
payment-authorization terminal. Operators open claims against seeded
policies, authorize plan remittances with deductible-then-coinsurance
splits, claw back overpayments, and close claims.

Five COPY books under `src/copybooks/` ship broken (transaction begin,
request identity, deductible math, clawback order, audit reserve).
Sequential happy-path authorizations can look fine; concurrent retries,
benefit caps, clawback validation, and audit numbering fail the contract.
Goals live in `instruction.md`. Protocol, state machine, benefit math
and response schemas live in `environment/docs/terminal-contract.md`.

## Why it bites

Bugs interact under concurrency and cumulative balances: request-identity
fingerprints, SERIALIZABLE request locks, deductible/coinsurance math
against remaining balances, clawback caps, and audit reservation all have
to agree. A fix that works for a single `claimsctl` call still fails the
parallel and benefits suites. Audit sequences must stay gap-free among
committed events only — rejects and rollbacks must not burn numbers.

## Difficulty

Advanced. Real ESQL against PostgreSQL, compose multi-container agent env,
separate verifier that rebuilds submitted sources and drives concurrent
terminals. Difficulty is provisional until measured.

## Oracle

`solution/solve.sh` installs the five fixed COPY books from `solution/fixed/`
and runs `/app/claims/bin/build-claims`.

## Verification

Separate verifier starts a clean local PostgreSQL, rebuilds `/app/claims`
from the agent's sources, and runs pytest (`protocol`, `transactions`,
`concurrency`, `benefits`). Hand-written SQL side paths cannot satisfy the
native-binary requirement in the contract.

## Base images / network

Agent is a two-service Compose app (`main` + `database`). Debian
bookworm-slim is the canonical base — Terminus has no dedicated GnuCOBOL
image. GnuCOBOL, libpq, OCESQL (pinned upstream commit
`14591d82…` with checksum), tmux and asciinema are installed at build time.
Verifier image also builds OCESQL and hosts PostgreSQL for the grade.
`network_mode = "public"` because the OCESQL tarball is fetched during image
build; trial runtime does not need the network for the grade itself.
