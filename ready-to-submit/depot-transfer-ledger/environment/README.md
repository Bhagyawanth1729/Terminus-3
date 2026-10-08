# Depot transfer ledger

This directory contains the overnight fixed-width transfer ledger and a small sample batch. Run `make clean all` to compile it with GnuCOBOL, then run `make sample` to inspect the four reports. The shell entry point only handles the fixed CLI and stale-report cleanup; all parsing, ordering, ledger decisions, and report calculations live in `src/core.cob`.
