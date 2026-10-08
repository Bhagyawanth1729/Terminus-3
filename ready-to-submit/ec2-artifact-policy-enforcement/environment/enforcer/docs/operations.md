# Operations

Operators provide policy, scanner fixtures, exception data, state directory, secret material, and optional RFC3339 time through the stable CLI. `evaluate` returns exit 42 on policy denial and 2 on operational failure. `verify-permit` returns exit 43 for an invalid permit and retains its existing stateless integrity/scope/expiry behavior when no replay state is supplied.

`verify-permit` may additionally receive `--state <dir>` for durable single-use enforcement. With replay state enabled, the first exact valid permit use returns the normal valid result and durably records consumption; later or concurrent use of that permit must return exit 43 with `PERMIT_REPLAYED`, while the successful verification reports `PERMIT_VALID`. Production repair must fail closed on stale or unavailable scanner evidence, preserve durable audit history, and prevent permit replay across restart and concurrency boundaries.
