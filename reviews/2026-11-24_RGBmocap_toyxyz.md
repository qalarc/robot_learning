# RGB MoCap (toyxyz/toyxyz_RGBMocap) — full review

**Date:** 2026-11-24 · **Reviewer context:** robotics hackathon — RGB-camera human motion capture for SO-101-style arm teleoperation + demonstration capture (LeRobot ACT / Diffusion Policy), plus gamedev reuse.
**Verdict:** **Excellent offline mocap app for a CUDA/NVIDIA machine; NOT usable as-is on our Linux + AMD iGPU hardware; not suitable for live robot teleop; genuinely strong for post-hoc human demonstration capture (video → retargeted humanoid motion → offline parsing).**

> **Repo name correction:** `github.com/toyxyz/RGBmocap` **404s**. The actual repository is
> **`toyxyz/toyxyz_RGBMocap`** — https://github.com/toyxyz/toyxyz_RGBMocap (confirmed 2026-11-24 via GitHub API; "RGBmocap" under that owner does not exist).

---

## 1. What it is

RGB MoCap is a **native Windows desktop GUI application** (PySide6/Qt + Python) that turns **monocular or multi-view RGB video** into editable human animation, with all AI inference running locally. It is **not** a VR/hardware-tracking product and not a SteamVR/OpenVR driver — there is no HMD, tracker, or headset involvement anywhere in the docs. It is also **not** a lightweight keypoint SDK: it is an orchestration app around several published human-mesh-recovery research models, adding detection/tracking, contact correction, retargeting and export.

