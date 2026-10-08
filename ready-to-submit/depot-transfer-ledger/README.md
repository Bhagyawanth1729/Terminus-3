# depot-transfer-ledger

Human notes only. Agents never see this file.

## What the task is

Overnight GnuCOBOL depot-transfer ledger under `/app/x`. `src/core.cob` is
frozen; four COPY fragments (`a1/a.c`, `b2/b.c`, `c3/c.c`, `d4/d.c`) disagree
with `/app/x/docs/requirements.md`. Fix those fragments, `make` rebuild
`/app/x/bin/depot-ledger`, and produce the four reports under `/app/output`
from the sample masters.

Goals live in `instruction.md`. Record layouts, reject-reason order,
dispatch/receipt/void rules and report schemas live in the requirements doc.

## Why it bites

Each fragment owns one failure mode (sort, duplicates, receipts, voids) and
the holdout fixtures hit them independently. A plausible local fix can still
fail summary reconciliation or leave reports behind on a fatal run. GnuCOBOL
COPY-book parsing is picky — the oracle rewrite uses explicit `END-IF`
nesting where the monolith's `ELSE IF` chain mis-parses.

## Difficulty

Advanced COBOL batch. Not a one-line typo hunt across four correlated
paragraphs.

## Oracle

`solution/solve.sh` copies `solution/fixed/{a1,b2,c3,d4}` over the broken
fragments, runs `make clean all`, then runs the sample batch and checks the
four reports exist.

## Verification

Separate verifier (Python + pytest + `libcob4`, no `cobc`) grades the
agent-built binary and `/app/output` against `tests/reference_ledger.py`, plus
sealed holdouts (sort, duplicates, voids/excess, fatal dup part) and a
metamorphic double-run. Hand-written reports without a correct binary fail
the CLI reruns.

## Base images / network

`network_mode = "no-network"`. Agent: digest-pinned
`python:3.13-slim-bookworm` + Debian `gnucobol` (no dedicated COBOL canonical
image). Verifier: same Python base with pytest and `libcob4` only.
