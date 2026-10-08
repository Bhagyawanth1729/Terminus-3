# CI server contract

This is the binding contract for the deploy and the service. It defines the
install tree, supervisord program, configuration, HTTP API, state changes,
persistence rules, smoke run, and deployment report. The task prompt explains
what needs to be repaired. This document says what the repaired system must do.

The server stores pipelines, queues builds for runners, records logs, steps,
artifacts, and audit events, and removes old finished builds when retention is
full.

## 1. Deployment layout

Everything the service needs lives under the prefix `/app/var/ci-server`.

| Path | Kind | Required properties |
|------|------|---------------------|
| `/app/var/ci-server/bin/ci-server` | file | compiled control-plane binary, mode `0755`, statically linked (`CGO_ENABLED=0`) |
| `/app/var/ci-server/etc/ci-server.json` | file | rendered configuration document, readable by the service account |
| `/app/var/ci-server/etc/supervisor/ci-server.conf` | file | supervisor program definition |
| `/app/var/ci-server/state` | directory | owned by the service account, mode `0775` |
| `/app/var/ci-server/state/pipelines` | directory | one record per pipeline |
| `/app/var/ci-server/state/builds` | directory | one record per build |
| `/app/var/ci-server/state/artifacts` | directory | one record per build that has artifacts |
| `/app/var/ci-server/state/agents` | directory | one record per registered runner |
| `/app/var/ci-server/state/logs` | directory | per-build directories of ordered log chunk records |
| `/app/var/ci-server/state/steps` | directory | one JSON array file per build that has steps |
| `/app/var/ci-server/state/audit` | directory | append-only audit events, one file per sequence number |
| `/app/var/ci-server/state/idempotency` | directory | webhook idempotency key → build id records |
| `/app/var/ci-server/state/deploy-report.json` | file | deployment report, see section 9 |
| `/app/var/ci-server/logs` | directory | supervisor captures service output here |

Run the service as the system account `ciserver` in group `ciserver`. That
account needs read access to the configuration and write access throughout
`/app/var/ci-server/state`.

Build the binary from `/app/environment/ci-server` during deployment. No
prebuilt service binary is provided.

## 2. Process supervision

There is no init system here. Supervisord loads the `ci-server` program from
`/app/var/ci-server/etc/supervisor/ci-server.conf` through the include in
`/etc/supervisor/supervisord.conf`.

The program definition must:

- use the literal supervisord section name `program:ci-server`
  (ini header `[program:ci-server]`),
- invoke `/app/var/ci-server/bin/ci-server` with `-config`
  `/app/var/ci-server/etc/ci-server.json` on the command line,
- run as the `ciserver` account,
- have `autostart` and `autorestart` enabled,
- send stdout and stderr to files under `/app/var/ci-server/logs`.

The `-config` flag selects the configuration file. Without it, the service uses
`/app/var/ci-server/etc/ci-server.json`.

## 3. Configuration document

`/app/var/ci-server/etc/ci-server.json` is a JSON object containing exactly these
keys, and no others:

| Key | Type | Meaning | Deployed value |
|-----|------|---------|----------------|
| `listen` | string | `host:port` the HTTP listener binds | `127.0.0.1:8080` |
| `state_dir` | string | absolute path of the state directory | `/app/var/ci-server/state` |
| `log_dir` | string | absolute path of the log directory | `/app/var/ci-server/logs` |
| `api_token` | string | credential for authenticated operations | value of the `ci_api_token` inventory variable |
| `webhook_token` | string | credential for webhook triggers | value of the `ci_webhook_token` inventory variable |
| `agent_ttl_seconds` | integer | runner heartbeat lifetime in seconds | `45` |
| `default_page_size` | integer | page size used when a request omits `per_page` | `5` |
| `max_page_size` | integer | largest `per_page` a request may ask for | `50` |
| `build_retention` | integer | maximum number of finished builds kept | `3` |
| `log_chunk_max_bytes` | integer | maximum UTF-8 byte length of one log chunk `text` | `4096` |
| `claim_lease_seconds` | integer | maximum age of a claim before it may expire | `120` |
| `max_log_chunks` | integer | maximum log chunks retained per build | `100` |
| `build_timeout_seconds` | integer | maximum time a build may stay `running` | `600` |
| `default_max_concurrent` | integer | default per-pipeline concurrent running builds | `2` |
| `version` | string | control-plane version reported by the service | `3.1.0` |

