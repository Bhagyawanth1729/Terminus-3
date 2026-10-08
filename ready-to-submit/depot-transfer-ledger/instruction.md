1) The depot ledger at /app/x builds, but its overnight reports do not match /app/x/docs/requirements.md. 

2) Repair the four COPY fragments at /app/x/a1/a.c, /app/x/b2/b.c, /app/x/c3/c.c, and /app/x/d4/d.c that feed /app/x/src/core.cob. Leave the rest of the core alone.

3) Rebuild /app/x/bin/depot-ledger. Clear any old reports before every run, then use /app/x/bin/depot-ledger --parts /app/x/sample/parts.dat --stock /app/x/sample/opening.dat --events /app/x/sample/events.dat --output /app/output.

4) A normal batch exits 0 and writes closing-stock.dat, open-transit.dat, exceptions.dat, and summary.dat under /app/output, even when it rejects some business events.

5) Bad master data or bad input is fatal. That run exits 2 and leaves none of the four reports behind.

6) Process events in the required sort order. Handle duplicate IDs, blank IDs, and conflicting ID reuse with the documented reasons, precedence, and counts.

7) Receipts must check the remaining transit quantity rather than the original dispatch quantity. Reject excess receipts and keep active-received totals correct.

8) Voids must restore stock or transit as the contract says, including the RECEIPTS_ACTIVE gate.

9) Summary counts must reconcile with the input. Follow the documented record layouts, report formats, rejection order, and fatal conditions.

10) Running the same valid batch again must produce byte-for-byte identical reports.
