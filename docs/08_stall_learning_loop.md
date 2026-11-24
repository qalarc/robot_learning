# 08 — The stall-recovery learning loop (S1/S2)

The user's idea, now measured and built: **Laya does the identification every time; a
local GLM 4.7 "alexei" (abliterated) does the reasoning only on stall.**

## Why this split (measured 2026-11-24, this machine)

| | Laya (System 1) | GLM-4.7-abl (System 2) |
|---|---|---|
| latency | **1.35 s** warm (27 s cold load) | **~5.5 s decode** uncontended (~46 tok/s, 255-token plan); 12–38 s under 3-model GTT contention; ~50–70 s cold load |
| cost | ~free, local, CPU | 18 GB resident, local |
| output | typed probabilities + calibrated confidence | free-form JSON diagnosis + plan |
| strengths | fast, calibrated, auditable | diagnoses novel failures, plans multi-step recoveries |
| weaknesses | only as good as its training data | slow; **abliterated → zero self-restraint** |
| cadence | every stall + heartbeat | only gated stalls |

## The loop, precisely

1. **L0 — detect (30 Hz, free, deterministic).** In-sim stall detector + controller's
   own: no >2 mm improvement in best-progress for 90 obs (3 s), or sim's
   `stall.stalled`.
2. **L1 — identify (~1.35 s).** `control/laya_client.py` renders the frozen state
   template (scenario/stage/stall_steps/ee/target/dist/gripper/grasp/history) and asks
   the `robot-ops` domain: `progress` (advancing|stalled|regressing|done|unsafe),
   `failure_mode` (grip_slip|unreachable_or_ik_residual|collision|bad_perception|
   controller_error|none), `recoverable` (P), `escalate` (P).
3. **L2 — gate (instant).** Escalate iff `escalate` or `stalled` p ≥ 0.5. **Fail-open**:
   if Laya is down we still escalate (a stuck robot is worse than an extra S2 call).
