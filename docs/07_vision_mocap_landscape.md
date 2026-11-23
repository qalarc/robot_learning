# 07 — Vision mocap landscape: RGB cameras → SO-101 teleoperation

*Researched 2026-11-24 for the Alloy × OpenAI Physical AI Hackathon. Target machine: Linux (CachyOS/Arch), AMD iGPU, no NVIDIA/CUDA, Python 3.12 venvs, CPU-only inference preferred.*

**Verification method.** Every repo below was checked live on 2026-11-24 (GitHub existence + licence metadata via the GitHub API, or raw `README`/`LICENSE` fetches). Official docs were fetched from ai.google.dev, huggingface.co and freemocap.org. `docs.opencv.org` blocked our fetcher (403), so OpenCV claims are verified against the tutorial *sources* in the opencv/opencv GitHub repos instead. Anything I could not confirm from a primary source is marked **[unverified]**. Licences are quoted as found in each repo's `LICENSE`/API metadata on that date.

---

## 1. MediaPipe in late 2026

Google's current offering is the **MediaPipe Tasks API** — "22 on-device tasks across five categories", of which **11 are vision tasks** (https://developers.google.com/edge/mediapipe/solutions). Bindings: **Web/JS (`@mediapipe/tasks-vision`), Android (Kotlin/Java), iOS (SwiftPM), Python (`pip install mediapipe`), Flutter**, plus the raw C++ "MediaPipe Framework" for custom graphs. All tasks run with **CPU or GPU** delegates, on-device ([solutions overview](https://developers.google.com/edge/mediapipe/solutions)).

