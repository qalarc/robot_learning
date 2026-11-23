# 08 — The stall-recovery learning loop (S1/S2)

The user's idea, now measured and built: **Laya does the identification every time; a
local GLM 4.7 "alexei" (abliterated) does the reasoning only on stall.**

## Why this split (measured 2026-11-24, this machine)

| | Laya (System 1) | GLM-4.7-abl (System 2) |
|---|---|---|
| latency | **1.35 s** warm (27 s cold load) | **15–30 s** per plan (~14 tok/s decode, ~0.1–1.4 s prompt eval) |
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
