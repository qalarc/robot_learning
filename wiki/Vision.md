# Vision

**Camera → robot input: MediaPipe hand teleop, the HSV "blue tape" tracker, and ArUco metric pose — all bus publishers with a measured ~45 ms sensor-to-bus latency and three hard physical limits you must design around.** Sources: [vision/README.md](../vision/README.md), [docs/07b_vision_tools.md](../docs/07b_vision_tools.md).

## The pipeline (hand tracking)

`hand_tracker.py` runs MediaPipe **Tasks API** HandLandmarker (mediapipe 1.2.3; the legacy `mp.solutions` path is gone) on the light venv: camera → 21 landmarks + handedness per hand → `retarget.py` (pure numpy) → `vision.hands` on the bus (≤30 Hz) + annotated `vision.frame` (≤10 Hz). Retarget maths: targets are **hand-relative x scale (`--scale`) + offset (`--offset`)** — MediaPipe world landmarks have *no absolute position*; per-axis **One-Euro** smoothing; pinch/fist scores (tip distances normalised by hand span) drive the gripper; `clamp_to_workspace` enforces the frozen box before anything reaches the arm. Sim mocap mode consumes `hands[0].ee_target` as an `ee` command; pinch closes the gripper. `--record runs/hands.jsonl` writes dataset-shaped JSONL offline.

## Tape tracker and marker pose

`tape_tracker.py` is the "blue tape robot" lineage (see [Assets and Lineage](Assets-and-Lineage.md)): HSV inRange + morphology + contours, `--learn`/`--custom` retuning, optional `--pid` steering → `vision.tape` with a `steer` ∈ [−1,1] signal. `marker_pose.py` prints DICT_6X6_250 ArUco markers and solves PnP → `vision.marker` metric `pos_m` — the cheap ground-truth channel for "did the arm physically go where the sim thinks?" (uses **uncalibrated intrinsics by default**: `--calib` + a chessboard run makes it real metrology). `vision/preview/index.html` watches all four topics; zero build.

## Measured latency budget (07b, this machine, CPU)

| stage | p50 | notes |
|---|---|---|
| MediaPipe inference @640x480 | 8.9 ms | 110 fps mean; 17.5 ms @1280x748 |
| tape HSV pipeline | 0.66 ms | inRange + morphology + contours |
| ArUco detect + solvePnP | 1.79 ms | IPPE_SQUARE |
| JPEG encode + base64 | 0.60 ms | ~31 KB @ q65 |
| bus one-way | 0.61 ms | same host |
| **sensor→bus total (hands, VGA)** | **~45 ms (p95 ~55)** | bounded by camera cadence (33.3 ms) + inference |

Published rates: `vision.hands` ~26 Hz, `vision.frame` ~9 Hz. Tests: 17 retarget checks, 9 tape, 12 marker — all synthetic (no webcam was used; fixture + SOURCES.txt).

## The three big pitfalls

1. **No absolute scale** — hand world landmarks are metres from the hand's own centre; retarget is relative-only, so budget a 30-second neutral-pose calibration (`--offset`) at demo start.
2. **z-noise / depth ambiguity** — single-camera z is model prior, not measurement (±cm errors, occlusion flips); clamp z hardest, prefer table-plane tasks.
3. **Latency budget** — ~45 ms sensor-to-bus is fine for teleop and stall correlation; vision is **not** a hard-real-time control loop. Also: hands vanish under occlusion (`hands: []` — consumers handle gaps), handedness flips when hands cross, HSV presets need re-`--learn` under venue lighting.

## Use + feasibility

**FOR**: live demos (recipe D in [TEAM_HANDOVER](../docs/TEAM_HANDOVER.md)) and human demo collection for ACT. **On the one-day clock**: test with the fixture image before the day; the live end-to-end run against the web sim is still pending (honest status) — if it misbehaves on the day, teleop is a stretch goal, not a dependency. **Feasibility**: CPU-only, ~9 ms inference at VGA, no GPU needed; risk is venue lighting and camera index surprises (`vision/find_cameras.py` probes which `/dev/video*` actually has pixels).

## See also

- [Robot Bus](Robot-Bus.md) — the `vision.*` topic contracts
- [The Simulators](The-Simulators.md) — mocap mode on the receiving end
- [docs/07_vision_mocap_landscape.md](../docs/07_vision_mocap_landscape.md) — the full landscape review