Per the README: "A native Windows app that turns video into editable human animation. Review and export motion with AI processing running locally." [README, §Install and run / Features — https://github.com/toyxyz/toyxyz_RGBMocap#readme]

**Wraps these research models** (all third-party; weights downloaded separately via its "Model Manager", some gated behind registration — e.g. SMPL-X/FLAME geometry must be registered from the providers) [README §Supported AI models; docs/models/PEAR.md]:

| Model | Upstream | Body representation | Fingers | Notes |
|---|---|---|---|---|
| ExMR | github.com/twehrbein/ExMR | SMPL-X | Included | Highest quality in author's tests |
| FlowHMR | github.com/flowhmr/flowhmr | SMPL-H | Included | Fast; 4-frame hand sampling + optional HaMeR refine |
| GVHMR | github.com/zju3dv/GVHMR | SMPL-X | Optional HandFlow add-on | World-grounded, gravity-aware |
| MAMMA | mamma.is.tue.mpg.de | SMPL-X | Included | **Multi-view** (synchronized camera videos) |
| PromptHMR | github.com/yufu-wang/PromptHMR | SMPL-X | **Not generated** | Multi-person placement; lower motion quality |
| GEM-X | github.com/NVlabs/GEM-X | SOMA Native77 | Included | Fast, "relatively low motion quality in our tests" |
| PEAR | github.com/Pixel-Talk/PEAR | SMPL-X / FLAME | Included | **Only live/real-time path; experimental, preview-only** |

The concrete weight stack (confirmed from the community ROCm port's verified manifest, which mirrors `mocap/models.py`): YOLOv8x detection, SAM-3D-body/DINOv3 segmentation (FlowHMR), VGGT-Omega-1B + GeoCalib camera estimation, ViTPose-H keypoints, GVHMR/ExMR/FlowHMR checkpoints, Sapiens-2 1B pose, SMPL-H/SMPL-X body models [https://github.com/herman6888/rgbmocap-rocm-port (README weight table)].

**Camera setups:** webcam or arbitrary video files (third-person views of a person); PEAR supports 1–32 webcam slots with ~80 ms software sync skew limit; MAMMA ingests **synchronized multi-camera videos** with automatic calibration (VGGT-Omega + GeoCalib) or imported calibration, using an approximate **Reference Height (m)** for scale. **No egocentric/chest- or head-mounted mode is documented** [README; docs/models/PEAR.md]. Tested inputs include 720×1280 and 1080×1920 @ 30 fps; lower-fps videos can be RIFE-interpolated to 30 fps [README §Features; PERFORMANCE.md].

## 2. Models output & runtime (the "ONNX?" answer)

- **Output:** SMPL-X / SMPL-H / SOMA body meshes + animation bones. The exported ExMR FBX contains **52 joints including 30 finger channels** (body+hands; face separate) — verified by the ROCm port's artifact inspection. Face is a separate "Track Face" feature exporting **ARKit-style blendshape coefficients** as TXT or Unreal Live Link Face CSV (CPU, offline) [README §Track Face; rgbmocap-rocm-port README].
- **Runtime: PyTorch + CUDA, no ONNX.** `requirements-windows.txt` pins the classic research stack (numpy 1.23.5, smplx 0.1.28, ultralytics 8.2.42, timm, lightning, hydra) and says "Install the official **cu128** torch wheels first". There is **no onnxruntime, TensorRT or OpenVINO anywhere** in the requirements; PERFORMANCE.md states optimizations need "**no extra packages, quantization, TensorRT engine or user compilation**". All pins are NVIDIA-only (`torch 2.14.0+cu128` per the ROCm port). **CPU-only inference is not offered by the app** and I found no CPU path in any doc — treat CPU viability as **not supported** by the app [requirements-windows.txt; docs/PERFORMANCE.md].
- **Reported performance (author's own measurements, RTX 5090 32 GB / Ryzen 9 9950X / 96 GB RAM — docs/PERFORMANCE.md, unusually honest and well-conditioned):**
  - Offline full pipeline, 60-frame (2 s @30 fps) clip incl. correction + export prep: **ExMR 89.0 s, FlowHMR 95.2 s, GVHMR+add-ons 127.5 s**; MAMMA 2-view/2-person/30-frame ≈ 241.6 s. So roughly **30–60× slower than realtime offline**, not streaming.
  - Peak PyTorch VRAM: ExMR 5.68 GiB → 3.87 (Low Memory), FlowHMR 6.10 → 2.77 GiB, GVHMR ~4.2 GiB, MAMMA 2.54 GiB; FlowHMR static-camera path ~5 GiB RAM, moving-camera VGGT ~12.8 GiB VRAM for 120 frames [PERFORMANCE.md; rocm-port README].
  - **Live (PEAR, experimental):** single-view worker **21.4 ms median / 23.8 ms p95** (~30 fps presented), four-view **39.6 ms median**; peak VRAM ~1.5 GiB; ~34 s model load; One Euro filtering "adds some motion-dependent lag". **Live mode cannot record, correct, retarget or export — preview only** [docs/models/PEAR.md §Placement and measured speed].

## 3. Integrations / outputs

- **File exports:** FBX and BVH (Generic/Blender or 3ds Max Biped), **VMD for MMD**, UE5 Manny/Quinn FBX; character FBX with/without meshes; portable Blender project bundles with video + cameras.
- **Retargeting built in:** to imported **Mixamo FBX, VRM and PMX** humanoids; separate companion add-on **toyxyz/toyxyz-blender-retargeter** (GPL-3.0, Blender 5.0+) for Blender-side retargeting.
- **Live streaming:** bones → **Blender** during playback (bundled add-on, bake to Actions); → **Unreal Live Link** via "RGB MoCap Connect" plugin (v0.5.0, UE 5.7.4 Win64; Manny/Quinn/MetaHuman + face). The plugin note says Live Link UDP Messaging is for trusted local networks, unencrypted.
- **No SteamVR/OpenVR driver, no VMC protocol, no OSC, and no generic UDP/JSON SDK are documented.** The only programmatic-ish live outputs are the Blender add-on and UE Live Link [README §Features; releases.atom].

## 4. Platforms, Linux, AMD — the critical question

- **Official support: 64-bit Windows + compatible NVIDIA GPU/driver + OpenGL 4.3.** [README]
- **Linux:** experimental, on a **`linux_support` branch** (separate from main): ~21 MiB AppImage + source install; covers **only single-video ExMR/FlowHMR/GVHMR + motion correction + export + Track Face**; PEAR/MAMMA/PromptHMR/GEM-X/SAM3.1/Unreal sender are Windows-only. Requirements: **"compatible NVIDIA driver for CUDA 12.8"**, OpenGL 4.3, FFmpeg, CMake 3.24+/C++17. Validated **on Ubuntu 24.04 under WSL 2 with WSLg + NVIDIA CUDA** (GVHMR inference + FBX/BVH export smoke-tested); a native Linux Mint report exists via issue #56 [linux_support docs/LINUX.md; releases/linux-appimage-0dc69476].
- **AMD iGPU / CPU (our CachyOS + Strix Halo case): NO.** The app is CUDA-pinned end to end (torch cu128 wheels, "CUDA Toolkit 12.8" native builds for optional models, CUDA checks in installers). There is **no CPU or ROCm path upstream**, and the headless question is partially answered by a community repo (`KoSukeWork/rgbmocap-remote` — "Windows validation tools for headless RGBMoCap pipelines and Blender output", created 2026-11-20), which still presumes a Windows machine doing the compute.
- **Community ROCm port exists but doesn't help an iGPU:** `herman6888/rgbmocap-rocm-port` runs the app on **Windows 11 + RX 9070XT (gfx1201) + ROCm 10.1.0** (torch 2.14.0+rocm10.1.0), patching the runtime pin + a lazy sitecustomize hook (SDPA forced to math backend, pure-torch NMS); GVHMR/ExMR/FlowHMR all produced valid FBX. **Verified on a discrete gfx1201 card on Windows only** — an AMD Strix Halo iGPU (gfx1151) is a different target and is [unverified]. It does prove the **inference code is fully open and patchable** (source + hash-verified manifest of PyTorch checkpoints, `sitecustomize.py` patching; nvdiffrast not needed — the app ships a pure-Python pytorch3d shim) [rocm-port README].

**Maturity & health:** created **2026-10-26**, last push **2026-11-22**; **3,103 stars, 419 forks, 41 watchers, 87 commits on main**; issues: **67 total, 40 open** (27 closed) with activity as recent as 2026-11-23; releases are frequent (4 releases in the 2 days before 2026-11-21: two Linux AppImage builds, MetaHuman Connect 0.4.0, RGB MoCap Connect 0.5.0). Documentation is exceptional — per-model guides, a candid PERFORMANCE.md with measured caveats, VALIDATION.md, AGENTS.md/AGENT_GUIDE.md ("Install with an AI agent" is an explicit supported workflow). Effectively one very active author; ~1 month old, so API/behaviour churn is likely. Install difficulty: **moderate-to-heavy** — ~77.8 GB for the six offline models+runtimes, gated weight downloads, Windows path-length and Smart App Control caveats documented [GitHub API; releases.atom; README].

**License:** original code + docs = **MIT** ("Copyright (c) 2026 RGB MoCap contributors"), with an explicit carve-out: third-party code, modifications, model weights and registered body models keep their own licences (SMPL-X/SMPL-H/FLAME/SOMA are gated, typically research/non-commercial — each model's terms must be checked in THIRD_PARTY_NOTICES.md before any commercial or dataset-sharing use) [LICENSE file; THIRD_PARTY_NOTICES.md referenced from README].

## 5. Use (a): robotics — SO-101 arm teleop + demonstration capture

**What it would give you:** 3D human upper-body + finger joint animation (SMPL-X-class, ≈52 joints) from a plain RGB camera, with foot/palm **contact correction**, per-person scale, and file exports. As **offline demonstration capture** (operator performs a task on video → parse FBX/BVH → retarget to the arm → pair with robot proprioception for ACT/Diffusion Policy) it is plausible and high-quality — but every step after the FBX is on you.

**What's missing, specifically:**

1. **No live, robot-rate output.** Live PEAR is preview-only (no record/export), and offline reconstruction is 30–60× realtime even on a 5090. There is **no OSC/VMC/UDP SDK**; the only live stream targets are Blender (add-on) and UE Live Link. For teleop you'd have to run reconstruction per-frame yourself against the upstream PyTorch models — a significant porting project, on hardware we don't have.
2. **No absolute metric guarantee / robot-frame calibration.** SMPL-X gives human-prior scale ("approximately metric"), and the docs themselves say for live alignment: "**Scale and floor are estimates, not calibrated measurements**"; MAMMA only takes an approximate Reference Height. A 6-DOF end-effector needs mm-level camera→robot-base extrinsics + verified scale — **not provided**.
3. **No robot retargeting.** Output is human joint animation; SMPL-X local joint frames ≠ SO-101 flange frame. A wrist-pose extraction + IK/limit-mapping layer (plus gripper derivation from finger span — unproven, and finger quality has documented caveats: 4-frame hand sampling shows 22.3 mm mean joint disagreement vs every-frame; optional HaMeR refine "may still produce jitter or inaccurate poses") must be built.
4. **Latency/smoothing:** live path's One Euro filter "adds some motion-dependent lag"; offline correction is post-hoc. Nothing is characterized for closed-loop control latency.
5. **Drift:** world placement is estimated per model (GVHMR is world-grounded; ExMR/FlowHMR get optional camera refinement), but no long-take drift characterization exists in the docs.
6. **Linux+AMD: no path.** Our capture host (CachyOS, AMD iGPU) cannot run it; you'd need a Windows/NVIDIA box (or WSL2+CUDA) for capture, then parse FBX/BVH back on Linux (bpy headless) — workable but clunky for a hackathon.
7. **Data-format friction:** FBX/BVH are fine to parse offline, but LeRobot wants aligned proprio+action at fixed Hz; you must write the SMPL-X→6-DOF-ee+gripper converter and time-align with the robot log yourself.

**Verdict (a):** strong as an **offline demo-capture front-end on borrowed NVIDIA hardware**; weak for teleop; zero robot-specific tooling. For our own AMD/Linux machine, MediaPipe/RTMW-style CPU pipelines or LeRobot's native teleop remain the pragmatic choice; RGB MoCap is the quality option when a CUDA box is available and quality > latency.

## 6. Use (b): AI gamedev (three.js character puppeteering)

Briefly (full gamedev dossier written separately at `unity_projects/AI_game_dev/research/2026-11-24_RGBmocap_toyxyz.md`): the **offline pipeline is excellent for game animation clips** — video → reconstruct → **built-in retarget to Mixamo FBX / VRM / PMX** → FBX/BVH → GLB → three.js `AnimationMixer`, with contact correction (no foot sliding), ARKit-style face coefficients, VMD export, and a Blender retargeter add-on for arbitrary rigs. **Live puppeteering into a browser is not possible today**: the live path can't export/stream, and there's no VMC/OSC/WebSocket output. Requires a Windows/NVIDIA capture machine.

## 7. Comparison table

Latency/quality notes are direction-of-truth only; licences verified from official repos unless flagged. (RGB MoCap row fully sourced this session.)

| Project | Input | Body/hand coverage | 3D / metric output | Linux + AMD/CPU viability | Licence | Latency notes | Best for |
|---|---|---|---|---|---|---|---|
| **RGB MoCap** (toyxyz) | RGB video/webcam; mono + multi-view (MAMMA) | Full body + fingers (SMPL-X/SMPL-H/SOMA); face (ARKit coeffs) | Yes — mesh + skeleton, human-scale prior (not calibrated) | **No (NVIDIA CUDA; Win; exp. Linux)** | MIT (code); weights gated | Offline 89–127 s / 2 s clip (5090); live preview 21–40 ms, export-less | High-quality offline mocap clips, retargeting, contact-fixed exports |
| MediaPipe Tasks (Pose/Hand/Holistic) | RGB video/camera | 33 body landmarks; 21 per hand; world 3D in metres | Keypoints + world coords (metric-ish, per-frame) | **Yes — real-time on CPU** | Apache-2.0 | ~real-time on CPU | Live low-cost tracking, robotics cheap path |
| RTMPose / RTMW (MMPose) | RGB | 133 whole-body keypoints (RTMW); 2D + optional 3D | 2D confident; 3D via pose3d variants; not metric | **Yes — ONNX/CPU near-real-time** | Apache-2.0 | Real-time | Live keypoint streams, custom pipelines |
| OpenPose | RGB | 135 body/foot/hand/face keypoints (2D) | No (2D heatmaps/keypoints) | Yes (CPU slow, CUDA optional) | ACADEMIC — non-commercial | Real-time w/ GPU | Legacy 2D keypoint baselines |
| MMPose (framework) | RGB | Many models incl. wholebody 133 | 2D mostly; 3D via VideoPose3D-style add-ons | Yes | Apache-2.0 | Model-dependent | Building your own keypoint stack |
| FreeMoCap | Multi-cam RGB | Full body (MediaPipe-based), hands incl. | 3D triangulated, ~metric after calibration | **Yes — CPU** | AGPL-3.0 | Near-real-time capture | Multi-cam open mocap, Blender export |
| EasyMocap | Multi-cam RGB(+depth) | SMPL body (hands limited) | 3D, calibrated metric | Yes but heavy/slow (CPU fitting) | Research licence — **verify at repo** [not confirmed this session] | Offline, slow | Calibrated multi-view research captures |
| Sapiens (Meta) | RGB | Body pose + surface (+seg/depth/normal) | 3D surface, human-scale prior | GPU recommended (CUDA); CPU impractical | Code Apache-2.0; weights gated non-commercial **[verify at HF]** | Offline seconds/image (GPU) | High-fid. body/depth priors |
| 4D Humans (HMR2.0) | RGB video | SMPL body, no fingers | 3D mesh, human-scale prior | CUDA PyTorch; CPU very slow | **Not confirmed this session** (check repo) | Offline, ~GPU-realtime-ish | Monocular body mesh recovery research |
| HaMeR | RGB hand crops | MANO hands, detailed | 3D hand mesh, metric-ish | CUDA PyTorch; CPU slow | **Not confirmed this session** (check repo) | Offline | Offline hand/finger refinement (used as RGB MoCap's add-on) |
| Move.ai | RGB video (1–8 cams, cloud) | Full body (+hands on some tiers) | 3D, calibrated multi-cam metric | Cloud — OS-agnostic | Commercial closed | Minutes/clip (cloud) | No-hassle pro mocap without rigs |
| Rokoko Video | RGB video | Full body + hands (Vision tier) | 3D FBX/BVH export | Cloud/app — OS-agnostic | Commercial (free tier) | Near-real-time-to-minutes | Quick game-dev mocap exports |

## 8. Bottom line for the hackathon

If a Windows/NVIDIA machine can be borrowed: RGB MoCap is the **highest-quality zero-hardware mocap** for capturing human demonstrations (upper body + fingers, contact-corrected, Mixamo/VRM retargeting built in), and the code is open enough to script (AGENT_GUIDE.md exists for exactly that). It will **not** run on our AMD iGPU Linux box in any mode, offers no live robot-rate stream, no OSC/VMC, no metric calibration against a robot frame — all retargeting, timing and robot-frame alignment work is ours to build.

## Sources (all fetched 2026-11-24)

1. Repo metadata: https://api.github.com/repos/toyxyz/toyxyz_RGBMocap (dates, stars, forks, issues, licence flag, language)
2. README: https://raw.githubusercontent.com/toyxyz/toyxyz_RGBMocap/main/README.md
3. LICENSE (MIT + third-party scope): https://raw.githubusercontent.com/toyxyz/toyxyz_RGBMocap/main/LICENSE
4. Linux guide (linux_support branch): https://raw.githubusercontent.com/toyxyz/toyxyz_RGBMocap/linux_support/docs/LINUX.md
5. Performance & measurements: https://raw.githubusercontent.com/toyxyz/toyxyz_RGBMocap/main/docs/PERFORMANCE.md
6. PEAR live-mode guide (latency, camera slots, scale caveats): https://raw.githubusercontent.com/toyxyz/toyxyz_RGBMocap/main/docs/models/PEAR.md
7. Python requirements (cu128 torch, no ONNX/TRT): https://raw.githubusercontent.com/toyxyz/toyxyz_RGBMocap/main/requirements-windows.txt
8. Releases feed (4 releases, Nov 19–20, 2026): https://github.com/toyxyz/toyxyz_RGBMocap/releases.atom
9. Issues count: https://api.github.com/search/issues?q=repo:toyxyz/toyxyz_RGBMocap+type:issue (67 total / 40 open from repo API)
10. Community ROCm port (AMD feasibility + weight manifest): https://github.com/herman6888/rgbmocap-rocm-port
11. Headless/remote tooling (community): https://github.com/KoSukeWork/rgbmocap-remote
12. Companion Blender retargeter: https://github.com/toyxyz/toyxyz-blender-retargeter (GPL-3.0, via GitHub API)
13. Comparison-table rows: google-ai-edge/mediapipe, open-mmlab/mmpose (RTMPose/RTMW), CMU-Perceptual-Computing-Lab/openpose, freemocap/freemocap, zju3dv/EasyMocap, facebookresearch/sapiens, muelemane/hmr, geopavlakos/hamer, move.ai, rokoko.com — official project pages; licences marked "not confirmed" where I did not read the licence text this session.