The deployed control plane binds to loopback because the production site proxy
sits in front of it. The rendered configuration must not use a wildcard host.

`api_token` and `webhook_token` are distinct credentials and must not be equal.

### Startup validation

Bad configuration must stop startup with a nonzero exit and no listener. Reject
invalid JSON, missing or unknown keys, relative `state_dir` or `log_dir` paths,
empty credentials, and matching API and webhook tokens. Also reject nonpositive
values for `agent_ttl_seconds`, `default_page_size`, `build_retention`,
`log_chunk_max_bytes`, `claim_lease_seconds`, `max_log_chunks`,
`build_timeout_seconds`, or `default_max_concurrent`. `max_page_size` cannot be
smaller than `default_page_size`.

### Configuration digest

`config_digest` is the lowercase SHA-256 hex digest of the configuration bytes
read from disk. Hash the file as written, before parsing it.

## 4. Authentication

| Surface | Header | Credential |
|---------|--------|------------|
| every state-changing request except webhooks | `X-Ci-Server-Token` | `api_token` |
| `POST /v1/hooks/{name}` | `X-Ci-Server-Webhook-Token` | `webhook_token` |

A missing, empty, or wrong credential returns `401` with
`{"error": "unauthorized"}`. The two credentials are not interchangeable.
Read-only requests need no credential.

Every error body is a JSON object with one `error` key containing the code
listed for that case.

## 5. HTTP API

All responses are JSON.

### `GET /healthz`

`200` with `status` (`"ok"`), `version`, `listen`, `config_digest`, `pipelines`
(number of registered pipelines) and `queued_builds` (number of builds in the
`queued` status).

### `POST /v1/pipelines`

Body: `name`, `repo`, `default_branch` (optional, defaults to `main`).

`201` with the pipeline object:

Body also accepts optional `allowed_branches` (array of branch name strings) and
optional `max_concurrent` (positive integer). When `allowed_branches` is omitted
or empty, every branch is accepted. When `max_concurrent` is omitted, the
configured `default_max_concurrent` is used.

```json
{
  "id": "pl-000001",
  "name": "checkout-service",
  "repo": "git@vcs.internal:platform/checkout-service.git",
  "default_branch": "main",
  "created_seq": 1,
  "paused": false,
  "allowed_branches": [],
  "max_concurrent": 2
}
```

`created_seq` starts at `1` and only increases. The `id` is `pl-` followed by
that sequence padded to six digits. Never reuse a sequence number. If the last
ID before a restart was `pl-000004`, the next one is `pl-000005`.

Pipeline names match `^[A-Za-z0-9][A-Za-z0-9._-]{1,39}$`. Anything else is `400`
`invalid_pipeline_name`. An empty `repo` is `400` `invalid_repo`. A
`max_concurrent` below `1` is `400` `invalid_max_concurrent`. Branch names in
`allowed_branches` must be non-empty strings of at most 64 characters. Anything
else is `400` `invalid_allowed_branches`.

Names are unique without regard to case. Registering an existing name under any
casing returns `409` `pipeline_exists`. New pipelines start with `paused` set
to `false`.

### `GET /v1/pipelines`

Query parameters `page` and `per_page`. Pages are one-based, so `page=1` returns
the first `per_page` pipelines ordered by ascending `created_seq`. Omitting
`page` means `1`. Omitting `per_page` means `default_page_size`.

`200` with `items` (array of pipeline objects), `page`, `per_page` and `total`.
`total` is the number of pipelines held by the control plane, not the length of
the page. A page beyond the end returns an empty `items` array with the same
`total`.

