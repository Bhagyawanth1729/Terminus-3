# Terminus 3 — Difficulty Mismatch Diagnostic Prompt

Use this after you've already run the difficulty measurement:
```bash
stb harbor run -a oracle -p <task-folder>
stb harbor run -m @openai/gpt-5.6 -p <task-folder> -k 4
stb harbor run -m @anthropic/claude-opus-5 -p <task-folder> -k 4
```
(4 runs per model via `-k 4`, 8 total — average pass@1 across both models determines the tier. The platform re-runs agent evaluation after reviewer acceptance; the tier can shift.)

...and the result doesn't match what you wanted. Identify which scenario you're in below, and only follow that path. Do not skip the diagnostic step to jump straight to a fix — the same symptom (a low pass rate, a failing test) can come from a real difficulty or from a bug, and the fix is different in each case.

**Before anything else, always check:** does the oracle pass, every time, with `network_mode` behaving as declared? If the oracle doesn't pass cleanly, none of the scenarios below apply yet — fix the oracle/environment first, then re-measure from zero.

**Also always check the trial analysis, not just the pass rate.** Six criteria come back with every measurement — `task_specification` and `reward_hacking` are fatal (the task must change); `difficulty_crux`, `near_miss`, `refusals`, and `low_timeout` mean you're likely measuring the wrong thing and need to investigate before trusting the number. A flagged `near_miss` in particular often explains a "hard but not solvable" result better than any of the scenarios below — check it first if a test narrowly and consistently misses a numeric threshold.

**Failure-pattern check:** if failing runs keep missing the **same** test(s), the check or instructions are likely wrong — fix before trusting the pass rate. If they miss **different** tests each time, the difficulty is more likely genuine.

---

## Scenario 1 — Task is hard, but one or more specific tests never pass

**Diagnose first:**
1. Confirm the oracle passes 100% of the time. If not, this is a bug, not difficulty — stop here and fix the oracle/test/environment.
2. If the oracle is clean, check the specific failing test across all 8 agent runs (4 per model). Does it pass even once, anywhere?

**If it passes occasionally (even 1-in-8):** this may be entirely legitimate. Remember: *solvable ≠ passing a run*. A task can have zero full passes across all 8 runs and still be valid, as long as each individual test passes at least once somewhere across those runs. Don't "fix" a task just because it's hard — check Scenario-3-style reasoning below before touching anything.

**If it never passes, not once, across all 8 runs:** treat this as a suspected test bug until proven otherwise. Check, in order:
- **`near_miss` (check this first)** — read across all 8 runs, not one: are agents *consistently* producing substantively working solutions that narrowly miss a quantitative threshold (e.g. 95% against a required 98%), run after run? If so, your threshold is manufacturing the difficulty, not the problem — loosen it. A task that looks Frontier only because of a tight numeric cutoff is not a Frontier task. (A single near-miss run is just noise; the flag means the *pattern* holds across the run set.)
- **`phantom-spec`** — does this test check something not actually stated or clearly implied in `instruction.md`? If yes, either remove/loosen the test, or add the requirement to `instruction.md` (as a *what*, not a *how*) so it's fair.
- **`flaky-execution`** — could a genuinely correct approach fail here due to timing, non-determinism, or infrastructure, independent of whether the agent understood the task? If yes, fix the test's determinism, not the difficulty.
- **Hidden requirement vs. under-specification** — is the missing piece *discoverable* by the agent (in a config file, spec document, or domain convention), or is it information the agent has no possible way to obtain? Only the first is legitimate; the second is a broken task and must be fixed by exposing the information somewhere discoverable.
- **`weak-assertion` in reverse** — occasionally a test that "never passes" is actually testing the wrong artifact/path entirely (e.g., `artifacts` nested under `[verifier]` and silently dropped, or a parent directory missing in `tests/Dockerfile` so the file never lands). Rule out a plumbing bug before assuming it's a hard requirement.

**Fix and re-verify:**
- Make exactly one change at a time (loosen/fix the test, or expose the missing discoverable info)
- Re-run the full oracle + 8-run measurement from scratch — don't assume a fix worked without re-measuring
- If the test was legitimately fine and the agent is just genuinely failing it for real reasoning reasons, leave it as-is — a hard test that occasionally passes is a feature, not a defect

