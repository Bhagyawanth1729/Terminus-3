# Terminus 3 — Complete Task Creation Prompt (Ideation → Build → Submit)

You are an expert Terminus 3 task designer, authoring for Terminal-Bench 3.0. Work through the phases in order. Each phase's output is a locked input to the next — do not revisit an earlier phase's decision without re-checking everything downstream of it.

**Your role:** design tasks grounded in a real domain that challenge frontier models; write oracle solutions that demonstrate correct completion; build verifiers that check semantics, not appearance; iterate on feedback from automated checks and peer review.

**Evaluation pipeline (each submission):** automated CI (structure, manifest, dependencies, verifier isolation) → LLM-as-Judge (LLMaJ) → peer review → agent evaluation against GPT-5.6 and Claude Opus 5 (4 trials per model after acceptance).

**Ground truth for file structure:** `reference-skeleton/` (extracted from the official Task Skeleton). If this prompt conflicts with the skeleton, the skeleton wins.

---

# TASK REQUIREMENTS (mandatory gates)

Every task must satisfy **all** of the following. See Task Components (Phase C) for file structure.

| Requirement | Rule |
|---|---|
| **Novel** | New setup, definition, and data — not a variation of TB 2.1, TB 3.0, or prior Terminus editions. Reskinning (same computation, different cover story/names/language) is not novelty. Near-duplicates are caught by **embedding similarity**. |
| **Multi-step** | Chaining commands with intermediate state, error recovery, branching, or reacting to prior output. Not solvable in one command or one straight-line burst. **Ask:** "Could an agent finish this in one shot without reacting to anything along the way?" If yes → too simple. "~5 agent steps" is a complexity heuristic — nothing counts steps; a 30-minute-minimum task naturally exceeds it. |
| **Testable** | Fully specified and self-contained; solvable without ambiguity; deterministic tests measure final environment state. |
| **Standalone** | Runs to completion without human input. All parameters via files, flags, or environment variables — **no interactive prompts**, no mid-run decisions. Validated in Harbor: single-container tasks in **Daytona**, multi-container in **Docker**. |
| **Runtime** | `[agent].timeout_sec` ≥ **1800** (floor, not target), ceiling **18000**. Most tasks land **60–90 minutes**. Completing in under ~30 minutes usually means the task isn't deep enough. Set timeout to what the work needs — padding a short task doesn't add difficulty; starving a long one creates false failures. |
| **Internet access** | All three phases must declare `network_mode` — omission silently inherits the baseline and **blocks submission**. See C2 for the full policy. |
| **Compute** | No GPU. Oracle must run within ~**8 GB** memory, **2** CPU cores, **~10 GB** storage. GPU-adjacent work: see ML/Kernels subcategory (CPU-simulated / compile-only patterns). |
| **Languages** | Record primary language(s) in `[metadata].languages`. Multi-language tasks preferred. Approved list: Python, C, C++, JavaScript, TypeScript, Java, Go, Rust, C#. Domain toolchains (HDL, proof assistants, CAD scripting, query languages) are welcome in the environment even if not listed. **Difficulty tiers are language-independent** (Terminus 2's "Python must be HARD" rule is gone). |
| **No canary strings** | In any component — instruction, environment, solution, tests, metadata. This is a training dataset; canaries keep benchmark data out of training corpora. |
| **Instruction prompts** | ~2 short paragraphs or ≤20 bullets; state the goal, not intermediate steps; human-written (AI-generated text is screened). |
| **Dependency pinning** | Every `FROM` digest-pinned; pip/npm exact-pinned. Verifier tooling baked into `tests/Dockerfile` — **never installed at trial time**. `tests/test.sh` must **never fetch from the network** at grade time. |
| **Rubrics** | Authored in the platform UI; Snorkel adds `rubrics.txt` at packaging — you don't ship it. |

---

# PHASE A — IDEATION

## A1. Pick a category and subcategory

Set exactly one of each in `[metadata]` — Title Case, exact match:

```toml
[metadata]
category = "Science"
subcategory = "Chemistry"
```

**Choosing your category:** pick the category describing the **domain the task lives in**, then the subcategory describing the **specific work**. The most common mistake is defaulting to Software because the task involves code — nearly every task involves code. Ask: **what does the agent have to understand to get this right?**

- Debugging a training loop → **ML / Training**, not Software / Systems
- Parsing mass spectra to infer molecular structure → **Science / Chemistry**, not Software / Algorithms
- Reserve **Software** for tasks where software engineering itself is the subject matter

If a task genuinely spans two categories, choose the one whose domain knowledge the agent **cannot succeed without**.

✅ Cross-check: if you deleted the domain framing and it became a generic scripting task, you picked the wrong category.

### Science
Natural sciences, mathematics, and engineering science.

| Subcategory | Scope |
|---|---|
| **Biology** | Genomics, proteomics, structural/computational biology, bioinformatics |
| **Chemistry** | Molecular structure, spectra, crystallography, reaction/property analysis |
| **Physics** | Simulation and numerical modeling of physical systems, including electromagnetic/FDTD device simulation and inverse design |
| **Earth** | Earth, climate, hydrology, and environmental modeling |
| **Robotics** | Dynamics, trajectory optimization, control |
| **Math** | Formalized mathematics and theorem proving (Coq/Lean/Isabelle), formal verification |
| **Linguistics** | Computational and historical linguistics |

### Software
General software engineering — where the **domain is software**.

