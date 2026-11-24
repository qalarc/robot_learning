# The Simulators

**Three interchangeable simulators — a browser arm (armsmith_web), a headless stub (fake_sim), and MuJoCo — all speaking the same `sim.obs`/`sim.cmd` protocol, so the loop never notices which one is running.**

## armsmith_web (the human-facing sim)

Zero-build Three.js + Rapier port of our Unity ARMSMITH project ([details](../sim/armsmith_web/README.md), lineage in [Assets and Lineage](Assets-and-Lineage.md)). Serves at `http://127.0.0.1:8891/`; vendored three.js/Rapier (Rapier wasm embedded) so it works on venue Wi-Fi with no CDN. Uses the **real SO-101 STL meshes** (`assets/so101/`) and the Unity-verified kinematics (112.6/134.9 mm segments, TCP 98.1 mm); FABRIK IK residual ~1 cm in the work envelope (Unity's was ~7 cm).

- **Modes**: `ik` / `joint` / `script` / `mocap` / `off` (bus `mode` command). **Mocap mode** follows `vision.hands` `ee_target`, gripper = pinch, holds last target 0.6 s when hands vanish, calibration sliders in the HUD.
- **Physics toggle**: kinematic (default; deterministic servo-FK, assist-grasp so demos never break) vs `?physics=dynamic` (experimental PD-motor bodies — sags under gravity like a weak servo; kinematic stays the demo default).
- **Controls**: LMB drag = IK target on the work-plane, wheel = depth, keys jog joints 1–6, N/B wrist roll, G/Space gripper, Tab ik↔joint, Z home, X reset — full table in the README. HUD: scenario/mode selects, joint sliders, episode/ok/fail counters, stall meter, **record + "Export ep_*.jsonl"** buttons.
- **Puppet view** `?view=puppet`: the page becomes a pure display for any external `sim.obs` publisher (e.g. MuJoCo training) — this is how you "train headless, watch in Three.js".
- Query params: `?hub=`, `?physics=dynamic`, `?scenario=`, `?autotest=1`. Needs WebGL2 + HTTP (ES modules; no `file://`).

**Use + feasibility**: FOR demos and human teleop/demos — drive it at 10:30 once the scenario is chosen. Feasibility: headless-Chromium smoke PASS (`step=1203 obs_sent=599`); needs a WebGL browser; snapshot needs a working GL context.

## fake_sim (the headless stub)

Protocol-complete Python stub (`agents/fake_sim.py`): 6 slew-limited joints, abstract EE (0.5 m/s), grasp-on-distance, full `sim.obs` at 30 Hz, request/reply, deterministic under a seed, auto episode reset after `--ep-len` (default 300). **Injectable faults**: `--fault ik_residual` (EE stops 7 cm above target — the classic stall) and `--fault slip` (drops a grasped object once lifted >5 cm).

**Use + feasibility**: FOR testing the loop with no browser, and for reproducible stall data collection — run it overnight to accumulate Laya rows. Feasibility: trivial CPU cost, zero risk; it is the executable spec for new `sim.cmd` verbs.

## MuJoCo (the training physics)

Two SO-101 MJCF models in `sim/mujoco/` ([bench](../docs/benchmarks/LOCAL_MUJOCO_BENCH.md)):

| model | what | steps/s (single thread) |
|---|---|---|
| `so101_official/so101_new_calib.xml` | official TheRobotStudio model, 13 STLs, nq=6, 30 geoms, 0 warnings | **89.6k** |
| `so101_simple/so101_simple.xml` | hand-written 6-DOF + 2 prismatic fingers + cube; capsules, no meshes | 53.1k |

Plus bench models `humanoid_simple.xml` and `two_link.xml`. `sim/py/mujoco_env.py` wraps them as Gymnasium envs that publish on the bus; `MUJOCO_GL=egl` renders offscreen at 229 fps @ 640×480 on the iGPU.

**Use + feasibility**: FOR PPO and fast eval rollouts (32 envs ≈ 0.6 s for 32×500 steps) — start RL early and keep it running all day. Feasibility: physics is CPU and effectively free; the wall-clock bottleneck is the learner, not `mj_step`. Note: `training/train_rl.py` is referenced by the docs but was still landing at wiki time — see [Training](Training.md).

**Which one when**: browser sim = humans watch/drive; fake_sim = controllers and overnight data; MuJoCo = training and honest nines at scale. All three publish identical `sim.obs` shapes, so [The Learning Loop](The-Learning-Loop.md) is simulator-agnostic.

## See also

- [Robot Bus](Robot-Bus.md) — the protocol all three speak
- [docs/04_lerobot_mujoco.md](../docs/04_lerobot_mujoco.md) — MuJoCo 4 field guide
- [Testing and Benchmarks](Testing-and-Benchmarks.md) — the bench numbers
