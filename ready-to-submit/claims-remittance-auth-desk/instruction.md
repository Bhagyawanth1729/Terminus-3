The GnuCOBOL claims remittance terminal at /app/claims authorizes plan payments correctly when operators work one request at a time. Concurrent retries, partial remittances, clawbacks, and benefit caps can accept stale revisions, double-pay the same remittance, mis-split patient and plan liability, or leave gaps in the audit sequence. Repair the existing COBOL application without moving its transaction logic into another language.

- Treat /app/claims/docs/terminal-contract.md as binding for commands, benefit math, states, concurrency, idempotency, and line-based responses. Keep the public fields and schemas unchanged.
- Build with /app/claims/bin/build-claims. Use the supplied environment variables for the live PostgreSQL connection and /app/claims/bin/claimsctl as the operator interface. Reject malformed use before touching the database.
- Commit each accepted state change, its request record, and its audit entry in one PostgreSQL transaction. Killing the process mid-operation must leave no partial request, claim, remittance, or audit data.
- Follow the required claim states without creating orphan remittance rows. Partial authorizations are allowed until billed remainder and stop-loss rules in the contract are exhausted.
- An identical retry returns the stored response byte for byte and runs no more SQL. If any argument changes under the same request ID, return REQUEST_CONFLICT and leave the original record alone. Store and replay business rejections too.
- Concurrent first use of one request ID or remittance ID must settle on one stored result. Stale revisions and invalid state changes fail closed, with the documented rejection order.
- Apply deductible then coinsurance against remaining claim balances. Clawbacks must validate the remittance and remaining clawable plan amount before changing totals.
- Keep audit numbers unique and gap-free across committed events, including concurrent work. Rejected requests and rolled-back attempts consume no audit sequence.
- Leave the submitted /app/claims tree buildable offline, with the repaired COBOL and SQL migration sources included.
