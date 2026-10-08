# On-call handoff

Security reproduced the incident with three paths:

- an `apt` request with digest `sha256:777...` was allowed while the vulnerability mirror was unavailable;
- `dpkg -i` and Maven resolution did not consult the same source allow-list as the higher-level paths;
- `docker pull app:stable` was scanned clean, then the tag moved to another digest and the second request reported `cache_hit=true` with the old result.

They also supplied an expired production dependency exception that still passed. A red-team script changed `instance_id` in an allow permit and generated another valid-looking signature without the host secret. Deny decisions were visible on stdout but absent after restarting the process and reading `state/audit.jsonl`.

Do not solve this by disabling cache or exceptions: both are required operational controls. Keep the scanner fixture boundary deterministic; the real service swaps that adapter for Trivy/internal scanning.