4. **L3 — reason (15–30 s).** `control/glm_s2.py` builds a compact dossier (state,
   S1's typed verdict, history, recent events, the skill vocabulary) and asks the local
   model for minified JSON: diagnosis, root_cause, ≤4-step plan, abort_if, confidence.
5. **Shield (instant, non-negotiable).** `validate_plan` whitelists skills
   (`SKILL_SIGNATURES`), clamps every arg to the workspace box / numeric bounds, drops
   unknowns, caps length. **The model never emits joint angles; bounds live in code.**
   Truncated JSON is salvaged (`loads_lenient`); empty plans fall back to a scripted
   bounded recovery. Measured live: shield silently cleaned args like
   `approach_from(from=side, target=-1.0)` — it earns its keep.
6. **Execute.** Skills → `sim.cmd` envelopes, paced 0.4 s apart, announced on
   `ctl.recovery` (source: glm-s2|scripted|human).
7. **Label (the learning).** Within a 120-obs window: resumed/done/timeout/episode_fail.
   A System One row is appended to `data/robot-ops.jsonl` (soft labels):
   `progress` ← outcome truth; `failure_mode` ← 0.7·S2 root_cause + 0.3·S1 spread
   (**System 2 teaches System 1**); `recoverable` ← 0.9/0.1; `escalate` ← 0.9/0.3.
8. **Retrain (offline bursts).** Push rows through the GUT trainer (train → gate:
   agreement ≥0.85, ECE ≤0.10 → register; serve.py hot-reloads). Next stall of a
   learned class: Laya catches it, no GLM. **Escalation rate falls over the day.**

## The second loop (policy)

Same bus log: episodes → `training/to_lerobot_dataset.py` → ACT/SmolVLA → policy
actions replayed via `sim.cmd play`. Failure episodes become corrective demos
(RECAP-flavoured: demos → corrections → improve). Both loops drink from
`runs/bus/*.jsonl`; both write into `runs/metrics.json`.

## Metrics (the pitch numbers)

`runs/metrics.json`: episodes, successes, stalls, escalations, escalations_helped,
escalation_success_rate, mean_time_to_recover_s, rows, ep_success_rate_20. The money
chart: escalation rate vs time + failure rate before/after policy retrain → the
"march of nines" table (e.g. 3 failures/10 → 1/10 = +1 nine).

## Honest limitations

- Laya starts untrained on `robot-ops` (base English fallback): early verdicts are
  uncalibrated. That *is* the before-curve; the day shows it bending.
- S2 at 15–30 s means recoveries are pauses, not reflexes — fine for the demo cadence,
  wrong for real-time control. Cap tokens; pre-warm the model at 9:00.
- Two Ollama models resident = ~40–60 GB RAM on a shared 124 GB box; keep ≤2, watch
  swap (`free -g`).
- Abliterated model + safety: acceptable because the action space is symbolic and
  fully clamped — but never relax the shield to "save time" on the day.
- Monocular mocap (vision teleop) lacks absolute scale: use relative motion + clamp.

### Streaming: acting on the first step (added 2026-11-24, T2)

Waiting out the whole S2 plan before the robot moves is wasted seconds: step 0 is
fully written roughly a third of the way through the decode. So
`GLMS2.ask_stream(dossier, on_step)` streams `/api/generate` (same request as
`ask()`: json format, temperature 0.3, `num_predict` from schema, system prompt,
keep_alive 2h) and after every NDJSON chunk extracts **complete** top-level
objects from the accumulating `"plan":[` array (`iter_plan_objects` — string-aware
brace matching; a step is yielded only once its closing `}` is seen, never a
partial). Each new object is shielded through `validate_step` — the same helper
`validate_plan` now uses internally, so the streaming and blocking paths cannot
drift apart — then `on_step(validated, index, raw)` fires and the controller
issues that step's `sim.cmd`s immediately, respecting `--dry-run` and the
`--cooldown` pacing.

Bookkeeping moved with the commands: `ctl.stall` still publishes before reasoning;
the evaluation window (`_ignore_obs_before`, `pending`, `eval_until`) arms at the
**first issued command**, not before, so obs queued while the model was still
writing can't burn the window; `ctl.recovery` publishes on stream completion with
the accumulated plan. If the stream dies before any step lands, `ask_stream`
falls back to blocking `ask()` transparently (`fallback: true`); with Ollama down
entirely, both fail to the scripted recovery as before. The result dict is the
`ask()` shape plus `ttfa_s` (request → first `on_step`), `load_s` (Ollama
`load_duration`), and `fallback`/`streamed` flags.

Measured on the demo dossier (`control/glm_s2.py --probe` state), resident
`glm-4.7-flash-abl:alexei-v3`, 5 interleaved runs per mode, 2026-11-24:

| | blocking `ask()` | streaming `ask_stream()` |
|---|---|---|
| time to FIRST action (ttfa) | — (nothing until the whole plan lands) | **2.05 s mean (1.79–2.22, n=3 warm)** |
| total plan time | 4.50 s mean (4.14–4.87, n=2 warm) | 5.27 s mean (4.99–5.74, n=3 warm) |
| tokens / rate | ~198 @ ~45 tok/s | ~234 @ ~45 tok/s |

- Warm = `load_duration == 0`. The bench overlapped another session's Ollama chat
  traffic, which kept evicting/reloading the 18 GB weights: 5 of 10 rows were cold
  (17–82 s of pure model load; e.g. one stream row ran `ttfa=84.9s` of which
  `load=82.2s`). Cold rows are excluded above — under contention the honest
  per-request metrics are Ollama's `eval_duration`/`eval_count` (~45 tok/s,
  matching the uncontended reference; the old 12–38 s `ask()` figures were
  3-model GTT contention at ~14 tok/s).
- Acceptance (`MODEL=glm-4.7-flash-abl:alexei-v3 bash scripts/acceptance.sh` →
  **ACCEPTANCE PASS**): every escalation logged `recovery via glm-s2 (stream)
  ttfa=2.05–3.49s total=14.5–22.7s (3–4 steps)` — the first recovery command now
  goes out ~7–20 s earlier than the blocking behaviour, even with reload churn
  inflating totals mid-run.
- First-step equality streamed vs blocking: matched in 2/5 paired runs. Not a
  streaming artifact — blocking `ask()` doesn't match *itself* across runs either
  (temperature 0.3 sampling flips between `backoff(z)` and `move_ee` hover as the
  opening step); both paths draw the same distribution.
- ttfa now scales with the plan prefix, not the plan: it covers diagnosis +
  root_cause + step 0 (~80 tokens) at whatever tok/s the iGPU is managing that
  minute; the remaining steps trail in and are issued as they close.

