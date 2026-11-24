# Home

robot_learning is our entry for the **Alloy x OpenAI Physical AI Hackathon** (Sat 5 Dec 2026, Sydney CBD): a live failure-recovery learning loop for a SO-101-class desktop arm. The sim runs; a deterministic detector catches stalls; a tiny calibrated classifier (**Laya**, System 1) identifies them; a local reasoning model (**alexei**, System 2) plans a bounded, shield-clamped recovery; and every recovery is labelled so System 1 learns to catch the next stall of that class *without* waking System 2. The escalation rate falls over the day — that falling curve is the demo.

Everything talks over one **Robot Bus** (a small WebSocket relay whose log *is* the training dataset), the browser sim is a port of our Unity ARMSMITH project, and a parallel loop trains policies (PPO in MuJoCo, ACT on recorded episodes) so the base controller itself fails less. The brief is secret until 10:00 on the day; this wiki exists so any teammate (human, Codex, or GLM) can pick up any part of the system in minutes.

## Pages

| page | one-liner |
|---|---|
| [The Event](The-Event.md) | date, schedule, prizes, judges, the five-part loop brief, "march of nines" |
| [Architecture](Architecture.md) | system diagram, loop parts mapped to components, design principles |
| [Robot Bus](Robot-Bus.md) | the wire protocol: envelope, delivery rules, topics, ports, logging |
| [The Simulators](The-Simulators.md) | armsmith_web, fake_sim, the MuJoCo models — when to use which |
| [The Learning Loop](The-Learning-Loop.md) | the L0–L4 escalation ladder, labelling contract, metrics, streaming |
| [System One Laya](System-One-Laya.md) | the calibrated classifier, the frozen schema, train/gate/register |
| [System Two alexei](System-Two-alexei.md) | the GLM reasoner, its dossier, the safety shield, latencies |
| [Agent Team](Agent-Team.md) | every agent, the escalation ladder, Codex workflow, morning checklist |
| [Training](Training.md) | RL / BC / distillation tiers, throughput numbers, iGPU unlock, Kaggle T4 |
| [Vision](Vision.md) | hand teleop, tape tracker, ArUco pose, measured latency budget, pitfalls |
| [Assets and Lineage](Assets-and-Lineage.md) | every prior project this repo builds on |
| [Operations Runbook](Operations-Runbook.md) | the day hour-by-hour, decision rules, risks, pack list, hard rules |
| [Testing and Benchmarks](Testing-and-Benchmarks.md) | every test + the headline measured numbers |
| [FAQ](FAQ.md) | the questions everyone asks, answered in wiki voice |

## 5-minute quickstart

```bash
scripts/setup_sim_env.sh                                          # light venv (mujoco/opencv/mediapipe/websockets)
sim/py/.venv/bin/python agents/hub.py &                           # the bus  ws://127.0.0.1:8890/ws
sim/py/.venv/bin/python agents/fake_sim.py --fault ik_residual &  # deterministic stall
sim/py/.venv/bin/python control/stall_controller.py               # THE LOOP (dry-run safe)
```

That is the full learning loop headless, in three terminals, no browser. Then:

```bash
bash sim/dashboard/serve.sh                                       # hub + sim :8891 + dashboard :8892
sim/py/.venv/bin/python agents/cli.py roster                      # who is online
sim/py/.venv/bin/python agents/cli.py stall                       # why did it fail (dossier)
bash scripts/acceptance.sh                                        # whole loop, headless, ~4 min
```

Two venvs, never mixed: `sim/py/.venv` (light) and `training/.venv` (heavy, CPU torch + lerobot). See [Testing and Benchmarks](Testing-and-Benchmarks.md) for what "PASS" means.

## Use + feasibility

Use this wiki on the day for lookup only — every page states what a component is FOR, when to run it on a one-day clock, and its honest feasibility (latency, cost, risk). Everything here runs loopback with local models; nothing needs the internet at demo time (the web sim is fully vendored, MuJoCo is CPU, Laya/GLM are local). The known gaps are stated where they exist (e.g. the Laya `robot-ops` checkpoint is not yet trained; MCAP export is not built).

## See also

- [Operations Runbook](Operations-Runbook.md) — the day plan and hard rules
- [docs/TEAM_HANDOVER.md](../docs/TEAM_HANDOVER.md) — the full onboarding document
- [AGENTS.md](../AGENTS.md) — the brief coding agents auto-load