| Subcategory | Scope |
|---|---|
| **Algorithms** | Algorithmic problems, solvers, computational geometry, optimization |
| **Systems** | Concurrency, backends, distributed systems, infrastructure; build pipelines, bundling, release engineering |
| **Databases** | Storage engines, transactions, indexing, recovery |
| **Data engineering** | ETL, record linkage, data processing at scale; ontologies, RDF/OWL, SPARQL, knowledge graphs |
| **Frontend** | Web/UI applications and their client/server pipelines |
| **Languages** | Language tooling, compilers, program analysis |

### ML
Machine-learning training, serving, evaluation, and infrastructure.

| Subcategory | Scope |
|---|---|
| **Training** | Training loops, optimization, debugging training runs; training infrastructure (checkpointing, cluster recovery, data integrity) |
| **Inference** | Inference implementations and LLM serving stacks; serving infrastructure, production monitoring/drift |
| **Evaluation** | Eval harnesses, benchmark construction, grading |
| **Kernels** | Custom compute kernels and accelerator programming — CPU-simulated or compile-only (see below) |

**Kernels without a GPU:** tasks must not require a GPU, but kernel/accelerator work is still in scope via two patterns:
1. **CPU-simulated kernels** — agent implements kernel logic; verifier checks numerical correctness against a reference on CPU
2. **Compile-only verification** — verifier checks the kernel compiles and passes static/structural checks without executing on device

All other requirements still apply: deterministic tests, oracle within compute limits, separate verifier container.

### Operations
Business, financial, and operational domain reasoning.

| Subcategory | Scope |
|---|---|
| **Finance** | Quantitative finance, risk, regulatory capital |
| **Logistics** | Dispatch, routing, fleet/flight planning, transportation |
| **Supply chain** | Procurement, production planning, manufacturing, ERP |
| **Claims** | Insurance/utility claims, billing rules, adjudication |
| **Compliance** | Regulatory reporting and compliance workflows |
| **Marketing** | Ads, CTR, marketing analytics |

### Security
Offensive and defensive security.

| Subcategory | Scope |
|---|---|
| **Cryptography** | Ciphers, cryptographic protocols and analysis |
| **Reverse engineering** | Binary RE, vulnerability hunting and patching, malware/backdoor analysis |
| **Forensics** | Network/host forensics, incident analysis and remediation |
| **AppSec** | Application- and web-layer vulnerabilities and defenses |

### Hardware
Physical and digital hardware design.

| Subcategory | Scope |
|---|---|
| **CAD** | Parametric CAD, mechanical part design |
| **RTL** | HDL, RTL, digital logic |

### Media
Creative and design work.

| Subcategory | Scope |
|---|---|
| **Music** | Music theory, audio transcription and processing |
| **Design** | Visual/layout design and reconstruction |

## A2. Pick a target difficulty tier

Difficulty is **measured, not declared** — from accuracy (average pass@1) across GPT-5.6 and Claude Opus 5 over **8 runs** (4 per model). Treat the tier below as a target only, never something to engineer backward from — piling on requirements to force a "Frontier" label is fake difficulty (see disqualifiers in B1). The real tier is set empirically in Phase D2.

| Tier | Measured accuracy | Target share of tasks (authoring guidance) |
|---|---|---|
| **Frontier** | < 20% | 20–30% |
| **Advanced** | 20% – < 50% | 25–35% |
| **Core** | 50% – < 80% | 30–40% |
| **Base** | 80% – < 100% | 5–15% |

Frontier/Advanced are the most valuable to author. **Base is a valid tier** — unlike Terminus 2, pass rates above 80% are accepted, not rejected. The only unacceptable outcome is **100%** (no agent ever fails → no signal).

## A3. Generate 3 original topics within that category/subcategory

Each topic must:
- Be realistic and novel — not a variation of any Terminal-Bench 2.1, Terminal-Bench 3.0, Terminus prior edition, or Terminal Bench Edition 1 task. Each topic must introduce a **new setup, definition, and data**. Reskinning — same computation under a different cover story, different variable names, or different language — is not novelty; near-duplicates are detected automatically via **embedding similarity**
- Work entirely inside a Linux terminal / container environment
- Involve **repairing a broken implementation** (not building from scratch) — a realistic system with defects reaching below the visible symptom
- Require multi-step reasoning: chaining commands, handling intermediate/live state, reacting to what a previous step reveals (not solvable in one shot or one straight-line burst). Ask: *could an agent finish this without reacting to anything along the way?*
- Have a specification that must be partly **inferred** from domain evidence (a spec file, dataset, design doc, or convention) rather than stated as a checklist
- Combine at least two **interacting** correctness axes (e.g., functional correctness + performance, or safety + state consistency) — not just a long list of independent checks
- Be gradeable by a deterministic, semantic verifier — not appearance-matching

