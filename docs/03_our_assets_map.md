# 03 — Our assets map: every project this builds on

All paths verified on this machine 2026-11-24. Each entry: what it is → why it matters
here → how it plugs in.

## Robotics

| project | path | what / why / plug-in |
|---|---|---|
| **ARMSMITH** (Unity) | `~/projects/unity_projects/robot_arms/` | Our SO-101 6-DOF arm digital twin: ArticulationBody physics, FABRIK IK, STS3215 servo tick model, emergent-friction gripper, scenarios, GA + diffusion-policy training, 16/16 headless regression suite. **The design source for `sim/armsmith_web`** — kinematics.json + KINEMATICS_NOTES.md are the porting contract. Docs: HANDOVER.md, STATUS.md, design/GAME_DESIGN.md. |
| **robot_hand** | `~/projects/robot_hand/` | Tendon-driven STS3215 hand (InMoov i2 print): `python/hand_mirror.py` (MediaPipe landmarks→servo angles), serial bridge, self-observation CV. Landmark→actuator mapping ideas reused in `vision/hand_tracking/retarget.py`; the physical twin if we bring hardware. |
| **gesture-control** | `~/projects/gesture-control/` | Mature MediaPipe Hands stack (JS + Python): 21 landmarks, 8-gesture classifier, smoothing, gesture→effect mapper. Lineage of `vision/hand_tracking/hand_tracker.py`. |
| **anymove (patch.gg)** | `~/projects/unity_projects/phone_games/anymove/` | Video→3D-animation mocap: train/detect/solve (dual-view triangulation)/mirror/generate, GLB export. The "recorded human motion becomes animation" precedent for mocap→robot. |

## Motion / mocap / retargeting

| project | path | what / why |
|---|---|---|
| **long-wind mocap tools** | `~/projects/github_repos/long-wind/tools/mocap/retarget.py` | MediaPipe world landmarks → rig channel keys with per-shot smoothing. The retargeting maths reused for `arm_keypoints_to_ee`. |
| **AI_game_dev** | `~/projects/unity_projects/AI_game_dev/` | Master gamedev research hub: `research/` dossiers (incl. our new `2026-11-24_RGBmocap_toyxyz.md`), `catalog/games.json`, MECHANICS.md, PROCEDURAL_MOVEMENT_REVIEW.md. Where gamedev-side findings get logged. |
| **RGBmocap review** | `reviews/2026-11-24_RGBmocap_toyxyz.md` (repo) | Full robotics+gamedev review of toyxyz/toyxyz_RGBMocap. Verdict: Windows+CUDA offline body/hand mocap; not runnable here; Mixamo/VRM/UE retarget paths useful on borrowed hardware. |
| **mimicmotion / liveportrait / facefusion** | `~/projects/MASTER_PROJECTS/*` | Motion-transfer lineage (video editing CV) — the techniques map to demo post-processing (see doc 07 §6). |

## Computer vision (video editing)

| project | path | what / why |
|---|---|---|
| **clipforge** | `~/projects/video_editing/clipforge/` (public: github.com/qalarc/clipforge) | Verified CV pipeline: ffmpeg scdet shot detection, numpy frame profiling, faster-whisper word timing, GLM scoring, EDL export. **Reusable for robot demo processing**: shot-boundary segmenting of episode video, Whisper-timed language labels for demos, frame profiling for failure forensics. |
| **face_tracking_system** | `~/projects/GLM_projects/face_tracking_system/` | Consolidated FaceMesh/iris/rPPG stack — landmark streaming patterns, calibration discipline. |

## The agent ecosystem (Laya / GUT / Jev / MCP)

| system | path / port | what / why |
|---|---|---|
| **Laya** | `~/projects/GLM_projects/Laya_integrations/` · serve `:8798` | Fine-tuned typed-decision models, ~29 domains, FINETUNING_PROTOCOL.md contract. **System 1 here** via domain `robot-ops` (control/robot_ops.schema.json). Read-only for us; `data/robot-ops.jsonl` is our side of the flywheel. |
| **GUT** | same repo (`mcp_finetune/`) · gut.qalarc.com · HF `Qalarc/Laya-GUT-Finetune` · github qalarc/gut-finetuned | The training loop protocol + gates (agreement ≥0.85, ECE ≤0.10). Reflection: doc 09. |
| **Jev** | MCP `jev_decide` | Calibrated remote decisions; optional L2 gate (needs network). |
| **Ollama models** | `:11434` | `glm-4.7-flash-abl:alexei-v3` = System 2. Base `:32k` measured 15–30 s/plans. Beware RAM: 18–21 GB resident each. |
| **Blender MCP** | blender_* tools | Scene props / URDF→GLB for the sim + pitch visuals. |

## 3D worlds / procedural (the "3d worlds" thread)

| project | path | what / why |
|---|---|---|
| **phone_games three.js fleet** | `~/projects/unity_projects/phone_games/` (DUSKRUNNER_2 r187, crocodile_survival, tunnel_war, …) | The house three.js patterns (SceneBootstrap-by-code, interaction juice, single-file serving) — the conventions `sim/armsmith_web` follows. |
| **patch.gg library** | `~/projects/unity_projects/phone_games/patch_gg_assets/` | 22 cloned three.js reference repos (terrain, dungeons, trees, forests, powder-toy) + hub-world sandbox. Source for sim scene dressing. |
| **img2threejs** | `~/projects/scratch_img2threejs_run/` | Reference image → code-only procedural three.js model (Apache-2.0). Generating sim props on the day. |
| **rule_the_city** | `~/projects/GLM_projects/RTC/` | Procedural city from DEM data; the DEM→terrain trick for sim environments. |
| **3d_models_movements** | `~/projects/unity_projects/phone_games/3d_models_movements/` | Creature/mixamo/procedural-movement demo fleet — the procedural-motion grammar we want robots to inherit. |

## Conventions we inherit

Ports: Laya 8798, trainer console 8797, browser-ops 8831, games 92xx, patch.gg labs
538x — ours: **bus 8890, sim 8891, preview 8892**. Formats: three.js r186+ ESM, GLB,
JSONL decision rows (Laya), games.json-style catalogs. Style: code-generated worlds,
no art packs; small boring working processes; archive, never delete.
