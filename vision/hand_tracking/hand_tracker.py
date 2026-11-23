#!/usr/bin/env python3
"""hand_tracker.py — MediaPipe hand landmarks → bus: vision.hands + vision.frame.

MediaPipe 1.2.x is the Tasks-API-only package: import via
``mediapipe.tasks.python.vision`` (the legacy ``mp.solutions.hands`` path does
NOT exist any more). We run HandLandmarker in VIDEO running mode with
monotonically increasing ms timestamps, exactly what detect_for_video expects.

Pipeline per frame:
  capture → RGB → detect_for_video → 21 img + 21 world landmarks per hand
  → pinch/fist scores (retarget.py, ratio-normalised like gesture_tracker.py)
  → ee_target = hand-relative wrist/index-MCP point × scale + offset, mirrored
    for Right hands (retarget.landmarks_to_ee; see its docstring for why
    world landmarks can never give an absolute position)
  → One-Euro smoothing per axis (retarget.OneEuro; supersedes the fixed EMA
    from robot_hand/hand_mirror.py SMOOTHING=0.5)
  → publish vision.hands (≤30 Hz) + vision.frame JPEG (≤10 fps) via SyncBus.

Degradation: no camera → clear error + camera probe dump, exit 2. Bus down →
warn once, keep tracking locally (the hub must never take vision down).

Usage:
  sim/py/.venv/bin/python vision/hand_tracking/hand_tracker.py --source 2
  sim/py/.venv/bin/python vision/hand_tracking/hand_tracker.py \
      --source 2 --scale 0.6 --offset 0.15 0 0.15 --record out.jsonl
  sim/py/.venv/bin/python vision/hand_tracking/hand_tracker.py --bench 300 \
      --source fixtures/hand_open.jpg          # FPS on the fixture image
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent))  # vision/ — find_cameras lives here
sys.path.insert(0, str(_REPO / "agents"))

import mediapipe as mp  # noqa: E402
from mediapipe.tasks.python import vision as mpv  # noqa: E402

import retarget as R  # noqa: E402

MODEL_PATH = _HERE / "models" / "hand_landmarker.task"

# Skeleton connections for the annotated preview — same edge list as
# robot_hand/python/robot_vision.py HAND_CONNECTIONS.
HAND_CONNECTIONS = [
    (0, 1),
    (1, 2),
    (2, 3),
    (3, 4),
    (0, 5),
    (5, 6),
    (6, 7),
    (7, 8),
    (0, 9),
    (9, 10),
    (10, 11),
    (11, 12),
    (0, 13),
    (13, 14),
    (14, 15),
    (15, 16),
    (0, 17),
    (17, 18),
    (18, 19),
    (19, 20),
    (5, 9),
    (9, 13),
    (13, 17),
]


def build_landmarker(num_hands: int = 2) -> "mpv.HandLandmarker":
    """Tasks-API landmarker, VIDEO mode (needs detect_for_video + rising ts)."""
    if not MODEL_PATH.exists():
        sys.exit(
            f"error: model missing at {MODEL_PATH}\n"
            "download once:\n"
            "  curl -L -o vision/hand_tracking/models/hand_landmarker.task \\\n"
            "    https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
            "hand_landmarker/float16/latest/hand_landmarker.task"
        )
    opts = mpv.HandLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(MODEL_PATH)),
        running_mode=mpv.RunningMode.VIDEO,
        num_hands=num_hands,
        min_hand_detection_confidence=0.5,
        min_hand_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    return mpv.HandLandmarker.create_from_options(opts)


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def open_capture(source: str, width: int, height: int) -> tuple:
    """Open --source 0|2|/path/video → (cap_or_None, is_cam, still_frame).

    Still images (fixture mode) bypass VideoCapture entirely — FFMPEG cannot
    re-seek a single JPEG, so the main loop just reuses the decoded frame.
    Returns (None, False, img) for that case.
    """
    try:
        idx = int(source)
        cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        # V4L2 metadata nodes OPEN fine but never deliver frames — require a
        # real first read before trusting the handle, else fall to the error
        # path with a probe dump.
        if not (cap.isOpened() and cap.read()[0]):
            cap.release()
            import find_cameras  # sibling script in vision/

            probe = find_cameras.probe_indices(list(range(0, 13)))
            usable = [c["index"] for c in probe if c.get("can_open")]
            sys.exit(
                f"error: cannot open camera source {source!r}.\n"
                f"OpenCV probe says usable indices: {usable or 'NONE'}.\n"
                f"Device nodes: "
                f"{[str(p) for p in sorted(Path('/dev').glob('video*'))]}\n"
                "fix: pass a working index (e.g. --source 2) or a file path."
            )
        return cap, True, None
    except ValueError:
        pass

    ext = Path(source).suffix.lower()
    if ext in IMAGE_EXTS:
        img = cv2.imread(source)
        if img is None:
            sys.exit(f"error: cannot read image file {source!r}")
        return None, False, img

    cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
    if not cap.isOpened():
        import find_cameras  # sibling script in vision/

        probe = find_cameras.probe_indices(list(range(0, 13)))
        usable = [c["index"] for c in probe if c.get("can_open")]
        sys.exit(
            f"error: cannot open camera/video source {source!r}.\n"
            f"OpenCV probe says usable indices: {usable or 'NONE'}.\n"
            f"Device nodes: {[str(p) for p in sorted(Path('/dev').glob('video*'))]}\n"
            "fix: pass a working index (e.g. --source 2) or a video file path."
        )
    return cap, False, None


def annotate(
    frame: np.ndarray,
    res,  # HandLandmarkerResult
    ee_targets: list[np.ndarray],
) -> np.ndarray:
    """Skeleton overlay + scores, drawn the compact robot_hand way."""
    h, w = frame.shape[:2]
    for i, lm_list in enumerate(res.hand_landmarks):
        pts = [(int(l.x * w), int(l.y * h)) for l in lm_list]
        for a, b in HAND_CONNECTIONS:
            cv2.line(frame, pts[a], pts[b], (255, 176, 59), 2, cv2.LINE_AA)
        for j, p in enumerate(pts):
            cv2.circle(
                frame,
                p,
                4 if j in (4, 8, 12, 16, 20) else 2,
                (255, 219, 88) if j in (4, 8, 12, 16, 20) else (88, 205, 255),
                -1,
                cv2.LINE_AA,
            )
        hand = res.handedness[i][0].category_name
        cv2.putText(
            frame,
            hand,
            (pts[0][0] - 20, pts[0][1] + 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        if i < len(res.hand_world_landmarks):
            wl = res.hand_world_landmarks[i]
            pinch = R.pinch_score(wl)
            fist = R.fist_score(wl)
            cv2.putText(
                frame,
                f"pinch={pinch:.2f} fist={fist:.2f}",
                (pts[0][0] - 20, pts[0][1] + 64),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (200, 220, 255),
                1,
                cv2.LINE_AA,
            )
    for i, ee in enumerate(ee_targets):
        if i < len(res.hand_landmarks) and res.hand_landmarks[i]:
            wr = res.hand_landmarks[i][0]
            pos = (int(wr.x * w), int(wr.y * h))
            cv2.putText(
                frame,
                f"ee=[{ee[0]:+.2f} {ee[1]:+.2f} {ee[2]:+.2f}]",
                (pos[0] - 20, pos[1] + 44),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (80, 255, 80),
                1,
                cv2.LINE_AA,
            )
    return frame


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--source", default="0", help="camera index or video/image path")
    ap.add_argument(
        "--scale",
        type=float,
        default=0.6,
        help="robot metres per hand-relative metre (default 0.6)",
    )
    ap.add_argument(
        "--offset",
        nargs=3,
        type=float,
        default=[0.15, 0.0, 0.15],
        metavar=("X", "Y", "Z"),
        help="workspace anchor, robot frame (m)",
    )
    ap.add_argument(
        "--mincutoff", type=float, default=1.0, help="OneEuro min cutoff Hz"
    )
    ap.add_argument(
        "--beta", type=float, default=0.007, help="OneEuro speed coefficient"
    )
    ap.add_argument("--hands", type=int, default=2, help="max hands to track")
    ap.add_argument(
        "--hands-hz", type=float, default=30.0, help="vision.hands rate cap"
    )
    ap.add_argument(
        "--frame-hz", type=float, default=10.0, help="vision.frame rate cap"
    )
    ap.add_argument("--jpeg-w", type=int, default=640, help="annotated preview width")
    ap.add_argument("--record", default="", help="write raw landmarks JSONL here")
    ap.add_argument(
        "--nogui", action="store_true", default=True, help="no cv2 window (default)"
    )
    ap.add_argument("--show", action="store_true", help="open a preview window")
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument(
        "--bench",
        type=int,
        default=0,
        help="N synthetic detections on --source image, print FPS, exit",
    )
    ap.add_argument(
        "--bus", default="", help="explicit bus URL (else ROBOT_BUS_URL/bus.port)"
    )
    args = ap.parse_args()

    # ---------------------------------------------------------------- bus
    bus = None
    try:
        from bus_client import SyncBus  # noqa: PLC0415  (degrade-able import)

        bus = SyncBus(
            "vision-hands", url=args.bus or None, roles=["tool"], caps=["mediapipe"]
        )
        print(f"bus: connected as {bus.name}")
    except Exception as e:  # noqa: BLE001 — offline mode is a feature
        print(f"WARN: bus unreachable ({e}); running offline, no publishing")

    def publish(topic: str, data: dict) -> None:
        if bus is not None:
            try:
                bus.send(topic, data)
            except Exception as e:  # noqa: BLE001 — never let the bus kill tracking
                print(f"WARN: publish failed ({e}); continuing")

    # ------------------------------------------------------------- model
    landmarker = build_landmarker(args.hands)

    rec = None
    if args.record:
        rec = open(args.record, "a", encoding="utf-8")

    # ------------------------------------------------------------ bench
    if args.bench:
        img = cv2.imread(
            args.source
            if not args.source.isdigit()
            else str(_HERE / "fixtures" / "hand_open.jpg")
        )
        if img is None:
            sys.exit(f"error: bench image not found: {args.source}")
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        lat: list[float] = []
        for i in range(args.bench):
            mp_img = mp.Image(mp.ImageFormat.SRGB, np.ascontiguousarray(rgb))
            t0 = time.perf_counter()
            landmarker.detect_for_video(mp_img, i + 1)  # ms, strictly increasing
            lat.append(time.perf_counter() - t0)
        lat_ms = np.array(lat) * 1000
        print(
            json.dumps(
                {
                    "bench_frames": args.bench,
                    "fps_mean": round(1000.0 / lat_ms.mean(), 1),
                    "latency_ms_p50": round(float(np.percentile(lat_ms, 50)), 1),
                    "latency_ms_p95": round(float(np.percentile(lat_ms, 95)), 1),
                    "resolution": [img.shape[1], img.shape[0]],
                }
            )
        )
        landmarker.close()
        return

    # ------------------------------------------------------------- loop
    cap, is_cam, still = open_capture(args.source, args.width, args.height)
    if is_cam and cap is not None:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    dims = (
        (still.shape[1], still.shape[0])  # (w, h) — shape is (h, w, c)
        if still is not None
        else (
            int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        )
    )
    print(
        f"capture: {args.source} {dims[0]}x{dims[1]}"
        + (" (still-image fixture mode)" if still is not None else ""),
        flush=True,
    )

    filt = {}  # handedness → Vec3Filter (OneEuro per axis)
    last_hands_t = 0.0
    last_frame_t = 0.0
    last_hb_t = 0.0  # console heartbeat (stdout may be redirected)
    fps = 0.0
    frame_count = 0
    t_prev = time.perf_counter()
    img_ts_ms = int(time.monotonic_ns() // 1_000_000)

    try:
        while True:
            if still is not None:
                frame = still.copy()  # fixture mode: same frame, fresh ts
            else:
                ok, frame = cap.read()
                if not ok:  # EOF on a video file → restart it
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ok, frame = cap.read()
                    if not ok:
                        if is_cam:
                            print("WARN: camera read failed; retrying", flush=True)
                            time.sleep(0.2)
                            continue
                        time.sleep(0.05)
                        continue

            now = time.perf_counter()
            dt = max(1e-3, now - t_prev)
            fps = 0.9 * fps + 0.1 * (1.0 / dt) if frame_count > 5 else 1.0 / dt
            t_prev = now
            frame_count += 1

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img_ts_ms += max(1, int(dt * 1000))  # strictly increasing
            mp_img = mp.Image(mp.ImageFormat.SRGB, np.ascontiguousarray(rgb))
            t0 = time.perf_counter()
            res = landmarker.detect_for_video(mp_img, img_ts_ms)
            infer_ms = (time.perf_counter() - t0) * 1000

            hands_payload = []
            ee_targets: list[np.ndarray] = []
            for i, wl in enumerate(res.hand_world_landmarks):
                handed = (
                    res.handedness[i][0].category_name
                    if i < len(res.handedness)
                    else "Right"
                )
                # one OneEuro chain per handedness keeps Left/Right independent
                f = filt.setdefault(handed, R.Vec3Filter(args.mincutoff, args.beta))
                ee = R.landmarks_to_ee(wl, handed, args.scale, args.offset)
                ee = R.clamp_to_workspace(ee)
                ee = f(ee, dt)
                ee_targets.append(ee)
                pinch = R.pinch_score(wl)
                fist = R.fist_score(wl)
                entry = {
                    "handedness": handed,
                    "world": [[float(l.x), float(l.y), float(l.z)] for l in wl],
                    "img": [
                        [float(l.x), float(l.y), float(l.z)]
                        for l in res.hand_landmarks[i]
                    ],
                    "pinch": round(pinch, 3),
                    "fist": round(fist, 3),
                    "ee_target": [round(float(v), 4) for v in ee],
                }
                hands_payload.append(entry)
                if rec is not None:
                    rec.write(
                        json.dumps(
                            {
                                "t": time.time(),
                                "handedness": handed,
                                "world": hands_payload[-1]["world"],
                                "img": hands_payload[-1]["img"],
                                "pinch": pinch,
                                "fist": fist,
                                "ee": hands_payload[-1]["ee_target"],
                            }
                        )
                        + "\n"
                    )

            # vision.hands — high-rate but capped at --hands-hz
            if now - last_hands_t >= 1.0 / args.hands_hz:
                last_hands_t = now
                publish(
                    "vision.hands",
                    {
                        "hands": hands_payload,
                        "fps": round(fps, 1),
                        "t": time.time(),
                        "infer_ms": round(infer_ms, 1),
                    },
                )

            # vision.frame — ≤ frame-hz, JPEG downscaled
            if now - last_frame_t >= 1.0 / args.frame_hz:
                last_frame_t = now
                vis = annotate(frame.copy(), res, ee_targets)
                if args.show:
                    cv2.imshow("hand_tracker", vis)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
                scale = min(1.0, args.jpeg_w / vis.shape[1])
                if scale < 1.0:
                    vis = cv2.resize(
                        vis, (int(vis.shape[1] * scale), int(vis.shape[0] * scale))
                    )
                okj, buf = cv2.imencode(".jpg", vis, [cv2.IMWRITE_JPEG_QUALITY, 65])
                if okj:
                    import base64

                    publish(
                        "vision.frame",
                        {
                            "from": "hands",
                            "jpeg_b64": base64.b64encode(buf.tobytes()).decode(),
                            "w": vis.shape[1],
                            "h": vis.shape[0],
                        },
                    )

            if now - last_hb_t >= 5.0:  # heartbeat: prove liveness when piped
                last_hb_t = now
                print(
                    f"[hb] {frame_count} frames {fps:.1f} fps "
                    f"infer {infer_ms:.1f} ms hands={len(hands_payload)}",
                    flush=True,
                )
    except KeyboardInterrupt:
        pass
    finally:
        print(f"\n{frame_count} frames, avg {fps:.1f} fps")
        if rec is not None:
            rec.close()
        if args.show:
            cv2.destroyAllWindows()
        landmarker.close()
        if bus is not None:
            bus.close()


if __name__ == "__main__":
    main()
