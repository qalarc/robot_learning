# The Learning Loop

**The stall-recovery loop in detail: five escalation levels, a frozen state template, soft labels that let System 2 teach System 1, and streaming so the arm moves before the plan finishes.** Source: [docs/08_stall_learning_loop.md](../docs/08_stall_learning_loop.md).

## The L0–L4 ladder (measured latencies)

| level | who | latency | notes |
|---|---|---|---|
| L0 | deterministic stall detector (in-sim + controller) | ~0, 30 Hz | fires on no >2 mm best-progress improvement for 90 obs (3 s), or the sim's own `stall.stalled` |
| L1 | Laya S1 typed identification | **1.35 s** warm (27 s cold) | renders the frozen state template, asks the `robot-ops` domain |
| L2 | gate | instant | escalate iff `escalate` or `stalled` p ≥ 0.5; **fail-open** if Laya is down |
| L3 | alexei S2 + shield | **15–30 s** blocking (uncontended decode ≈ 5.5 s for a 255-token plan) | dossier in, minified JSON plan out, clamped in code |
| L4 | human / teleop | — | `request_teleop` after 3 failed recoveries per episode |

## The state template

`control/laya_client.py` renders each `sim.obs` into the frozen template: scenario, stage, step, t, stall_steps, progress_delta_mm, ee_pos, target, dist_to_goal_mm, gripper, contact, grasp_state, prior_recoveries, ep_success_rate_20, vision. Every field is a one-word-to-one-number fact — cheap tokens, byte-identical shape across all rows (the GUT rule; see [System One](System-One-Laya.md)).

## The labelling contract (who teaches whom)

Within a 120-obs evaluation window after recovery, the outcome is one of resumed / done / timeout / episode_fail, and a System One row is appended to `data/robot-ops.jsonl` with **soft labels**: `progress` ← outcome truth; `failure_mode` ← 0.7·S2 root_cause + 0.3·S1 spread (**System 2 teaches System 1**); `recoverable` ← 0.9/0.1; `escalate` ← 0.9/0.3. Retrain offline via the GUT trainer (gate: agreement ≥ 0.85, ECE ≤ 0.10), register, and serve hot-reloads — next stall of a learned class never wakes GLM.

## Streaming first-action

Waiting out the whole plan wastes seconds, so `GLMS2.ask_stream` emits each **complete** plan step as it closes; each step passes the same `validate_step` shield as the blocking path (the two cannot drift), and the controller issues it immediately. Measured: **time-to-first-action 2.05 s mean** (1.79–2.22, warm) vs 4.50 s blocking total; acceptance runs logged `ttfa=2.05–3.49s total=14.5–22.7s`. The evaluation window arms at the first issued command, so obs queued during decode can't burn it; a dead stream falls back to blocking `ask()`.

## Metrics

`runs/metrics.json`: episodes, successes, stalls, escalations, escalations_helped, escalation_success_rate, mean_time_to_recover_s, rows, ep_success_rate_20. The money chart: escalation rate vs time, plus failure rate before/after retrain → the nines table (see [The Event](The-Event.md)).

## Use + feasibility, and honest limitations

**FOR**: this loop IS the entry — run it continuously from 10:30 and let the curve fall. **Feasibility**: works headless (acceptance: 16 eps → 5 stalls → 5 Laya verdicts → 5 alexei-class plans → labelled rows, PASS). Known limits, stated on stage: Laya starts untrained on `robot-ops` (base-English fallback = uncalibrated — that IS the before-curve); S2 at 15–30 s is a pause, not a reflex (streaming + token cap 450 + 9:00 pre-warm mitigate); two Ollama models resident cost ~40–60 GB on the shared 124 GB box; monocular mocap lacks absolute scale (relative motion + clamp only).

## See also

- [System One Laya](System-One-Laya.md) and [System Two alexei](System-Two-alexei.md) — the two brains
- [docs/08_stall_learning_loop.md](../docs/08_stall_learning_loop.md) — the full measured write-up
- [Training](Training.md) — the second (policy) loop