For each topic, provide:
- Topic name
- One-paragraph scenario (grounded in the chosen category/subcategory's domain)
- Why the task is difficult — map explicitly to which of the six properties it exercises (see Phase B1)
- Expected debugging/reasoning challenges
- A rough guess at difficulty tier — to be confirmed empirically later, not assumed

## A4. Compare and select

1. Compare the three topics against the disqualifiers: reject any that are hard mainly due to ambiguity, unrelated-requirement pileup, obscure trivia, or non-determinism.
2. Check each topic against early warning signs, before any building starts:
   - **Too easy** if: single-step solution, a common tutorial topic, simple API usage, or pattern matching alone would suffice.
   - **Too hard / unfair** (not the good kind of hard) if: it requires information the agent has no way to obtain, the environment would be inherently unreliable, success would depend on luck, or requirements are internally contradictory.
3. Select the strongest benchmark candidate.
4. Explain why — cite which properties it satisfies most strongly and why the constraints genuinely interact rather than just co-existing.

Lock the selected topic before proceeding to Phase B.

---

# PHASE B — DESIGN

Terminal-Bench 2.1 asked agents to perform a difficult terminal or software task. Terminal-Bench 3.0 asks something different: **understand a specialized domain, manipulate the right system or artifact inside it, and prove the result satisfies interacting hidden invariants.** This is not simply "harder" — difficulty moves from isolated technical execution toward vertically integrated engineering.

Strong tasks usually follow this chain:

```
specialized evidence
        ↓
domain-specific inference
        ↓
algorithm/system manipulation
        ↓
native artifact or live state
        ↓
hidden, structural, performance, and safety verification
```

## B1. Design against the six properties

A strong task needs most/all of:

1. **The specification must be inferred.** The correct model of the problem is not handed over as a checklist. The agent has to work out what the requirements mean in the domain before implementing anything — reconstructing structure from instrument output, deriving geometry from an engineering drawing, inferring rules from examples.

2. **Output semantics matter, not appearance.** Require a native, structurally valid artifact: an editable parametric feature tree rather than a baked mesh, a checkable proof without admits, synthesizable RTL, correctly mutated live database state. Producing something that merely looks similar must not pass.

3. **Correctness is multidimensional.** Rather than one dominant axis, combine several that must hold simultaneously — functional correctness, performance, determinism, safety, provenance, state consistency, structure, generalization to hidden instances.

4. **Constraints interact.** The point is not that constraints are numerous, but that they affect one another: a navigation error changes fuel burn, which changes feasible routing, which changes crosswind exposure. Interacting dependencies are far more demanding than a list of independent assertions.

5. **State is part of the problem.** Strong tasks often are not "edit files and run pytest." They involve operating databases under live traffic, stream processors, ERP workflows, model-serving runtimes, or multi-service systems — understanding current state, sequencing operations correctly, recovering from partial progress, and validating the result from a clean process.

6. **Hidden checks probe understanding.** Verify semantic equivalence across variations and metamorphic properties, not just more examples. A solution should not pass by satisfying the author's happy path alone — and must exercise every documented behavior on its hard instance, not a degenerate one. A rule tested only on the easy case (e.g., an ordering rule tested only where timestamps are distinct) is not really tested.

**From TB-style to Terminus 3-style** (aim for the right column):

| TB-style | Terminus 3-style |
|---|---|
| Compile and repair a package | Repair a runtime while preserving batching, caching, streaming, numerical, and performance semantics |
| Recover a fixed database file | Maintain recovery ordering guarantees, or perform a zero-downtime live cutover |
| Solve an explicitly specified scheduling problem | Operate dispatch or ERP state under capacity, lineage, safety, and workflow constraints |
| Read a value from an image and compute output | Infer geometry from a drawing and construct an editable parametric model |
| Implement an algorithm | Produce a behaviorally compatible, performance-qualified reimplementation under hidden workloads |
| Process a scientific dataset | Infer the scientific interpretation, implement the analysis, and emit convention-correct, provenance-preserving results |

**Enforce constraints architecturally, not just by asking nicely**: read-only files, banned imports/constructs, required APIs the verifier imports directly, pinned commit checkouts (prevents "read newer commits" shortcuts).

🚫 **What still disqualifies a task**

A task must **reject a wrong solution**, not merely accept a right one. Before you submit, run a deliberately wrong, incomplete, or lazy solution against your own verifier. If it passes, the task is disqualified — confirming the oracle passes proves nothing about whether a wrong one fails, and the latter is the only question the verifier exists to answer.

Difficulty must come from the **problem**, never from:
- Ambiguity, non-determinism, unstated requirements, or hidden knowledge the agent could not possibly obtain
- Piling on unrelated independent requirements (length, not difficulty)
- Obscure trivia with no reasoning behind it

A task is also disqualified if the agent can **shortcut** it — reaching the answer or satisfying checks without doing the work:

*The answer is reachable:*
- Held-out inputs staged next to their expected outputs (program copies the sibling)
- A sealed directory the graded process can still read
- Agent's prior output left at a predictable path to replay
- Ground truth derived from agent-writable paths (`/app`, mutable corpus, agent-delivered trees) — the agent can edit the truth, not just read it
- Reading test files, verifier logic, or `solution/`; writing `/logs/verifier/reward.txt` directly; unpinned git history

*The checks are hollow:*
- Proxy assertions a wrong answer also satisfies (count, first element, field presence but not value, expected result reconstructed from agent-controlled input)
- Grading a delivered binary without rebuilding from the agent's final source at grade time
- Grading two artifacts the agent controls both sides of (simulated vs synthesized build, library and its consumer) without proving they agree
- Staging copies that follow symlinks into protected fixtures
- Grading the wrong optimization objective or tie-break when the spec defines one

*A documented behavior is never exercised:* a required command or mode the tests reference but never run can be broken or hardcoded and still pass.

*The contract drifts:* instructions state one numeric tolerance but tests enforce a tighter (or looser) one; or the spec names an objective the verifier never distinguishes from a weaker feasible plan.

See C6 for how to close each hole in the verifier.

**Hidden requirement vs. under-specification** (the subtle line): a hidden requirement is *discoverable* — the agent can find it in a config, spec file, or domain convention. Under-specification means the goal itself is unclear. First is good design; second is a broken task.

---

# PHASE C — BUILD

## C1. Write `instruction.md`

**Length**: ~2 short paragraphs or up to 20 bullets (guidance, not a hard wall — complex tasks may need more room).

Each task is a **single-shot, outcome-verified** problem: state the goal up front; do not enumerate intermediate steps the agent should take. Must run **standalone** — no interactive prompts; all parameters via files, flags, or environment variables.

**Must:**
- State the **what** (requirements/goal), never the **how** (steps, exact values, hints)
- Use **absolute paths** only (`/app/output.json`, never `config/settings.json`)
- Name **every file** your tests will read or write
- Specify **exact output format/schema** if output is structured (JSON/CSV field names, types, required vs. optional)
- Read like a real person prompting a coding agent — no emojis, minimal markdown headers, not LLM-generated (screened automatically)
- Be genuinely interesting/useful to real developers
- Be unique (per A3's novelty rule)

**Must NOT:**
- Enumerate step-by-step instructions or exact values to set
- Include a "detection guidance" / hints section
- Mention specific tools unless verifiable ("use vim" is unverifiable — verify the *result* instead)
- Contain the task's own name or a canary string
- Be split across files to dodge the length limit — supporting spec/README files may define **what** (schemas, protocols, like a real API contract/RFC) but never **how**, and must look like a real engineering doc, not a polished LLM-style template

✅ Cross-check: every requirement (explicit + implicit + edge case) here must have exactly one test in C6, and every test in C6 must trace back to something stated or clearly implied here.

**Vague → specific, concretely** — when self-checking for ambiguity, look for phrases like these and replace them:
| Vague | Specific |
|---|---|
| "Make it better" | "Reduce runtime by 50%" |
| "Fix the issues" | "Fix the 3 failing tests" |
| "Handle errors properly" | "Return HTTP 400 for invalid input" |
| "Optimize the code" | "Achieve O(n log n) complexity" |
| "Process the data and save results" | "Process `/data/input.csv` and save results to `/output/results.json`" |

If a sentence in your draft instruction could be satisfied in several incompatible ways, it's still vague — replace it with the specific, checkable version.

## C2. Write `task.toml`

Confirmed against the official skeleton (`reference-skeleton/`, extracted from `default-template.zip`) — this structure is authoritative:

```toml
name = "your-task-name"                  # top-level, kebab-case, matches folder name

# Paths the SEPARATE verifier reads from the agent's final container.
# Declare the whole project dir (e.g. "/app/") when the verifier needs to
# rebuild/re-run the agent's own sources, not just inspect one output file.
artifacts = ["/app/"]                    # top-level — never nest under [verifier]

[metadata]
author_name = "anonymous"
author_email = "anonymous"
category = "..."                         # locked in A1 — one of 7 exact category names
subcategory = "..."                      # locked in A1 — must match taxonomy exactly (Title Case)
tags = ["tag1", "tag2", "tag3"]          # 3–6
languages = ["python"]                   # primary language(s) agent mainly works in — from: python, c, c++, javascript, typescript, java, go, rust, c#; multi-language preferred
difficulty = "..."                       # base | core | advanced | frontier — set from measured pass rate, not by feel
expert_time_estimate_hours = 6
difficulty_explanation = "..."           # what specifically defeats a strong agent — name the concrete traps
solution_explanation = "..."             # the reference approach, what has to be discovered and in what order
verification_explanation = "..."         # what the verifier grades and why partial/faked work still fails
relevant_experience = "..."              # your actual background — generic statements fail review
# is_multi_container = true              # ONLY under [metadata] when environment/docker-compose.yaml runs multiple services; omit otherwise

[verifier]
timeout_sec = 600                        # max verifier runtime — scale to task (official examples use up to 1800)
network_mode = "no-network"              # normally "no-network"; verifier deps belong in tests/Dockerfile
environment_mode = "separate"            # always "separate" — verifier runs in tests/Dockerfile container

[agent]
timeout_sec = 3600                       # min 1800, ceiling 18000; most tasks sit around 3600–5400
network_mode = "no-network"              # "public" or "no-network" — set explicitly

[environment]
network_mode = "public"                  # MUST always be "public" — image build and harness install need network
build_timeout_sec = 600                  # max environment build runtime
cpus = 2
memory_mb = 8192
storage_mb = 10240                       # no GPU; ~2 cores, ~8 GB, ~10 GB
```

**Separate verifier container** (most important structural change): grading no longer runs inside the agent's environment. The verifier is built from `tests/Dockerfile` and runs isolated — `tests/` and `solution/` are never visible to the agent. The verifier only reads paths declared in top-level `artifacts`.

⚠️ **`network_mode` is set in three places — all required; missing values block submission.**

```toml
[environment]
network_mode = "public"          # MUST be "public" on every task — image build + harness install need network

[agent]
network_mode = "no-network"      # "public" or "no-network" — yours to choose

[verifier]
network_mode = "no-network"      # "public" or "no-network" — normally "no-network"
```

| Task needs | `[agent]` | `[verifier]` |
|---|---|---|
| Solved offline (most common) | `"no-network"` | `"no-network"` |
| Agent genuinely needs internet | `"public"` | `"no-network"` |

- Omission **silently inherits** the environment baseline — the static check reports each missing phase and **blocks submission**
- Offline tasks: keep `[environment]` `"public"`, set `[agent]` to `"no-network"` — that stops the agent reaching the network while working
- The platform grants the **harness** its gateway access separately — you don't need to open the network for agent tooling
- **`"allowlist"` is not supported**; `allowed_hosts` is rejected — tasks using these are refused at creation (Oracle shows 0 trials)
- **Top-level `network_mode` is ignored** — Harbor drops unrecognized root keys; it must live under `[environment]`, `[agent]`, and `[verifier]`
- Legacy `allow_internet` field is **rejected** — cannot express per-phase policy
- Dependencies must be **baked into images at build time**. A public `[verifier]` is **not** license to install at grade time — `tests/test.sh` must never fetch from the network at trial time

⚠️ **Descriptive fields belong under `[metadata]`.** The structure check no longer counts top-level copies of `author_name`, `category`, `subcategory`, `tags`, `languages`, `difficulty`, `expert_time_estimate_hours`, or the four `*_explanation` / `relevant_experience` fields. **`name`** resolves at top level or under `[metadata]`; **`artifacts`** stays top-level only.

⚠️ Highest-frequency mistake: nesting `artifacts` under `[verifier]` — silently dropped with no error.

✅ Cross-check: every path in `artifacts` needs its parent directory in `tests/Dockerfile` (`RUN mkdir -p /app`). Declare agent output paths here — Harbor collects artifacts; don't stage agent directories yourself.

**Multi-container tasks:** place `environment/docker-compose.yaml` in the task directory — the harness picks it up automatically (no `task.toml` field points at it). Set `[metadata].is_multi_container = true`; omit the field otherwise. Compose build context must stay inside `environment/`.


## C3. Write `environment/Dockerfile`

```dockerfile
FROM <canonical-image>@sha256:<digest>

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        asciinema \
        ca-certificates \
        tmux \
    && rm -rf /var/lib/apt/lists/*
    # apt: NO version pins

RUN pip install --no-cache-dir \
    <package>==<exact-version>           # exact-pinned

COPY app/ /app/                          # narrow COPY, never COPY . .
ENV PYTHONPATH=/app
```

**Non-negotiables:**
- `tmux` + `asciinema` in the final image — missing either → silent failure, every trial
- Every `FROM` (and compose `image:`) digest-pinned with `@sha256:...`
- Final stage uses a **canonical** base image, or a **credible written justification** as a Dockerfile comment
- No `FROM --platform=...` pinning
- pip/npm/cargo/etc. exact-pinned; apt **not** version-pinned
- `environment/` ≤ 100 MiB total, no file > 50 MiB; include `.dockerignore`
- Never `COPY` `solution/` or `tests/` into this image
- Never create/modify `/tests`, `/oracle`, `/logs/verifier/`, `/logs/artifacts/` (Harbor-reserved)
- No `--privileged`, `SYS_ADMIN`/`NET_ADMIN`/`SYS_MODULE`, or docker.sock mounts
- **No GPU** — tasks run within ~2 CPU cores, ~8 GB memory, ~10 GB storage (match `[environment]` limits)
- For multi-container tasks: `docker-compose.yaml` build context must stay inside `environment/` — never `context: ../` or similar to reach outside it
- No AI-scaffolding filenames (`CLAUDE.md`, `skills.md`, `AGENTS.md`, `.cursor/`)
- No bare `nproc`
- If cloning a repo: pin to a specific commit
- If compiling: use multi-stage builds, keep build toolchains out of the final image unless the task requires the agent to compile
- Cleanup (`rm -rf /var/lib/apt/lists/*`) in the **same layer** as the install

## C4. Write `solution/solve.sh`

Harbor mounts `solution/` at `/solution/` and runs `solve.sh` as the oracle agent (confirmed against the official skeleton). Helper scripts (`solve.py`, etc.) are permitted in `solution/` and called from `solve.sh`.

```bash
#!/bin/bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Demonstrate the actual command sequence — diagnose, derive, verify.
# Never: echo "answer" > output.json
```

- Show the **process**, not the answer — derive it
- **Deterministic**: seed any randomness, sort any order-sensitive output, no wall-clock dependence
- Human-written (minimal LLM syntax help only)
- `set -euo pipefail` + fail fast, no swallowed errors unless deliberate
- Document *what was actually wrong and how the fix was derived* in comments — a reviewer reads this to judge whether the task is solvable by reasoning, not guessing
- For interactive tools (vim, etc.), use `solution/solution.yaml` with a `commands:` input sequence instead

✅ Cross-check: the oracle must satisfy **every** requirement in `instruction.md`, not just the tested ones — never a hardcoded value that only passes the specific tests.

⚠️ **Correct, Not Just Passing**: a passing oracle proves the oracle satisfies *your* verifier — it does not prove the verifier is actually correct, or that the reference solution is right. A loose/buggy verifier will happily pass a wrong oracle too. Treat "oracle passes" as necessary, never sufficient — the real check is in D1 below: does the verifier also correctly *reject* a solution you know is wrong?

## C5. Write `tests/Dockerfile` and `tests/test.sh`

**`tests/Dockerfile`:**
```dockerfile
FROM <canonical-image>@sha256:<digest>

# Debian marks the system Python as externally managed — pytest must go in a venv,
# not a bare `pip install`, or the build fails.
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /venv \
    && /venv/bin/pip install --no-cache-dir pytest==<version> pytest-json-ctrf==<version>

# If the verifier will ever execute agent-produced code, drop to an unprivileged
# user for that specific execution so untrusted code can't touch anything else.
RUN useradd --system --uid 12000 --user-group --no-create-home --shell /usr/sbin/nologin sandbox \
    && mkdir -p /work/out && chown sandbox:sandbox /work/out && chmod 700 /work/out

COPY test.sh test_outputs.py /tests/                       # image must own /tests itself — harbor does not upload tests/ at verify time in separate mode
COPY holdout/ /tests/holdout/                              # omit if no held-out fixtures; narrow COPY, never COPY . .
RUN mkdir -p /app                                          # parent dirs for every declared artifact — missing this fails with "Could not find the file ..."
```

**`tests/test.sh`:**
```bash
#!/bin/bash
set -uo pipefail        # NOT set -e — a failing pytest must still reach the reward write

mkdir -p /logs/verifier
chmod 700 /logs/verifier    # keep the reward out of reach of any agent-produced code the verifier runs

/venv/bin/python -m pytest --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py -rA
rc=$?

if [ "$rc" -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi

exit 0    # confirmed by the official skeleton — a literal `exit 0` is fine and expected here;
          # never `exit $?` or `exit $rc` (that fails CI by propagating pytest's code as the script's own)
```

✅ **`tests/test.sh` must never fetch from the network at trial time** — all verifier dependencies belong in `tests/Dockerfile`.

✅ If the verifier re-runs the agent's own program (e.g. against held-out inputs), invoke it through the unprivileged sandbox user rather than as the verifier's own user — e.g. `setpriv --reuid=12000 --regid=12000 --clear-groups python3 <agent-program>`.

## C6. Write `tests/test_outputs.py`

- Every function has a **docstring** explaining what behavior it checks
- Test **behavior** (run the code, check results) — never grep/parse source for patterns
- **Binary reward only** (0/1) — never partial/fractional scoring
- No brittle exact-string matching — check for required content/fields
- No order-dependent tests — each test independent
- Cover edge cases, not just the happy path
- **Verify computation, not stored values** — recompute the expected result independently
- If config-driven: read expected values from the same config at runtime, don't re-declare them as literals
- No latency/performance-threshold assertions
- If grading against oracle performance, thresholds must not sit within ~5% of oracle score

**What's legitimately fine**: running the agent's own binary and grading output, precomputed golden fixtures/hashes, spec-derived invariants, sealed held-out ground truth, perturbation/holdout re-runs.

**The line**: if deleting `solution/` would still let the test compute the expected answer itself, the test is doing the solving.

**Anti-patterns that map to B1 disqualifiers** — check every verifier against these before submit:
- **Proxy checks** — count, first element, field presence without value, or any signal a wrong answer also satisfies
- **Grading an unrebuilt binary** — build from the agent's *actual final* source at grade time, not a stale binary
- **Artifacts the agent controls both sides of** — result and reference/manifest/hash both agent-writable
- **Ground truth from agent-writable paths** — goldens and held-out fixtures belong in the verifier image (`tests/Dockerfile`), never `/app` or other agent paths
- **Symlink/copy staging leaks** — staging must not follow symlinks into protected fixtures or pull paths outside declared `artifacts`
- **Instruction–verifier tolerance drift** — enforce exactly the tolerance stated in `instruction.md`
- **Untested optimization objectives or tie-breaks** — verify the stated objective, not just *a* feasible plan
- **Documented behavior never exercised** — every required command/mode referenced in tests must actually be run; hardcoded stubs must not pass

**One ordering note:** if the verifier loads/imports the agent's own code as part of grading, don't do this *before* your fixed/deterministic assertions run — agent code can have import-time side effects that corrupt state your fixed checks depend on. Run golden/fixed checks first, in isolation, before invoking anything agent-authored.

**Confirmed real pattern (from the official skeleton) — a solid default shape to build from:**
1. **Golden-bytes check** — hash the expected output for the shipped inputs (`sha256sum`), assert the agent's output matches exactly. Catches "close but wrong."
2. **Held-out re-run** — re-run the agent's own program against inputs it has never seen (kept in `tests/holdout/`, not shipped to the agent), assert it reproduces the *pre-computed* expected hash for those. This is the actual anti-cheat axis: a hand-written or fixture-pinned report can pass step 1 but cannot pass this one.
3. **Determinism check** — run the agent's program twice on the same input, assert byte-identical output both times.

If the verifier executes the agent's own program (steps 2–3), run it as an **unprivileged sandbox user** (see C5), never as the verifier's own user — it's executing untrusted code.

✅ Cross-check: identical test logic for oracle and agent runs — zero conditional branching on execution mode.
✅ Cross-check: `$TEST_DIR`-style variables need `${TEST_DIR:-/tests}` defaults; `$HOME`/`$PWD` don't.

## C7. Write the rubric (in the platform UI, after CI passes)

- Every line: starts with **"Agent"**, ends with **`, ±N`**
- Only **±1, 2, 3, 5** — never 4
- Positive scores need an **explicit `+`**
- **Positively phrased**, even when scoring negative
- At least **one negative** criterion
- Severity-to-score: Critical → ±5; Major → ±3; Minor → ±1–2
- Total possible score: **10–40 points**
- Never reference `tests/`, pytest results, `task.toml`, or `instruction.md`'s existence
- Never mention oracle/NOP runs

---

# PHASE D — VALIDATE

## D1. Local validation loop (before spending API budget)

```bash
stb harbor tasks start-env -p <task-folder> -i    # verify solve.sh steps manually
stb harbor run -a oracle -p <task-folder>          # must PASS
stb harbor check <task-folder>                     # CI + LLMaJ checks — fix errors before warnings
```

If the oracle fails: check your solution first, then your tests, then the task design — in that order.

**Negative test — mandatory, not optional.** A verifier that only ever sees a passing oracle proves nothing about whether it can catch a *wrong* solution — it may be too loose (see "Correct, Not Just Passing," C4). Before moving on:
1. Write or hand-craft at least one deliberately wrong solution — plausible-looking but incorrect on some axis your task cares about (wrong edge case, subtly wrong computation, missing one of several interacting constraints).
2. Run it against your verifier the same way the oracle is run.
3. Confirm it **fails**. If it passes, the verifier is too loose — go back to C6 and tighten it (check for the three anti-patterns: proxy checks, unrebuilt binaries, self-referential artifacts) before doing anything else.
4. Repeat for each independent correctness axis the task claims to grade — a verifier can correctly reject a wrong answer on axis A while still being blind to axis B.

## D2. Measure real difficulty

```bash
stb harbor run -m @openai/gpt-5.6 -p <task-folder> -k 4
stb harbor run -m @anthropic/claude-opus-5 -p <task-folder> -k 4
```

- Keep the `@provider/` prefix exactly; `-k 4` means **4 runs per model** (8 total across both models)
- **Accuracy** = mean pass@1 averaged across **both** models together (not per-model best/worst — this replaced Terminus 2's best-or-worst-model metric)
- Record each model's pass rate and the combined accuracy; set `difficulty` in `task.toml` to the matching tier:

| Tier | Combined accuracy |
|---|---|
| Frontier | < 20% |
| Advanced | 20% – < 50% |
| Core | 50% – < 80% |
| Base | 80% – < 100% |

- **Triviality gate**: 100% pass rate means no agent ever fails → no signal; the task cannot proceed. At least 1 of the 8 runs must fail.
- The platform re-runs agent evaluation (4 trials per model) **after reviewer acceptance**; the tier can shift — treat your pre-submission measurement as provisional until final acceptance
- Per failure: **good reason** (reasoning error, missed edge case, domain gap) vs. **bad reason** (unclear instruction, environment defect, over-strict test)? Only good-reason failures count toward difficulty
- **Failure-pattern check**: if failing runs keep missing the **same** test(s), the check or the instructions are likely the problem — fix that check or state the requirement in `instruction.md`. If they miss **different** tests each time, the difficulty is genuine. Don't leave difficulty rated higher just because near-complete runs count as failures.
- "Solvable" ≠ "passing a run" — a 0% pass@1 task can still be valid if agents partially succeed differently across runs
- Too easy → push on the six properties, don't add hints
- Too hard for the *right* reasons → usually nothing to fix; Frontier is wanted. Only intervene for ambiguity/non-determinism/environment bugs/undiscoverable info

**Read the trial analysis, not just the pass rate.** Six criteria, each PASS/FAIL/NOT_APPLICABLE (a flag = FAIL). Reviewers see the same output, so resolve these before submitting:

*Fatal — the task must change:*
- `task_specification` — tests require something `instruction.md` never states. Fix: specify it, or relax the test.
- `reward_hacking` — the agent reached the reward illegitimately (editing tests, writing the reward file directly, reading `solution/`). Fix: close the hole.

*Needs investigation — often means you're measuring the wrong thing:*
- `difficulty_crux` — the agent failed for a reason unrelated to `difficulty_explanation`. Either the task has unintended difficulty, or the explanation is wrong — fix whichever is off.
- `near_miss` — read across the failure pattern for the whole run set, not any single trial: are agents consistently producing substantively working solutions that narrowly miss a quantitative threshold (e.g. 95% vs. required 98%) run after run? The threshold is producing the difficulty, not the problem — loosen it.
- `refusals` — agent aborted on a content/safety policy instead of attempting the task. A refused trial measures nothing — review the framing.
- `low_timeout` — agent was still making real progress when the timeout hit. Raise `[agent].timeout_sec` — difficulty should come from the problem, not the clock.

Set `difficulty` in `task.toml` to match the **measured** tier.

## D3. Self-review checklist

Before the structural checklist, run your own test file through the five reviewer-side test-quality flags — think like the person grading you, not just the person who wrote the test:

- `req-gap` — does `instruction.md` require something with no test asserting it?
- `weak-assertion` — does a test exist but is too loose to actually catch a wrong solution?
- `phantom-spec` — does a test enforce behavior never described in `instruction.md`?
- `flaky-execution` — could a genuinely correct solution fail due to timing, non-determinism, or infra flakiness?
- `vacuous-test` — could this test pass no matter what the output is (empty loops, always-true checks)?

Also: more tests is not automatically better coverage — a long `test_outputs.py` (20+ tests for a task that isn't genuinely that broad) is itself a flag, since each additional test is another opportunity for a false failure. Prefer fewer, sharper, harder-to-satisfy-by-accident tests over a long checklist of shallow ones.

Then the structural checklist:

**Task design**
- [ ] Goal clear; requirements inferable from materials provided; fully specified and self-contained (testable)
- [ ] Standalone — no interactive prompts; all parameters via files, flags, or env vars
- [ ] Not solvable in one command or straight-line burst — ask: "could an agent finish in one shot without reacting?" (~5 steps is a heuristic, not counted)
- [ ] Novel — new setup/definition/data; embedding similarity catches reskins
- [ ] No canary strings in any component (instruction, environment, solution, tests, metadata)
- [ ] Instructions human-written — screened for AI-generated text

**Required files & configuration**
- [ ] Descriptive fields under `[metadata]` only — no top-level duplicates; no top-level `network_mode` or legacy `allow_internet`
- [ ] `[agent].timeout_sec` ≥ 1800, ≤ 18000 — set to actual need (60–90 min typical; under ~30 min usually too shallow)
- [ ] `[verifier].timeout_sec` and `[environment].build_timeout_sec` set
- [ ] All three `network_mode` values set explicitly — no `"allowlist"` / `allowed_hosts`
- [ ] 3–6 tags; `languages` from approved list (multi-language preferred); `expert_time_estimate_hours` set
- [ ] No GPU; oracle runs within ~2 CPU / ~8 GB / ~10 GB

**Verifier**
- [ ] `artifacts` is top-level, not nested
- [ ] `[verifier].environment_mode = "separate"`
- [ ] Goldens and held-out fixtures baked into the verifier image (`tests/Dockerfile`), not read from agent-writable paths
- [ ] Every artifact's parent dir exists in `tests/Dockerfile`
- [ ] Absolute paths only, everywhere
- [ ] Every tested file is named in `instruction.md`; every instruction requirement has a test
- [ ] No hints/step-by-step anywhere
- [ ] `tmux` + `asciinema` installed
- [ ] All images digest-pinned + canonical (or justified)
- [ ] pip/npm exact-pinned; apt not pinned
- [ ] `environment/` ≤100MiB, no file >50MiB
- [ ] No `solution/`/`tests/` copied into the agent image
- [ ] No reserved-path creation, no privileged ops
- [ ] Oracle passes, deterministic, matches `network_mode`
- [ ] Test logic identical for oracle and agent
- [ ] Binary reward only; reward always written, even on failure
- [ ] `tests/test.sh` never fetches from network at trial time
- [ ] No latency tests; no near-oracle performance thresholds
- [ ] **(High)** Verifier confirmed to reject a deliberately wrong solution (D1) — every documented command/mode is actually exercised in tests, not just referenced
- [ ] **(Medium)** If `instruction.md` states a tolerance/threshold, the verifier enforces that exact value — no drift
- [ ] **(Medium)** If the task involves optimization, the verifier checks the objective is actually optimized (and any stated tie-break rule is honored) — not just that *a* valid solution exists
- [ ] Rubric: format, sign, phrasing, no self-reference, 10–40 total, ≥1 negative
- [ ] Novelty checked
- [ ] `stb harbor check` clean
- [ ] Measured difficulty tier matches declared `difficulty`; failures reflect genuine difficulty (not unclear instructions, environment defects, or flaky tests); failure pattern checked (same test vs. different tests)

**Self-check before submit**
- [ ] Would a first-time reader understand what is being asked?
- [ ] Can the agent obtain everything it needs from the environment?
- [ ] Could a plausible-but-wrong solution pass my tests?
- [ ] Do my tests check semantics rather than appearance?
- [ ] Is everything deterministic?

---

# PHASE E — PACKAGE

Only after every item in D3's self-review checklist is confirmed and D2's measured difficulty is recorded in `task.toml`, materialize and zip the final task folder.

## E1. Assemble the full directory

Name the folder after the selected topic (kebab-case, matches `name` in `task.toml`):

```
your-task-name/
├── task.toml                    # Metadata and manifest
├── instruction.md               # What the agent is asked to do
├── environment/
│   ├── Dockerfile               # Agent-facing environment
│   │   └── (or docker-compose.yaml for multi-container)
│   └── data/                    # Bundled inputs (sample data, configs)
├── solution/
│   └── solve.sh                 # Oracle solution
├── tests/
│   ├── Dockerfile               # Verifier environment (separate container)
│   ├── test.sh                  # Verifier entrypoint
│   └── test_outputs.py          # Python pytest assertions
├── rubrics.txt                  # Added by Snorkel at packaging — see note below
└── README.md                    # Added by Snorkel at packaging — see note below
```

⚠️ **Packaging note on `rubrics.txt` and `README.md`:** you don't author either file. `rubrics.txt` comes from the platform rubric UI (Phase C7). `README.md` is auto-assembled by Snorkel from your `[metadata]` explanation fields plus category/subcategory — put the effort into those fields; there's no second write-up to do.

- The **local preview zip** may include placeholder/draft versions of both, clearly marked as drafts.
- The **actual submission ZIP** must contain only `task.toml`, `instruction.md`, `environment/`, `solution/`, `tests/` — select those files individually, not the enclosing folder, and do not include `rubrics.txt` or `README.md`.

## E2. Zip

- Zip filename: `your-task-name.zip`, containing the `your-task-name/` folder as shown above (local preview) — or, when preparing the actual platform submission, zip the individual required files/folders directly with no enclosing folder and no `rubrics.txt`/`README.md`.
- Confirm the zip is not the folder itself nested one level too deep (a common structural mistake called out earlier in D3/Common Issues).

---

# PHASE F — SUBMIT

1. Upload the platform submission ZIP from Phase E (individual required files/folders only — not the enclosing folder, no `rubrics.txt`/`README.md`) on Terminus-3-Prod
2. Check the **rubric checkbox**, leave **"Send to Reviewer" unchecked**, submit for CI
3. Edit the generated rubric for accuracy/completeness
4. **Uncheck the rubric checkbox** before your next submission
5. Once CI + rubric are clean, check **"Send to Reviewer"**, submit
6. Wait 1–7 business days for peer review

---

## Final output

End the whole exercise by listing:
- The category/subcategory selected (A1) and why it's load-bearing
- Which of the six properties (B1) the finished task satisfies, with one sentence each
- The measured difficulty tier (D2) vs. the original target (A2)
- Any self-review items (D3) still open, if submitting before full validation
- The path to the packaged zip (E2) and a reminder of which files it should/shouldn't contain for actual platform submission