Return `400` `invalid_pagination` when `page` is below `1`, `per_page` is below
`1` or above `max_page_size`, or either value is not an integer.

### `GET /v1/pipelines/{id}`

`200` with the pipeline object, or `404` `pipeline_not_found`.

### `POST /v1/pipelines/{id}/pause`

API-token. Sets `paused` to `true`. `200` with the pipeline object. Already
paused is still `200`. Unknown pipeline is `404` `pipeline_not_found`.

### `POST /v1/pipelines/{id}/resume`

API-token. Sets `paused` to `false`. `200` with the pipeline object. Already
active is still `200`. Unknown pipeline is `404` `pipeline_not_found`.

### `POST /v1/hooks/{name}`

Webhook trigger. `{name}` resolves a pipeline by name, ignoring case. Optional
body key `branch`. When absent, the pipeline's `default_branch` is used. Optional
body key `params`: an object of string values used as build parameters. Optional
body key `priority`: integer from `0` to `100` inclusive (default `50`). Higher
priority builds leave the queue sooner.

The optional `Idempotency-Key` header must match
`^[A-Za-z0-9._:-]{1,64}$`. A repeated key for the same pipeline returns `202`
with the original build object and does not create a second build. Concurrent
requests with the same key for the same pipeline must converge on one build.
Keys are stored under
`/app/var/ci-server/state/idempotency/`. A malformed key is `400`
`invalid_idempotency_key`.

`202` with `build_id`, `pipeline_id`, `status`, `branch`, `params` and
`priority`. Unknown pipeline is `404` `pipeline_not_found`. A paused pipeline is
`409` `pipeline_paused`. A branch not listed in a non-empty
`allowed_branches` is `409` `branch_not_allowed`.

`params` rules: at most 8 keys. Each key matches `^[A-Za-z0-9_]{1,32}$`. Each
value is a string of at most 256 characters. Anything else is `400`
`invalid_params`. A `priority` outside `0..100` is `400` `invalid_priority`.

### `GET /v1/builds/{id}`

`200` with the build object:

```json
{
  "id": "bd-000001",
  "pipeline_id": "pl-000001",
  "pipeline_name": "checkout-service",
  "status": "queued",
  "branch": "main",
  "trigger": "webhook",
  "queued_seq": 1,
  "params": {},
  "priority": 50
}
```

After a successful claim the object also carries `claimed_by` (the claiming
`agent_id`) and `claimed_at` (unix seconds when the claim was accepted). A retry
build carries `retried_from` (the prior build id). A canceled build carries
`cancel_reason` when one was supplied.

`queued_seq` starts at `1` and only increases. The `id` is `bd-` followed by
that sequence padded to six digits. Build IDs follow the same restart rule as
pipeline IDs. An unknown build returns `404` `build_not_found`.

### `GET /v1/queue`

Before listing, the control plane reaps expired claims and timed-out builds
(see sections 12 and 13).

`200` with `items` and `count`. Include only `queued` builds, sorted by
descending `priority` and then ascending `queued_seq`. Running and finished
builds do not appear. An empty queue returns `items: []` and `count: 0`, not
JSON null.

### `POST /v1/builds/{id}/claim`

Body: `agent_id`. Reaps expired claims and timed-out builds first, then moves a
`queued` build to `running` and records the claim. `200` with the updated build
object.

`agent_id` matches `^[A-Za-z0-9][A-Za-z0-9._-]{1,39}$`. Anything else is `400`
`invalid_agent_id`. The claiming agent must be online. If not, return `409`
`agent_offline`. The number of builds already `running` for that agent
must be lower than the agent's `capacity`. Otherwise return `409`
`agent_at_capacity`. The number already `running` for the pipeline must be
lower than `max_concurrent`. Otherwise return `409`
`pipeline_at_capacity`. An unknown build is `404` `build_not_found`. A build
that is not `queued` is `409` `already_claimed` when it is already `running`
under a different agent. Re-claiming a `running` build with the same
`agent_id` that already holds the claim is `200` with the current build object
(no audit event). Any other non-queued status is `409` `invalid_transition`.

