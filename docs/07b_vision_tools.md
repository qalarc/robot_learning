# 07b — Vision tools: camera → robot input layer

> Built 2026-11-24. See `vision/README.md` for quickstarts and
> `docs/PROTOCOL.md` for the `vision.*` topic contracts. Every number in the
> latency table below was **measured on this machine** (Ryzen AI Max+ 395,
> CPU-only, MediaPipe 1.2.3 Tasks API, OpenCV 5.1.0) — method noted per row.

## What exists

| file | publishes | consumes |
|---|---|---|
| `vision/hand_tracking/hand_tracker.py` | `vision.hands` (≤30 Hz), `vision.frame` (≤10 Hz) | camera/video/image |
| `vision/tape_tracker/tape_tracker.py` | `vision.tape` (≤30 Hz), `vision.frame` | camera/video |
| `vision/tape_tracker/marker_pose.py` | `vision.marker` (≤30 Hz), `vision.frame` | camera/video |
| `vision/find_cameras.py` | — (JSON to stdout) | `/dev/video*` |
| `vision/preview/index.html` | — | all four topics |

All three trackers degrade the same way: bus down → warn once and keep
tracking locally; camera gone → clear error + a probe dump of usable indices.

## How vision feeds the loop

### Sim mocap mode
The sim (`sim.cmd mode {"control":"mocap"}`) expects external pose input.
The bridge is a ~20-line subscriber: take `vision.hands → hands[i].ee_target`
(already retargeted to the robot base frame by `retarget.landmarks_to_ee`,
clamped to the workspace box by `clamp_to_workspace`) and forward it as
`sim.cmd {"cmd":"ee","args":{"pos":ee_target,"gripper":1-pinch}}`. The pinch
score (1.0 = tips touching) maps directly onto the gripper: pinch to grab,
open to release. Until that bridge lands, `--record runs/hands.jsonl` gives
you the same signal offline — the JSONL is already dataset-shaped for
`training/to_lerobot_dataset.py`.

### Stall controller
`vision.marker` is the cheap ground-truth channel: put one 6 cm ArUco on the
table and one on the end-effector. When `sim.obs` reports a stall, the
controller can compare commanded EE position against the marker's
`pos_m` to answer "did the arm physically go where the sim thinks it went?"
— the sim-vs-reality disagreement is exactly the failure class the learning
loop hunts. `vision.tape.steer` gives the same role for line/wand-following
scenarios (steer ≠ 0 while progress stalls = the target moved, not the robot).

### Preview page
`vision/preview/index.html` subscribes to all four topics (high-rate topics
are opt-in per the protocol — it sends `bus.sub` after `bus.hello`) and shows
the annotated JPEG plus live numbers. Serve `vision/` statically; no build
step, no CDN.

## Latency budget (measured, 2026-11-24)

Machine: Ryzen AI Max+ 395, CPU-only. Bench method: `hand_tracker --bench 300`
fixture-loop (inference only); 300-iteration loops for the pure stages; the
bus row is 100 send→recv probes through the live hub on one host.

| stage | p50 | p95 | notes |
|---|---|---|---|
| camera cadence (V4L2 @30 fps) | 33.3 ms | — | frame *period*, not latency; the sensor-to-buffer delay of a cheap webcam is typically +1–2 frames [unverified] |
| MediaPipe inference @640×480 | 8.9 ms | 10.4 ms | 110 fps mean, fixture bench, VIDEO mode |
| MediaPipe inference @1280×748 | 17.5 ms | 22.0 ms | 44–54 fps mean across runs (load-dependent — other agents train on this box) |
| tape HSV pipeline (640-wide) | 0.66 ms | 1.19 ms | inRange + morphology + contours |
| ArUco detect + solvePnP (640-wide) | 1.79 ms | 2.33 ms | IPPE_SQUARE |
| JPEG encode + base64 (640-wide) | 0.60 ms | 0.83 ms | ~31 KB payload @ q65 |
| bus one-way (pub→sub, hub relay) | 0.61 ms | 1.13 ms | vision.hands probe, same host |
| **sensor→bus total (hands, VGA)** | **~45 ms** | **~55 ms** | cadence 33 + infer 9 + encode/bus 2 |
| published `vision.hands` rate | ~26 Hz | — | probe counted 104 msgs / 4 s, cap 30 Hz |
| published `vision.frame` rate | ~9 Hz | — | cap 10 Hz |
| live tracker loop (fixture, 1280×748) | 39–53 fps | — | incl. detect + annotate + JPEG + publish |

Read it as: the bus and encoding are free; the pipeline is bounded by camera
cadence and inference. Don't shrink `--hands-hz` below what consumers need —
the stall controller cares about *staleness*, not rate.

## Limitations (honest list)

1. **No absolute scale from hands.** MediaPipe *world* landmarks are metres
   relative to the hand's own geometric centre — never an absolute position
   in the room. That is why the retarget pipeline is hand-relative × scale +
   a calibrated offset. Budget a 30-second calibration at demo start.
2. **Marker poses use uncalibrated intrinsics** by default (`fx=fy=w`).
   Good enough for "is it left or right of centre", not for millimetres.
   `--calib` + a chessboard run fixes it (workflow in `vision/README.md`).
3. **Latency:** ~45 ms sensor-to-bus for hands. Fine for teleop and
   stall-correlation; do not use vision as a hard-real-time control loop.
4. **Occlusion:** a hand that hides itself just disappears from
   `vision.hands` (`hands: []`); consumers must handle gaps, not NaNs.
5. **Handedness flips** occasionally when hands cross in a selfie view.
6. **Lighting:** HSV presets are tuned for a normally-lit room; re-learn with
   `--learn` (or `--custom`) under venue lighting before the demo.
7. Webcams were **not** used to build or test any of this — all tests are
   synthetic (numpy canvases, rendered ArUco, CC0 photo fixture, see
   `vision/hand_tracking/fixtures/SOURCES.txt`). The only live-hardware
   fact assumed is that `/dev/video2` opens with pixels (probe output).
