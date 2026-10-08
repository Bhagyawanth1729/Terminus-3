The local Go CI service and its Ansible deploy stopped agreeing after a large edit. There is no clean copy to restore. Repair both sides under /app/environment and leave a working control plane.

- Run the finished deployment through /app/bin/ci-server-apply. It must compile /app/environment/ci-server, apply /app/environment/ansible, and install the service under /app/var/ci-server.

- Its state directory must hold pipelines, builds, artifacts, agents, log chunks, steps, audit events, idempotency records, and /app/var/ci-server/state/deploy-report.json.

- Keep the service behind supervisord under its own account. Configuration must control the listener, credentials, pagination, retention, heartbeat, lease, log, timeout, and concurrency limits. Bad or incomplete configuration must fail before the server starts.

- Keep API and webhook credentials separate. Pipeline names are case-insensitive, pause and branch rules block new work, webhook keys stay idempotent under concurrency, and the queue sorts by priority then arrival.

- The deployed tree must contain /app/var/ci-server/bin/ci-server, /app/var/ci-server/etc/ci-server.json, /app/var/ci-server/etc/supervisor/ci-server.conf, and /app/var/ci-server/logs. 

- Only online runners with spare capacity may claim work, and pipeline concurrency still applies. 

- Claims, timeouts, retries, cancellation, ordered logs and steps, artifact keys, retention, metrics, and audit history must follow the binding contract even across races and restarts.

- The apply must exercise the running service and build the deployment report from live responses and stored records. The report has only status, version, listen, config_digest, and checks. The contract defines the eleven string fields inside checks.

- A second apply must succeed without duplicating the bootstrap webhook build. Restarting the service must preserve claimed work and identifier counters.

- /app/environment/docs/requirements.md is the binding layout and protocol contract. Match its routes, schemas, errors, limits, state changes, and report fields. Do not rewrite it to excuse the current code.
