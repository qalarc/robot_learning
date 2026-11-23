# vision/ — camera → robot input layer

MediaPipe hand tracking, the "blue tape" HSV tracker redux, and ArUco marker
poses — all publishing on the Robot Bus per `docs/PROTOCOL.md`
(`vision.hands`, `vision.tape`, `vision.marker`, `vision.frame`).

Everything here runs on the **light** venv:

```bash
sim/py/.venv/bin/python   # mediapipe 1.2.3 (Tasks API), opencv 5.1.0, numpy 2.5
```

## Layout

| path | what |
|---|---|
| `find_cameras.py` | list `/dev/video*` + probe OpenCV indices → JSON (which index actually has pixels) |
| `hand_tracking/hand_tracker.py` | live hand landmarks → bus; `--bench N` for CPU FPS |
| `hand_tracking/retarget.py` | PURE landmark→EE math (numpy only): `landmarks_to_ee`, `pinch_score`, `fist_score`, `OneEuro`, `clamp_to_workspace`, `arm_keypoints_to_ee` |
| `hand_tracking/test_retarget.py` | synthetic-landmark unit tests (no camera) |
| `hand_tracking/fixtures/` | CC0 hand photo + `SOURCES.txt` (no webcam was used) |
| `hand_tracking/models/` | `hand_landmarker.task` (Apache-2.0, Google) |
| `tape_tracker/tape_tracker.py` | HSV colour tracker (+`--learn`, `--pid`) → bus |
| `tape_tracker/marker_pose.py` | ArUco DICT_6X6_250 + solvePnP → bus (uncalibrated-K warning) |
| `tape_tracker/test_tape.py`, `test_marker.py` | synthetic-frame tests |
| `preview/index.html` | zero-build bus preview page (plain JS) |

## Install

Nothing to install — deps are already in `sim/py/.venv`. The only download is
the hand-landmarker model (already fetched; if missing):

```bash
curl -L -o vision/hand_tracking/models/hand_landmarker.task \
  https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task
```

> **MediaPipe ≥1.2 note:** the legacy `mp.solutions.hands` path is GONE.
> This is the Tasks API only: `from mediapipe.tasks.python import vision`,
> `HandLandmarker.create_from_options(...)`, VIDEO running mode +
> `detect_for_video(img, monotonic_ms)`. Result fields: `hand_landmarks`
> (normalised image), `hand_world_landmarks` (metres, hand-centred),
> `handedness` (list of `Category.category_name`).

## Quickstart 1 — hand → mocap / EE teleop

```bash
sim/py/.venv/bin/python agents/hub.py &          # the bus
sim/py/.venv/bin/python vision/hand_tracking/hand_tracker.py --source 2 \
    --scale 0.6 --offset 0.15 0.0 0.15 --record runs/hands.jsonl
```

* `--source` is a camera index (`vision/find_cameras.py` tells you which) or a
  video/image path (an image becomes a looping fixture).
* Watch it: `vision/preview/index.html` (serve `vision/` with any static
  server, open `preview/index.html?port=8890`).
* Calibration: hold your hand where you want the *neutral* EE pose, note the
  printed `ee_target`, and pass the negated value as `--offset` (targets are
  hand-relative × `--scale` + offset — MediaPipe world landmarks have NO
  absolute position; see the docstring in `retarget.py`).
* Feed the sim's mocap mode: subscribe to `vision.hands` and forward
  `ee_target` as a `sim.cmd ee` (`mode: mocap`). Keep `clamp_to_workspace`
  between vision and the arm — never trust raw targets.
* Offline later: `--record` writes raw 21-landmark JSONL (dataset material).

## Quickstart 2 — tape track

```bash
sim/py/.venv/bin/python vision/tape_tracker/tape_tracker.py --source 2 --blue
# PID heading instead of raw proportional steer:
... --pid 0.8 0.05 0.1        # KP KI KD on the normalised centroid error
# any colour, OpenCV HSV scale (H 0-179):
... --custom 100 130 80 255 60 255
```

## Quickstart 3 — marker pose

```bash
# print a DICT_6X6_250 marker (id 7), e.g. 6 cm side:
sim/py/.venv/bin/python -c "import cv2; cv2.imwrite('m7.png', cv2.aruco.generateImageMarker(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_6X6_250), 7, 600))"
sim/py/.venv/bin/python vision/tape_tracker/marker_pose.py --source 2 --marker-len 0.06
```

⚠ Positions use **default (uncalibrated) intrinsics** (`fx=fy=w`, centre
centre) — rough distances only. Pass `--calib file.npz` (`mtx`,`dist` from
`cv2.calibrateCamera`) for real metrology.

## HSV tuning workflow

1. `--learn` + a display: click the tape in the preview window; it prints the
   equivalent `--custom H0 H1 S0 S1 V0 V1` (±12 H, ±60 S/V around the pixel).
2. Headless: grab a still (`agents/cli.py snapshot`), open Python, sample
   `cv2.cvtColor(img, COLOR_BGR2HSV)` at a few tape pixels, take min/max per
   channel ± slack, pass `--custom`.
3. Sanity: run `tape_tracker/test_tape.py` — its synthetic strip uses the blue
   preset, so a failing test usually means a broken range, not the pipeline.
4. Remember: threshold mostly on S/V (illumination lives in V), morph open→
   close is already applied, `--min-area` rejects speckle blobs.

## Calibration workflow (camera intrinsics)

1. Print an OpenCV chessboard (9×6, e.g.
   `cv2.findChessboardCorners`-friendly 2–2.5 cm squares), tape it flat.
2. Capture ~20 poses (`snapshot` or `--record` stills), then
   `cv2.calibrateCamera` over them → save `{"mtx":…, "dist":…}` as `.npz`.
3. `marker_pose.py --calib that.npz` → `pos_m` becomes metres you can trust.
   The same `.npz` upgrades `vision.marker` to real 6-DoF ground truth for
   the stall controller's "where was the arm pointing" question.

## Tests

```bash
sim/py/.venv/bin/python vision/hand_tracking/test_retarget.py   # 17 checks
sim/py/.venv/bin/python vision/tape_tracker/test_tape.py        # 9 checks
sim/py/.venv/bin/python vision/tape_tracker/test_marker.py      # 12 checks
sim/py/.venv/bin/python vision/hand_tracking/hand_tracker.py --bench 300 --source vision/hand_tracking/fixtures/hand_open.jpg
```

All synthetic tests run without a camera and without the bus.

## Known limitations

* **No absolute scale** from hands (world landmarks are hand-centred metres —
  relative motion + `--offset` calibration only). Markers: uncalibrated K
  until you calibrate.
* **Latency:** camera cadence (33 ms @30 fps) + inference (~9 ms @VGA) +
  JPEG/bus (~1.5 ms) ⇒ ~45 ms sensor-to-bus; see
  `docs/07b_vision_tools.md` for the measured table.
* **Occlusion:** MediaPipe drops a hand under heavy self-occlusion; the bus
  message just omits it (`hands: []`), consumers must tolerate gaps.
* **Lighting:** HSV presets assume a normally-lit room; re-`--learn` under
  stage/demo lighting.
* MediaPipe occasionally flips handedness when hands cross — per-hand OneEuro
  chains keep the smoothing sane but don't fix a wrong label.