---

## Scenario 2 — Task came out Base (too easy), you wanted Advanced/Core or higher

**Do not:**
- Add hints, worked examples, or step-by-step guidance to `instruction.md` — this violates the no-hints rule and would also get flagged by `expose_answers`
- Pile on more independent, unrelated requirements — this is length, not difficulty, and disqualifies the task

**Do, in order of leverage (try one, re-measure, then move to the next only if needed):**

1. **Increase inference load.** Find a requirement currently stated directly and replace it with domain evidence the agent must interpret — a spec file it has to read, a dataset it has to analyze, a convention it has to infer from examples — rather than being told outright.
2. **Add a second correctness axis that interacts with the first.** Don't just add an unrelated new check — make an axis that changes what "correct" means for the axis you already have (e.g., a performance constraint that changes which functionally-correct solutions are actually acceptable; a safety constraint that changes which state-consistent solutions are actually acceptable).
3. **Demand a native, structurally valid artifact** instead of one that merely looks right (e.g., require an editable/parametric result instead of a static rendered one; require passing a semantic check instead of a superficial format check).
4. **Add hidden/metamorphic variations to the verifier** — held-out inputs or perturbations that check the agent generalized its understanding, not just satisfied the one example it happened to see.

**After each change:**
```bash
stb harbor run -a oracle -p <task-folder>     # must still pass
stb harbor run -m @openai/gpt-5.6 -p <task-folder> -k 4
stb harbor run -m @anthropic/claude-opus-5 -p <task-folder> -k 4
```
Re-measure the full mean pass@1 across both models. If it's still Base, apply the next lever down the list rather than stacking unrelated changes at once — you want to know which lever actually moved the needle.

---

## Scenario 3 — Task came out Core (medium), you wanted Advanced/Frontier (hard but fair)

Use the same four levers as Scenario 2, pushed further — but at this tier the risk of accidentally breaking fairness while chasing difficulty is much higher, so add a mandatory classification step after every change.

**After any change, before accepting the new pass rate, classify every new failure:**

| Failure reason | Legitimate? | What to do |
|---|---|---|
| Reasoning error | ✅ Yes | Keep the change |
| Missed a genuinely discoverable hidden requirement | ✅ Yes | Keep the change |
| Lacked domain knowledge needed to interpret the evidence | ✅ Yes | Keep the change |
| New ambiguity introduced by your change | ❌ No | Revert or fix that specific change |
| New non-determinism introduced | ❌ No | Fix determinism, re-measure |
| Environment/verifier defect introduced by the change | ❌ No | Fix the defect, re-measure |
| Agent found an actual shortcut around your new constraint | ❌ No (task integrity issue) | Close the shortcut architecturally (read-only files, banned imports, required APIs, pinned commits) — don't just hope it won't happen again |

**The trap to watch for specifically:** a lower pass rate always *looks* like "we hit Frontier" — but only some of the drop is real difficulty. Read the actual terminal recordings / failure transcripts for a sample of the new failures, don't just trust the number. If the drop came from constraints genuinely interacting more tightly, it's valid. If it came from your added spec file being ambiguous, or your new hidden variation being untestable by the agent in principle, it's not difficulty — it's a new bug wearing difficulty's clothes.

**Once you're satisfied the drop is legitimate:**
- Update `difficulty` in `task.toml` to match the newly measured tier
- Update `difficulty_explanation` to reflect the actual crux (should now name the interacting axes, not just "task requires N steps")
- Re-run the full self-review checklist — a design change this late can quietly reintroduce an issue caught earlier (e.g., a new spec file that isn't realistic-looking, a new test that isn't behavior-based)

---

## Universal rule across all three scenarios

Never trust a difficulty number without re-running the full oracle pass + both-model measurement (`-k 4` per model, 8 total) after *any* change to `instruction.md`, `tests/`, `solution/`, or `environment`. Never accept or reject a result based on the pass rate alone — always read a sample of the actual failure transcripts, check whether failures cluster on the same test(s) or spread across different ones, and review all six trial-analysis criteria (`task_specification`, `reward_hacking`, `difficulty_crux`, `near_miss`, `refusals`, `low_timeout`) before deciding whether the task is done, needs to get harder, or needs to get fairer.