The status endpoint cannot move a build from `queued` to `running`. Only a claim
starts a build. When runners claim the same build at once, one gets `200` and
the others get `409` `already_claimed`. The current holder may repeat its own
claim and receive `200` without a new audit event.

### `POST /v1/builds/{id}/status`

Body: `status`, and when `status` is `canceled` a non-empty `reason` string of
at most 200 characters. `200` with the updated build object.

A status name outside the five below is `400` `invalid_status`. Canceling
without a usable `reason` is `400` `invalid_cancel_reason`. An unknown build is
`404` `build_not_found`. A transition the machine forbids is `409`
`invalid_transition`.

After a transition into a terminal status (`success`, `failed`, `canceled`), the
control plane enforces `build_retention` (see section 10).

### `POST /v1/builds/{id}/logs`

Body: `seq` (integer), `text` (string). Appends one ordered log chunk while the
build is `running`. `201` with `build_id`, `seq` and `text`.

`seq` must start at `1` for the first chunk and each later chunk must be exactly
one greater than the previous. A gap or duplicate is `409` `invalid_log_seq`.
`text` must be non-empty and at most `log_chunk_max_bytes` UTF-8 bytes, otherwise
`400` `invalid_log_chunk`. A build that already holds `max_log_chunks` chunks is
`409` `log_limit_reached`. A build that is not `running` is `409`
`build_not_running`. Unknown build is `404` `build_not_found`.

Chunks are persisted under
`/app/var/ci-server/state/logs/{build_id}/{seq}.json` with zero-padded six-digit
`seq` in the filename (for example `000001.json`).

### `GET /v1/builds/{id}/logs`

`200` with `items` (chunk objects ordered by ascending `seq`) and `count`.
Unknown build is `404` `build_not_found`. A build with no chunks yet returns an
empty `items` array and `count` of `0`.

### `POST /v1/builds/{id}/steps`

API-token. Body: `name`, `status` (`running`, `success` or `failed`). Records an
ordered step against a `running` build. `201` with `build_id`, `seq`, `name` and
`status`.

`name` matches `^[A-Za-z0-9][A-Za-z0-9._-]{1,39}$`. Anything else is `400`
`invalid_step_name`. An unknown `status` is `400` `invalid_step_status`. A build
that is not `running` is `409` `build_not_running`. Unknown build is `404`
`build_not_found`.

Steps are persisted as a JSON array at
`/app/var/ci-server/state/steps/{build_id}.json`, ordered by ascending `seq`
starting at `1`.

### `GET /v1/builds/{id}/steps`

`200` with `items` and `count`. Unknown build is `404` `build_not_found`.

### `POST /v1/builds/{id}/retry`

API-token. Creates a new `queued` build for the same pipeline, branch and
`params`, with `trigger` `"retry"` and `retried_from` set to the source build
id. Source status must be `failed` or `canceled`. Otherwise return `409`
`invalid_retry`. `201` with the new build object. Unknown build is `404`
`build_not_found`. Retrying a paused pipeline is `409` `pipeline_paused`.

### `POST /v1/builds/{id}/artifacts`

Body: `path`, `size_bytes`, `sha256`. `201` with `build_id`, `path`,
`size_bytes` and `sha256`.

Artifacts may only be recorded against a build that has left the `queued`
status. Recording one against a queued build is `409` `build_not_started`. A
path already recorded for that build is `409` `artifact_exists`. An unknown
build is `404` `build_not_found`.

### `GET /v1/builds/{id}/artifacts`

`200` with `items` (artifact objects ordered by ascending `path`) and `count`.
`404` `build_not_found` for an unknown build.

### `POST /v1/agents/heartbeat`

Body: `agent_id`, `capacity`. `200` with `agent_id`, `capacity` and
`expires_in_seconds` (the configured `agent_ttl_seconds`).

