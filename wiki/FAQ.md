# FAQ

**The questions everyone asks, answered from the repo's own docs — with the honest caveats included.** Use + feasibility: this page is for mid-day lookup under pressure; every answer carries its measured latency, cost or risk where one exists, and the "Can this run on the real arm?" answer is the most important honest line in the wiki — nothing here has been validated on live hardware yet.

## Why not Isaac Sim?

It cannot run on our hardware, full stop ([docs/05_simulators_isaac.md](../docs/05_simulators_isaac.md)): Isaac Sim requires an RTX GPU with RT Cores, 16 GB VRAM minimum, Ubuntu 22.04/24.04 and driver 595.x — even NVIDIA datacenter cards without RT Cores are excluded, and no AMD/ROCm/Arch path exists anywhere in its docs. Our box is an AMD Ryzen AI Max+ 395 with a Radeon 8060S iGPU (no CUDA). Plan A is the MuJoCo ecosystem on CPU — which also happens to be what LeRobot's RL tooling uses — and it is not a compromise: 89k steps/s single-thread makes 10,000-episode evaluations cost seconds.

## What do the S2 latency numbers actually mean?

Three different regimes ([docs/08_stall_learning_loop.md](../docs/08_stall_learning_loop.md)): **15–30 s** is the blocking path under 3-model GPU memory contention (~14 tok/s); **~5.5 s** is an uncontended 255-token plan (~46 tok/s — the honest per-request rate); and **2.05 s** is time-to-first-action when streaming, because the first plan step is complete roughly a third of the way through the decode. Cold loads (model evicted) add 17–82 s of pure weight-loading — which is why the model is pre-warmed at 9:00 with a 2 h keep-alive.

## Why does Laya start "dumb"?

There is no trained `robot-ops` checkpoint yet (4 real labelled rows as of 24 Nov; ~250 for an honest r1, ~1.5k for the calibration gate). Until one passes the GUT gate (agreement ≥0.85, ECE ≤0.10), serve falls back to the base English model — verdicts are schema-shaped but uncalibrated. That is deliberate staging: the untrained-vs-trained curve IS the demo. See [System One](System-One-Laya.md).

## Is monocular mocap good enough for robot movement?

For teleop and demo collection, yes — with three disciplines ([Vision](Vision.md)): retarget *relatively* (MediaPipe world landmarks have no absolute position; scale + calibrated offset), clamp everything to the workspace box, and respect the ~45 ms sensor-to-bus latency (fine for teleop, wrong for hard-real-time control). Expect ±cm z-noise from a single camera and treat it accordingly.

## What are "nines" and how do we measure them?

`nines = -log10(failure_rate)` — 99% success per action is 2 nines, and a 99%-reliable robot finishes a 100-action task 37% of the time (99.9% → 90%; 99.99% → 99%). We measure it honestly: thousands of episodes are affordable because MuJoCo physics is effectively free (a 10,000-episode eval ≈ 17 s), the number lives in `runs/metrics.json` with its baseline, and the dashboard renders before → after live.

## How do I add a new agent/sensor to the bus?

The 60-second recipe ([docs/02_agent_network.md](../docs/02_agent_network.md)): pick a unique name; read [docs/PROTOCOL.md](../docs/PROTOCOL.md); use `SyncBus` (Python) or copy `sim/armsmith_web/src/bus.js` (JS) for hello/subscribe/publish; register it in `agents/registry.json`. Never send anything you wouldn't want logged forever. High-rate topics need an explicit `bus.sub`.

## How do I swap the System-2 model?

The default lives in `control/robot_ops.schema.json` (`s2.model_default` = `glm-4.7-flash-abl:alexei-v3`). Override per-run with `--model` on `control/stall_controller.py` (or `glm_s2.py --probe`), or the `MODEL` env for `scripts/acceptance.sh` (it defaults to the resident base `glm-4.7-flash-abl:32k`). Whatever you swap in goes through the same shield — the skill whitelist and clamps are model-independent. Keep ≤2 Ollama models resident (18 GB each; ~40–60 GB for two).

## Where does the training data come from?

One hub log, three uses ([docs/TEAM_HANDOVER.md](../docs/TEAM_HANDOVER.md)): `runs/bus/*.jsonl` records every envelope (image payloads stripped, so converted datasets are state-only via `use_videos=False`); the stall controller appends soft-labelled S2→S1 rows to `data/robot-ops.jsonl`; vision `--record` and the web sim's "Export ep_*.jsonl" add demo streams. `training/to_lerobot_dataset.py` converts any of them to LeRobotDataset v3.0.

## What happens if the hub dies mid-run?

Nothing crashes ([docs/02_agent_network.md](../docs/02_agent_network.md)): every client degrades to local operation and reconnects with retry; the sim keeps accepting human control; Laya-down fail-opens the gate straight to S2; GLM-down falls back to the scripted bounded recovery (max 3/episode, then a teleop request); the dashboard banner just says "bus offline — retrying…". The one thing you must not do is truncate `runs/bus/*.jsonl` — it is the dataset.

## Can this run on the real arm?

The protocol is hardware-neutral — SO-101 is first-class in LeRobot (driver, calibration, teleop, record tooling; doc 04), BYO hardware is welcome at the event, and our `robot_hand` project is the physical twin. Honest status: everything here has only been run in simulation; the same bus would point at the real arm, and the decision rule is "if real hardware is available, run the loop against it" — but no live-hardware validation exists yet, and the stall shield's workspace box must be re-checked against the physical arm before the first real command.

## See also

- [The Learning Loop](The-Learning-Loop.md) — the mechanics behind half these answers
- [Operations Runbook](Operations-Runbook.md) — the day plan and hard rules
