# ansible-ci-control-plane

## What this task covers

This is a small, self-contained CI control plane written in Go. It manages
pipelines, a priority build queue, runner claims, logs, steps, artifacts,
retries, metrics, audit events, and retention. Ansible builds the service,
installs it under supervisord, runs a live smoke check, and writes a deployment
report.

The deploy and the service drifted together. Some wrong field names match on
both sides, so fixing only Go or only Ansible often exposes the next failure.
The goal is in `instruction.md`. The layout and API contract are in
`/app/environment/docs/requirements.md`.

## Broken Ansible state

1. `/app/environment/ansible/site.yml` targets `ciserver`, but the inventory
   group is `ci_control_plane`. The play can match no hosts and still exit 0.
2. The inventory binds `0.0.0.0:8000` instead of the required loopback
   address.
3. Role defaults use `/opt/ci-server`, `/var/log/ci-server`, and account
   `ci` instead of the contracted install tree and service account.
4. The directory task misses the service log directory and several state
   directories.
5. The build task writes `bin/ciserver`, then later tasks look for
   `bin/ci-server`.
6. The configuration template emits the old key names used by the broken Go
   loader.
7. The supervisord template uses the wrong program name, flag, working
   directory, and startup settings.
8. Tasks notify `Restart ci-server`, while the handler has a different name.
9. The smoke run calls old routes, sends the wrong auth header, and posts old
   request fields.
10. The report template still uses the old check names.

## Broken Go state

1. The configuration tags match the old Ansible template instead of the
   contract.
2. The loader hashes re-encoded JSON rather than the bytes read from disk.
3. It accepts empty credentials and lets both credentials match.
4. The binary accepts `--conf` instead of `-config`.
5. Health is exposed at the old path and returns the old digest field.
6. Auth accepts empty values, and webhooks read the API header.
7. Several routes and request fields still use their old names.
8. The status machine allows builds to skip claim or leave terminal states.
9. Store and listing code mishandles persistence, pagination, empty queues,
   artifact paths, and runner expiry.
10. A second runner can steal a running build.
11. Claim cleanup watches runner expiry but ignores the wall-clock lease.
12. The audit endpoint still behaves like the old history endpoint.

## Why it is advanced

The first visible bug is a silent no-op play, but that is only the start. Once
Ansible reaches the host, install errors expose a service that agrees with the
bad templates and disagrees with the contract. Concurrency adds another layer:
idempotent webhook storms and runner claim races must settle on one stored
result. Lease expiry, timeout, audit, and retention also share the same state,
so a local fix can break a later transition.

## Verification

The verifier receives `/app/var/ci-server`. It checks the installed tree,
configuration, supervisord program, deployment report, and the state written by
the smoke run. It then starts the submitted binary with scratch configurations
and drives the HTTP API through normal, invalid, concurrent, expiry, timeout,
retention, and restart cases.

## Oracle

`solution/solve.sh` restores the corrected Go and Ansible trees, runs
`/app/bin/ci-server-apply` twice, and checks that the deployment report was
written.

## Images

The agent uses the canonical Go 1.24 Bookworm image. The verifier uses the
canonical Python 3.13 slim Bookworm image. Both bases are pinned by digest, and
the service is built with `CGO_ENABLED=0`.