`agent_id` matches `^[A-Za-z0-9][A-Za-z0-9._-]{1,39}$`. Anything else is `400`
`invalid_agent_id`. A `capacity` below `1` is `400` `invalid_capacity`.

### `GET /v1/agents`

`200` with `items` and `count`. Each item carries `agent_id`, `capacity` and
`state` (`"online"`), ordered by ascending `agent_id`.

### `GET /v1/audit`

Query parameters `page` and `per_page` with the same rules as pipeline listing.

`200` with `items` (audit objects ordered by ascending `seq`), `page`,
`per_page` and `total`. Each audit object:

```json
{
  "seq": 1,
  "at": 1710000000,
  "action": "build_claimed",
  "build_id": "bd-000001",
  "pipeline_id": "pl-000001",
  "detail": "bootstrap-runner"
}
```

Audit files live at `/app/var/ci-server/state/audit/{seq}.json` with
zero-padded six-digit `seq` in the filename. Mutating operations that must
append an audit event are: `pipeline_created`, `pipeline_paused`,
`pipeline_resumed`, `build_queued`, `build_claimed`, `claim_expired`,
`build_timed_out`, `status_changed`, `log_appended`, `step_recorded`,
`artifact_added`, `build_retried`. Heartbeats do not create audit events.

### `GET /v1/metrics`

API-token. `200` with exact counts derived from live state after reclaiming
expired claims and timed-out builds:

```json
{
  "pipelines": 1,
  "queued_builds": 0,
  "running_builds": 1,
  "finished_builds": 0,
  "online_agents": 1,
  "audit_events": 4
}
```

## 6. Build status machine

Statuses: `queued`, `running`, `success`, `failed`, `canceled`.

| From | Permitted next | How |
|------|----------------|-----|
| `queued` | `running` | `POST .../claim` only |
| `queued` | `canceled` | `POST .../status` |
| `running` | `success`, `failed`, `canceled` | `POST .../status` |
| `success` | none | none |
| `failed` | none | none |
| `canceled` | none | none |

A new build starts as `queued`. It can reach success or failure only after it
has run. Terminal states are final, and setting the current status again is not
a valid transition.

## 7. Artifact paths

`path` is a key inside the build's own artifact namespace, not a filesystem
location. It is rejected with `400` `invalid_artifact_path` when it is empty,
longer than 200 characters, absolute, contains a backslash, contains an empty
segment (including a doubled separator), or contains a `.` or `..` segment
anywhere. Check the path as received. Do not normalize it first.

`sha256` is exactly 64 lowercase hexadecimal characters, otherwise `400`
`invalid_artifact_digest`. A negative `size_bytes` is `400`
`invalid_artifact_size`.

## 8. Runner heartbeats

A heartbeat records its arrival time. A runner stays online while the age of
its latest heartbeat is strictly less than `agent_ttl_seconds`. At the limit it
becomes offline and disappears from `GET /v1/agents`. The configured value is
in seconds.

## 9. Deployment report

The deployment writes `/app/var/ci-server/state/deploy-report.json` as its last
step, after it has exercised the running service. The top-level object has
exactly the keys `status`, `version`, `listen`, `config_digest` and `checks`
(no others). `checks` has exactly these eleven keys: `health`,
`pipeline_registered`, `webhook_build`, `build_claimed`, `log_appended`,
`step_recorded`, `status_transition`, `artifact_recorded`, `agent_registered`,
`audit_total`, `metrics_running`. Every value is a JSON string taken from a
live response of the deployed control plane:

