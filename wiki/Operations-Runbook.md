# Operations Runbook

**The day, the decisions, the risks, the rules — one page to have open on a laptop from 9:00 to 19:15.** Sources: [docs/00_hackathon_strategy.md](../docs/00_hackathon_strategy.md), [docs/01_agent_team.md](../docs/01_agent_team.md), [docs/TEAM_HANDOVER.md](../docs/TEAM_HANDOVER.md).

## The day, hour by hour

| time | who | what |
|---|---|---|
| 9:00 | all | in, network, hub + sim up on the big machine, roster check (checklist in [Agent Team](Agent-Team.md)) |
| 10:00 | lead | read brief; map onto the five parts; freeze scenario choice by 10:20 |
| 10:30–12:00 | Codex A + dev / Codex B | wire the brief's task as an armsmith_web scenario; teleport demo collecting / eval harness: run-N-episodes → failure taxonomy |
| 12:00–14:00 | all | loop 1: collect 50–100 eps → train ACT (tiny) → eval → record delta |
| 14:00–16:30 | all | failure-driven loop: stalls → S1/S2 recover → labels → Laya retrain (Kaggle T4 if net allows, else local) → escalation rate falls |
| 16:30–17:30 | stretch | MCAP export + "agent investigates the fleet log" screen; hand teleop if hardware present |
| 17:30–18:30 | lead + Codex C | freeze code; nines before/after table; 3-min backup demo video; submit |
| 19:15 | lead | pitch: loop diagram → live demo → the falling curve → what breaks at scale |

## Morning checklist

The 7-step checklist lives in [Agent Team](Agent-Team.md) (venvs, hub, sim, Ollama pre-warm, Laya serve, tests green, metrics fresh — collect baseline data before the brief arrives).

## Decision rules

- **Bad Wi-Fi** → nothing changes: no CDN in the web sim, CPU MuJoCo, local models — planned for.
- **RTX boxes / credits appear** → move ACT training there (commands in docs 04/05); keep the laptop as the robot controller.
- **Real hardware available** (ours or theirs) → run the same bus against it; the protocol is hardware-neutral. LeRobot's SO-101 driver/calibration/record tooling is documented in doc 04.

## Risk register

| risk | mitigation |
|---|---|
| Brief demands an exotic platform | the bus protocol absorbs new sims; Codex's whole day-job |
| WebGL blocked on venue machines | fake_sim + MuJoCo path demos the loop identically, headless |
| Laya fails the GUT gate | show untrained-vs-trained curve anyway; honesty is on-thesis |
| S2 too slow under load | cap tokens (450), scripted fallback recovery, pre-warm at 9:00, streaming first-action |
| Machine memory (124 GB shared) | close Ollama extras; ≤2 models resident; `free -g` checks |
| Dataset too small for ACT | fine: the loop, not the policy, is the entry; report the curve honestly |

## Pack list

Laptops + chargers; the arm + PSU + cables (if BYO); webcam; phone hotspot; USB stick with the repo + vendored deps + a rendered demo video; SSH keys; powerboard; printed one-pager of the pitch.

## Rules of engagement (the six hard ones)

1. Never send joint/EE commands outside the workspace box (`control/robot_ops.schema.json`: x 0.05–0.30, y ±0.18, z 0.02–0.25 m) — use `ee`, not raw joints.
2. Never bypass the safety shield — the S2 model is abliterated; assume zero self-restraint.
3. Don't change the frozen criteria in `robot_ops.schema.json`; new behaviour means new skills + shield clamps, or a new domain version.
4. Reset between episodes with a `seed`; announce takeovers on `ctl.recovery`.
5. Don't write into the Laya repo; keep `runs/bus/*.jsonl` intact — it IS the dataset.
6. Small, boring, working code. One process per concern. Everything survives the hub being down.

## Use + feasibility

**FOR**: printing/sharing before the day; the single page to consult mid-crisis. **Feasibility**: every item on it has already been run end-to-end at least once (see [Testing and Benchmarks](Testing-and-Benchmarks.md)); the main residual risks are venue-side (Wi-Fi, power, WebGL), and each has a rehearsed fallback.

## See also

- [The Event](The-Event.md) — the clock behind this plan
- [FAQ](FAQ.md) — quick answers under pressure