Vision tasks relevant to us ([task list](https://developers.google.com/edge/mediapipe/solutions#tasks)):

| Task | Output |
|---|---|
| **Hand Landmarker** | 21 3D landmarks/hand + handedness |
| **Gesture Recognizer** | landmarks + canned gestures (`None, Closed_Fist, Open_Palm, Pointing_Up, Thumb_Down, Thumb_Up, Victory, ILoveYou`) + custom gesture heads |
| **Pose Landmarker** | 33 full-body 3D landmarks (lite/full/heavy models), optional segmentation mask |
| **Holistic Landmarker** | face + hand + body pose combined in one pipeline |
| **Face Landmarker** | 478 3D points + 52 blendshapes |

**Landmark semantics** (from the official task pages — this is the part that matters for retargeting):

- **Hand landmarks** are `NormalizedLandmark`s, `x,y ∈ [0,1]` normalised by image width/height; **`z` is depth with the wrist (landmark 0) as origin**. Landmark names: 0 `WRIST`, 1–4 thumb (CMC/MCP/IP/TIP), 5–8 index (MCP/PIP/DIP/TIP), 9–12 middle, 13–16 ring, 17–20 pinky ([Hand Landmarker page](https://ai.google.dev/edge/mediapipe/solutions/vision/hand_landmarker)).
- **Hand *world* landmarks** are "in real-world **meters**, with the origin at the hand's **geometric center**" — i.e. roughly metric but *hand-local*, not in your camera/world frame ([Hand Landmarker page](https://ai.google.dev/edge/mediapipe/solutions/vision/hand_landmarker)).
- **Pose landmarks** likewise: normalised image coords, and **world landmarks in meters with the midpoint of the hips as origin**; 33 joints include shoulders (11/12), elbows (13/14), wrists (15/16) ([Pose Landmarker page](https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker)).
- **Handedness** refers to the *subject's* hands — "passing a horizontally mirrored image will invert these outputs" (same pages). Feed a mirrored preview and labels flip.
- In `VIDEO`/`LIVE_STREAM` mode, palm detection only re-runs when tracking fails; otherwise a light tracker follows the previous frame's box (docs, Hand/Gesture pages).

**Performance (official benchmarks, Pixel 6):** HandLandmarker full **17.12 ms CPU / 12.27 ms GPU**; GestureRecognizer **16.76 ms CPU** ([task pages](https://ai.google.dev/edge/mediapipe/solutions/vision/hand_landmarker)). A desktop x86 CPU is typically faster than a Pixel 6, so ~30–60 FPS end-to-end for hands+camera is realistic, but **no official desktop-CPU FPS number is published** — measure it on our machine **[unverified for our hardware]**.

**Legacy "Solutions" API:** the current Google docs only describe the Tasks API; the old `mp.solutions.*` family is no longer documented there. Google's deprecation date for legacy solutions (March 1, 2023) could not be re-confirmed from a live page on 2026-11-24 **[unverified]**. Practical takeaway: our existing Tasks-API code is on the supported path; `mp.solutions` still works in older wheels but is the past.

**Known limitations** (docs-adjacent, honest): no absolute camera-frame position in meters (only hand/hip-relative world coords); `z` is model-estimated and noisy — depth ambiguity is severe for a single camera; landmark jitter of a few pixels at 30 fps; single-hand orientation degrades when the hand is edge-on to the camera; performance drops when hands occlude each other or the face.

## 2. Mocap alternatives on CPU/Linux/AMD

| Tool | Body / hands | Metric 3D? | Runtime on our box | Licence (verified) | Arch install | Verdict for hackathon |
|---|---|---|---|---|---|---|
| MediaPipe Hands/Pose/Holistic (Tasks) | both | no (relative only) | real-time, CPU-friendly | Apache-2.0 | trivial (pip wheel) | **primary choice** |
| RTMPose / RTMW (MMPose) | body 2D; RTMW = 133-pt wholebody 2D; RTMW3D = real-time 3D wholebody | RTMW3D: camera-space 3D | GPU-normal; CPU possible but slow [unverified] | Apache-2.0 | easy pip (mmpose) — heavier deps | fallback for wholebody 2D |
| ViTPose | body 2D/3D | ViTPose3D: camera-space | needs GPU in practice | Apache-2.0 | easy pip, torch CPU slow | skip |
| Sapiens (Meta) | body: pose/depth/seg/normal | depth in meters (relative depth task) | 0.3–2B models, GPU expected | **CC-BY-NC 4.0** (`LICENSE`) | heavy | skip (licence + GPU) |
| 4D Humans / HMR 2.0 | body SMPL mesh + track videos | SMPL camera-space | torch; needs registered SMPL model files; GPU expected | MIT | medium (SMPL registration) | offline demo-video mesh only |
| WHAM | body+hands, world-grounded motion from video | yes (world frame w/ gravity) | torch GPU expected | MIT (verified `LICENSE`) | medium | offline ego→motion experiments |
| NLF (isarandi/nlf) | body 3D pose+shape, continuous | camera-space 3D | designed light; "models for PyTorch and TensorFlow … noncommercial research use" (README) | code MIT, **models non-commercial** | easy | CPU 3D-body fallback |
| HaMeR (hand mesh) | hands (MANO mesh) | MANO camera-space | GPU expected | **repo not found**: `github.com/gonometa/hamer` and `github.com/gvblab/hamer` both 404 on 2026-11-24; project page unreachable from this network → **could not verify** | — | not found |
| FrankMocap (Meta) | body+hands | camera-space | GPU expected; **repo archived 2022-11** | CC-BY-NC 4.0 | dated deps | skip |
| EasyMocap (zju3dv) | multi-view body/hand | yes (multi-view) | offline, multi-camera | custom "Project Registration License v1.0" | medium | multi-cam fallback only |
| FreeMoCap | body+hands via multi-cam triangulation | **yes** (multi-cam ChArUco-calibrated world) | "designed to run on CPU" (site); README offers `pip install freemocap[cpu]` | **AGPL-3.0** | easy-ish (`uv`/pip) | offline "real mocap" wow-factor; AGPL is fine for us (we're not shipping closed source) |
| OpenPose | 135 keypoints body/hands/face | 2D; 3D needs multi-cam | CPU-only builds exist; slow on CPU | **academic non-commercial** (`LICENSE`) | hard build | skip |
| Vision Pro / Quest hand tracking | hands, world-tracked | yes (headset frame) | external device | proprietary SDKs | needs hardware | only if a team member owns one; Bunny/DexCap-style pipelines prove the path |

Sources: [freemocap/freemocap](https://github.com/freemocap/freemocap) + [freemocap.org](https://www.freemocap.org/) ("two or more standard webcams… wave a printed ChArUco board… designed to run on CPU"), [mmpose](https://github.com/open-mmlab/mmpose) (RTMPose/RTMW/RTMW3D), [ViTPose](https://github.com/ViTAE-Transformer/ViTPose), [sapiens](https://github.com/facebookresearch/sapiens), [4D-Humans](https://github.com/shubham-goel/4D-Humans), [WHAM](https://github.com/yohanshin/WHAM) (arXiv 2312.07531), [nlf](https://github.com/isarandi/nlf) (NeurIPS'24, arXiv 2407.07532), [frankmocap](https://github.com/facebookresearch/frankmocap), [EasyMocap](https://github.com/zju3dv/EasyMocap), [openpose](https://github.com/CMU-Perceptual-Computing-Lab/openpose).

## 3. RGB → robot teleoperation & demo capture (verified projects)

| Project | Input → output | Hardware | Licence | Reusable by us |
|---|---|---|---|---|
| **LeRobot** ([huggingface/lerobot](https://github.com/huggingface/lerobot)) | leader-arm/keyboard/gamepad/phone → SO-101 actions; policies in/out | SO-101, Feetech bus | Apache-2.0 | **everything**: SO-101 driver, dataset format, `lerobot-train`, `lerobot-eval` (LIBERO/MetaWorld); docs pages `/so101`, `/teleoperate`, `/sim`, `/mujoco` all exist (checked 2026-11-24) |
| **Open-TeleVision** ([OpenTeleVision/TeleVision](https://github.com/OpenTeleVision/TeleVision)) | headset + stereo cams → bimanual teleop with immersive feedback | Vision Pro/Quest + 2 cams | Apache-2.0 (LICENSE) | retargeting ideas; CoRL 2024, arXiv 2407.01512 |
| **Bunny-VisionPro** ([Dingry/BunnyVisionPro](https://github.com/Dingry/BunnyVisionPro)) | AVP hand tracking → dexterous bimanual arms via `dex-retargeting` | Vision Pro + arms | MIT | its retargeting tutorial + `bunny_teleop_server`; built on Improbable-AI/VisionProTeleop (arXiv 2407.03162) |
| **DexCap** ([j96w/DexCap](https://github.com/j96w/DexCap)) | AVP hand capture + SLAM → dexterous hand demos | Vision Pro | MIT | SLAM drift-correction UX pattern |
| **UMI** ([real-stanford/universal_manipulation_interface](https://github.com/real-stanford/universal_manipulation_interface)) | handheld gripper + GoPro → ORB-SLAM3 trajectory → diffusion policy | GoPro + 3D-printed gripper | MIT | proves "RGB+SLAM → policy" end-to-end; SLAM pipeline is a reference |
| **ALOHA / Mobile ALOHA** ([tonyzhaozh/aloha](https://github.com/tonyzhaozh/aloha), [MarkFzp/mobile-aloha](https://github.com/MarkFzp/mobile-aloha)) | leader arms → follower arms, joint-space imitation | 2×2 ViperX/SO-class arms | MIT | the joint-space BC recipe (AGGREGATED dataset → ACT) |
| **EgoMimic** ([SimarKareer/EgoMimic](https://github.com/SimarKareer/EgoMimic)) | Aria glasses human video + robot video → joint policy | Aria + A1 arm | MIT | egocentric data-processing conventions |
| **AirExo-2** ([AirExo/AirExo-2](https://github.com/AirExo/AirExo-2); v1 base [AirExo/collector](https://github.com/AirExo/collector)) | low-cost exoskeleton → demos from in-the-wild video | exoskeleton | **CC-BY-NC-SA 4.0** (collector part MIT) | exoskeleton-as-teleop concept only |
| **HOMIE / OpenHomie** ([Sage-PhysicalAI/OpenHomie](https://github.com/Sage-PhysicalAI/OpenHomie)) | isomorphic exoskeleton cockpit → humanoid loco-manipulation | exoskeleton + humanoid | **CC-BY-NC-SA 4.0**; requires NVIDIA GPU (README) | not runnable here; citation material |
| **EgoDex** ([apple-aiml-research/ml-egodex](https://github.com/apple-aiml-research/ml-egodex)) | AVP/ARKit egocentric video + 3D hand/body pose + language, 829 h @ 30 Hz | Apple Vision Pro | code: custom `LICENSE`; **dataset CC-BY-NC-ND** (README, arXiv 2505.11709) | free labeled ego-manipulation data for offline analysis |
| **dex-retargeting** ([dexsuite/dex-retargeting](https://github.com/dexsuite/dex-retargeting)) | "retargeting optimizers to translate human hand motion to robot hand motion" (README) | any (Python) | MIT | direct dependency if we ever drive a dexterous hand; SO-101 gripper doesn't need it |
| **PHC** ([ZhengyiLuo/PHC](https://github.com/ZhengyiLuo/PHC)) | human motion → humanoid tracking controller | sim/GPU | BSD-3-Clause-Clear (LICENSE) | humanoid transfer, out of scope for SO-101 |
| **SAM 3D Body** ([facebookresearch/sam-3d-body](https://github.com/facebookresearch/sam-3d-body)) | image → 3D body mesh | GPU expected | "SAM License" (custom) | demo-video meshing garnish |
| **AnyTeleop** | original `dyanikoglu/AnyTeleop` returns **404** today; forks exist: [RalphFH/AnyTeleop](https://github.com/RalphFH/AnyTeleop) (MIT), [makolon/lerobot_anyteleop](https://github.com/makolon/lerobot_anyteleop) (Apache-2.0) | Quest + Isaac | MIT (fork) | Quest-path reference only |

**Could NOT verify from your list** (see final section): HaMeR, "RGB-Is-All-You-Need", "versatile-retargeting"/VRT, "H2R", "Ego-Allo" (paper), HandVLA (paper).

## 4. Retargeting maths (21 landmarks → SO-101)

SO-101 is effectively **5 joints + parallel gripper** (pan, shoulder-lift, elbow, wrist-pitch, wrist-roll, gripper) per the [LeRobot SO-101 docs](https://huggingface.co/docs/lerobot/so101). Mapping:

1. **End-effector position**: wrist landmark 0 (or midpoint of 0 and 9). Take **hand world landmarks** (meters, hand-centre origin) and add the wrist position estimated from **Pose world landmarks** (hip-origin meters) when the whole arm is visible — the two frames must be stitched by a single per-user offset, calibrated by touching three known points on the table **[our own calibration procedure — design, not sourced]**.
2. **Gripper aperture**: distance `‖p_thumb_tip(4) − p_index_tip(8)‖` in world landmarks, normalised by hand span (distance 5→17, MCP line) to cancel hand size; map pinch-close→gripper-close, fist (GestureRecognizer `Closed_Fist`) → hard close. Landmark indices/names per the official table (§1).
3. **Orientation**: palm direction = vector 0(wrist)→9(middle MCP); palm normal from (5−0)×(17−0). Use pan for azimuth of the palm direction, wrist-pitch from elevation, wrist-roll from palm normal roll. Only one rotation DOF pair is truly observable from a single camera — accept 5-DOF teleop, don't fake 6.
4. **Scale calibration**: retarget in *ratios*: target = workspace centre + (landmark offset / arm-length proxy) × arm-reach. Arm-reach proxy = shoulder(11/12)→wrist(15/16) distance in pose world landmarks at calibration time.
5. **Workspace clamping**: clamp the IK target to the frozen box in `control/robot_ops.schema.json` (x 0.05–0.30, y ±0.18, z 0.02–0.25 m) *outside* any model, per repo rules of engagement.
6. **Smoothing — One-Euro filter** (Casiez, Roussel, Vogel, CHI 2012, [paper](https://dl.acm.org/doi/10.1145/2207676.2208639), [homepage](https://gery.casiez.net/1euro/)): adaptive low-pass — low cutoff kills jitter when slow, speed-proportional term (`beta`) cuts lag when fast. Official tuning recipe (quoted from the homepage): start `fcmin` ≈ 1 Hz with `beta=0`, tune jitter/lag at low speed; then raise `beta` starting from ~0.001 while moving fast. Use the author-verified Python implementation ([casiez/OneEuroFilter](https://github.com/casiez/OneEuroFilter), Python version BSD — per homepage list). Run one filter per coordinate axis; the same filter ships in Chrome and Vicon, so it's the industry default for exactly this problem.
7. **Handedness mirroring**: docs state handedness flips on mirrored images (§1). Decide one camera orientation, verify labels by posing, and mirror the target's y-axis so a *right* hand drives a right-side-mounted arm naturally.
8. **Temporal alignment**: stamp every frame with the camera's monotonic timestamp, run `detect_for_video` in VIDEO mode (docs), and resample the retargeted joint stream to the control loop rate (30 Hz camera → 50 Hz control via last-value hold; RIFE interpolation only for pretty offline videos, never online).

## 5. Colour/HSV tracking & markers today

- **HSV pipeline** (verified against OpenCV's own tutorial source: `cv.cvtColor`, `cv.inRange`, "hue range is [0,179]" — [py_colorspaces.markdown](https://github.com/opencv/opencv/blob/4.x/doc/py_tutorials/py_imgproc/py_colorspaces/py_colorspaces.markdown), rendered at [docs.opencv.org colorspaces](https://docs.opencv.org/4.x/df/d9d/tutorial_py_colorspaces.html)):

```python
import cv2 as cv, numpy as np
lo, hi = np.array([100, 120, 80]), np.array([130, 255, 255])   # blue-tape example
hsv   = cv.cvtColor(frame, cv.COLOR_BGR2HSV)
mask  = cv.inRange(hsv, lo, hi)
mask  = cv.morphologyEx(mask, cv.MORPH_OPEN,  np.ones((5, 5), np.uint8))
mask  = cv.morphologyEx(mask, cv.MORPH_CLOSE, np.ones((9, 9), np.uint8))
cnts, _ = cv.findContours(mask, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
if cnts:
    c   = max(cnts, key=cv.contourArea)
    M   = cv.moments(c)
    cx, cy = int(M["m10"]/M["m00"]), int(M["m01"]/M["m00"])   # centroid = target pixel
```

  CamShift/meanshift and `cv2.SimpleBlobDetector` remain in OpenCV 4.x for blob/region tracking (meanshift tutorial family exists; content moved to `tutorial_meanshift` per its source).
- **Detectors**: Ultralytics YOLO ([ultralytics/ultralytics](https://github.com/ultralytics/ultralytics)) is **AGPL-3.0** — fine internally, contagious if distributed. **SAM 2** ([facebookresearch/sam2](https://github.com/facebookresearch/sam2), Apache-2.0) does promptable video masks; **SAM 3** ([facebookresearch/sam3](https://github.com/facebookresearch/sam3), "Segment Anything with Concepts", custom SAM License, Nov 2025) — both GPU-first, poor fit for our iGPU box on the day.
- **Markers give metric 6-DoF from one camera** — the point HSV can never give: **ArUco** (OpenCV contrib) and **AprilTag** ([AprilRobotics/apriltag](https://github.com/AprilRobotics/apriltag), BSD-2-Clause) return full pose once camera intrinsics are calibrated. docs.opencv.org blocked our fetcher, so treat the snippet's API names as "verify against your build" [tutorial: https://docs.opencv.org/4.x/d5/dae/tutorial_aruco_detection.html]:

```python
det = cv.aruco.ArucoDetector(cv.aruco.getPredefinedDictionary(cv.aruco.DICT_4X4_50))
corners, ids, _ = det.detectMarkers(gray)
if ids is not None:
    rvecs, tvecs, _ = cv.aruco.estimatePoseSingleMarkers(corners, 0.05, K, dist)  # 5 cm marker
    # tvecs = metric position of the marker centre in the camera frame
```

  Use an ArUco patch on the gripper or object for ground-truth-ish localisation; use HSV only as the cheap fallback when lighting is controlled.

## 6. Video-editing CV, reused for demo processing

- **Shot detection**: [PySceneDetect](https://github.com/Breakthrough/PySceneDetect) (BSD-3-Clause) segments long demo recordings into episodes; ffmpeg's `scdet` filter does it without Python.
- **Optical flow**: OpenCV DIS/Farneback (`cv.DISOpticalFlow_create`, `cv.calcOpticalFlowFarneback`) — motion energy per frame is a free "was anything happening" label for trimming static spans.
- **Frame interpolation**: [Practical-RIFE](https://github.com/hzwer/Practical-RIFE) (MIT) and FILM ([google-research/frame-interpolation](https://github.com/google-research/frame-interpolation), Apache-2.0, **repo archived 2024-08**) resample 15 fps phone demos to 30–50 fps offline; GPU-class models, run sparingly on CPU.
- **Word timing**: [Whisper](https://github.com/openai/whisper) (MIT) transcribes your narration with segment timestamps — use spoken words as language-conditioned task labels in the dataset.
- **Video segmentation**: SAM 2 video predictor for object masks in recorded demos (Apache-2.0).

## 7. Recommended stack for the 1-day hackathon

**Camera → landmarks → retarget → sim → policy**, all CPU, all pre-verified licences:

1. **Capture**: USB webcam @ 30 fps → **MediaPipe Hand Landmarker + Pose Landmarker** (Tasks API, Python, VIDEO running mode). Apache-2.0, pip wheel, no GPU needed. Pixel-6 CPU latency 17 ms says a laptop CPU keeps 30 fps.
2. **Smooth + retarget**: One-Euro filter per axis ([casiez/OneEuroFilter](https://github.com/casiez/OneEuroFilter), BSD) → pinch-aperture gripper + 5-DOF IK target from §4 → clamp to the schema box → simple analytic IK (2-link planar for lift/elbow, pan/yaw, wrist-pitch/roll from palm vectors).
3. **Sim**: MuJoCo ([google-deepmind/mujoco](https://github.com/google-deepmind/mujoco), Apache-2.0, pip, CPU) with an SO-101 XML; LeRobot's `/sim` and `/mujoco` doc pages exist (checked) — reuse if they ship the model, else hand-write the XML.
4. **Record + train**: LeRobot dataset format from the teleop stream (Apache-2.0) → `lerobot-train` ACT/SmolVLA in `training/.venv` → eval; export MCAP for Alloy.
5. **Fallbacks**: ArUco patch on gripper for metric truth; HSV tape tracker if MediaPipe lighting fails; FreeMoCap (AGPL, CPU) if judges want to see "real mocap".

## 8. Pitfalls

1. **Scale**: hand world landmarks are metres *from the hand's own centre* (docs) — never feed them to the arm raw; calibrate ratio-style (§4.4) or you'll command 10× the workspace.
2. **Depth ambiguity / z-noise**: single-camera `z` is model-prior, not measurement; expect ±cm errors and occlusion flips — clamp z hardest, prefer table-plane-constrained tasks.
3. **Latency stack**: camera (33 ms) + inference (~20 ms) + smoothing + bus ≈ 100–150 ms; the One-Euro beta term and the frozen workspace clamp are the safety margin — never let the model output near limits.
4. **Occlusion & lighting**: hand-behind-object kills landmarks (tracker re-seeds); HSV dies with white balance/shadows; always have the ArUco/HSV fallback and keep a desk lamp.
5. **Rolling shutter**: fast hand sweeps skew landmarks per-frame; slow the operator down and downweight high-speed commands (One-Euro does this implicitly at low `beta`).
6. **Handedness/mirroring**: labels flip on mirrored images (docs note) — fix one camera orientation and test before demoing.
7. **Workspace mismatch**: human reach ≫ SO-101 reach; teleop feels "truncated" — scale gain ≈ 0.4 and tell the operator.
8. **Licence traps**: FreeMoCap & Ultralytics are AGPL-3.0; OpenPose/Sapiens/FrankMocap/AirExo-2/HOMIE/EgoDex-data are non-commercial — fine for a hackathon demo, wrong to ship.

## 9. Source index (primary)

MediaPipe: [solutions](https://developers.google.com/edge/mediapipe/solutions) · [hand](https://ai.google.dev/edge/mediapipe/solutions/vision/hand_landmarker) · [pose](https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker) · [gesture](https://ai.google.dev/edge/mediapipe/solutions/vision/gesture_recognizer) · [MediaPipe Hands paper, arXiv 2006.10214](https://arxiv.org/abs/2006.10214) · [google-ai-edge/mediapipe](https://github.com/google-ai-edge/mediapipe).
One-Euro: [paper](https://dl.acm.org/doi/10.1145/2207676.2208639) · [homepage](https://gery.casiez.net/1euro/) · [casiez/OneEuroFilter](https://github.com/casiez/OneEuroFilter).
OpenCV: [colorspaces tutorial source](https://github.com/opencv/opencv/blob/4.x/doc/py_tutorials/py_imgproc/py_colorspaces/py_colorspaces.markdown) · [ArUco tutorial](https://docs.opencv.org/4.x/d5/dae/tutorial_aruco_detection.html) · [AprilRobotics/apriltag](https://github.com/AprilRobotics/apriltag).
Teleop: [lerobot](https://github.com/huggingface/lerobot) · [TeleVision](https://github.com/OpenTeleVision/TeleVision) · [BunnyVisionPro](https://github.com/Dingry/BunnyVisionPro) · [DexCap](https://github.com/j96w/DexCap) · [UMI](https://github.com/real-stanford/universal_manipulation_interface) · [aloha](https://github.com/tonyzhaozh/aloha) · [mobile-aloha](https://github.com/MarkFzp/mobile-aloha) · [EgoMimic](https://github.com/SimarKareer/EgoMimic) · [AirExo-2](https://github.com/AirExo/AirExo-2) · [OpenHomie](https://github.com/Sage-PhysicalAI/OpenHomie) · [ml-egodex](https://github.com/apple-aiml-research/ml-egodex) · [dex-retargeting](https://github.com/dexsuite/dex-retargeting) · [PHC](https://github.com/ZhengyiLuo/PHC) · [sam-3d-body](https://github.com/facebookresearch/sam-3d-body).
Mocap: [mmpose](https://github.com/open-mmlab/mmpose) · [ViTPose](https://github.com/ViTAE-Transformer/ViTPose) · [sapiens](https://github.com/facebookresearch/sapiens) · [4D-Humans](https://github.com/shubham-goel/4D-Humans) · [WHAM](https://github.com/yohanshin/WHAM) · [nlf](https://github.com/isarandi/nlf) · [frankmocap](https://github.com/facebookresearch/frankmocap) · [EasyMocap](https://github.com/zju3dv/EasyMocap) · [freemocap](https://github.com/freemocap/freemocap) / [freemocap.org](https://www.freemocap.org/) · [openpose](https://github.com/CMU-Perceptual-Computing-Lab/openpose).
Video: [PySceneDetect](https://github.com/Breakthrough/PySceneDetect) · [Practical-RIFE](https://github.com/hzwer/Practical-RIFE) · [FILM](https://github.com/google-research/frame-interpolation) · [whisper](https://github.com/openai/whisper) · [sam2](https://github.com/facebookresearch/sam2) · [sam3](https://github.com/facebookresearch/sam3) · [ultralytics](https://github.com/ultralytics/ultralytics) · [mujoco](https://github.com/google-deepmind/mujoco).