```json
{
  "status": "ok",
  "version": "3.1.0",
  "listen": "127.0.0.1:8080",
  "config_digest": "<from GET /healthz>",
  "checks": {
    "health": "<status field of GET /healthz>",
    "pipeline_registered": "<HTTP status of the bootstrap pipeline registration>",
    "webhook_build": "<build_id returned by the bootstrap webhook trigger>",
    "build_claimed": "<claimed_by returned by the bootstrap claim>",
    "log_appended": "<seq returned by the bootstrap log chunk, as a string>",
    "step_recorded": "<name of the bootstrap step>",
    "status_transition": "<status field of the build after it is claimed>",
    "artifact_recorded": "<path field returned when the bootstrap artifact is recorded>",
    "agent_registered": "<agent_id returned by the bootstrap runner heartbeat>",
    "audit_total": "<total field of GET /v1/audit, as a string>",
    "metrics_running": "<running_builds field of GET /v1/metrics, as a string>"
  }
}
```

`version` and `listen` mirror the configuration document. `config_digest` must
match a digest recomputed from the exact bytes of the deployed configuration
file (same rule as section 3). `checks.webhook_build` matches `^bd-\d{6}$`.
`checks.build_claimed` is the bootstrap runner identifier.

Read the bootstrap pipeline, repository, branch, runner ID, artifact path, and
artifact digest from the matching inventory variables. Heartbeat the bootstrap
runner before its claim so it is online and has capacity. Use that runner ID as
`agent_id`. The bootstrap webhook sends header
`Idempotency-Key` with value `bootstrap-smoke` and may omit `params`. The
bootstrap log chunk uses `seq` `1` and a non-empty `text`. The bootstrap step
uses name `bootstrap` and status `running`. Re-running the deployment is
valid when the bootstrap pipeline already exists. Reusing the same idempotency
key must not create another build for that pipeline and key.

## 10. Build retention

Finished builds are those whose status is `success`, `failed` or `canceled`.
After every transition into a terminal status, if the number of finished builds
exceeds `build_retention`, the control plane deletes the oldest finished builds
(lowest `queued_seq` first) until at most `build_retention` finished builds
remain. Deleting a build removes its build record, its artifact record (if any),
its steps file and its entire log chunk directory under `state/logs/{build_id}/`.
Pipelines, agents and the audit log are not removed by retention.

## 11. Apply and workspace paths

`/app/bin/ci-server-apply` runs the Ansible under `/app/environment/ansible`.
That play compiles the Go module at `/app/environment/ci-server` with the Go
toolchain on the host, installs under supervisord, and leaves the control plane
at `/app/var/ci-server` per the layout in section 1 (binary, `etc/ci-server.json`,
supervisor program, `state/` with `pipelines/`, `builds/`, `artifacts/`,
`agents/`, `logs/`, `steps/`, `audit/`, `idempotency/`,
`state/deploy-report.json`, and supervisor `logs/`).

Binding reference for schemas and behaviour: `/app/environment/docs/requirements.md`.
A second apply on the same host must still succeed. The running binary must
honour whatever `-config` file it is given for listen address, tokens,
heartbeat lifetime, page sizes, build retention, log chunk limits, claim lease,
max log chunks, build timeout and default max concurrent.

## 12. Claim lease expiry

A `running` build's claim is expired when either:

1. `now - claimed_at` is greater than or equal to `claim_lease_seconds`, or
2. the claiming agent is not online under the heartbeat rules in section 8.

Reap expired claims before `GET /v1/queue`, `GET /v1/metrics` and
`POST /v1/builds/{id}/claim`. Reaping sets the build back to `queued`, clears
`claimed_by` and `claimed_at`, and appends a `claim_expired` audit event. Log
chunks and steps already recorded for that build are kept. After a lease
expires, further log or step writes must fail with `build_not_running` until a
runner claims the build again. Wall-clock lease expiry applies even when the
claiming agent is still heartbeating.

Claim expiry is checked before build timeout. If both limits are reached in the
same reap pass, return the build to `queued` as an expired claim. Do not time it
out in that pass.

## 13. Build timeout

A `running` build whose claim age reaches `build_timeout_seconds` times out in
the reap pass unless claim expiry has already returned it to the queue. A
timeout sets the build to `failed`, clears the claim fields, appends a
`build_timed_out` audit event, and applies retention. A timed-out build counts
as finished.
