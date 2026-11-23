# Simulators for robot-learning loops on non-NVIDIA hardware (Strix Halo / AMD 8060S)

*Researched 2026-11-24 for the ~Dec 2026 "learning loops" hackathon (OpenAI × Alloy Robotics, 1 day).*
*Machine under study: AMD Ryzen AI Max+ 395 (32 threads), 124 GB unified RAM, Radeon 8060S iGPU (Vulkan, no CUDA), CachyOS (Arch), kernel 6.18, 429 GB free, Python 3.14 system / 3.12 venv.*

---

## 0. TL;DR verdict

**Isaac Sim on this machine: not possible. Full stop.** Isaac Sim requires an RTX GPU with RT Cores, 16 GB VRAM minimum, Ubuntu 22.04/24.04, and NVIDIA driver 595.x; AMD GPUs, ROCm, ZLUDA, and Arch Linux are all outside its supported matrix — and no official AMD path exists anywhere in the docs. **Plan A is the MuJoCo ecosystem on CPU** (MuJoCo Playground v1.0 ships a literal CPU training command; PyTorch-based, Python 3.12–3.14, Apache-2.0, SO-101 = LeRobot's arm), with **Genesis World (Quadrants targets Vulkan/ROCm/x86)** and **ManiSkill CPU-sim + Vulkan rendering** as backups. Keep a **RunPod RTX box** ($0.89–2.89/hr) only as the fallback if the hackathon demands Isaac — budget ~1 day of pre-work for that path, not the day itself.

---

## 1. The NVIDIA Isaac stack, hard look

### 1.1 Isaac Sim (current major version: 6.x; Isaac Lab 3.0.0 targets Isaac Sim 6.2)

Official requirements (source: [Isaac Sim Requirements](https://docs.isaacsim.omniverse.nvidia.com/latest/installation/requirements.html), last updated 2026-10-14):

| Element | Minimum |
|---|---|
| OS | Ubuntu 22.04/24.04 (22.04 deprecated), Windows 11 |
| GPU | **GeForce RTX 4080 min / RTX 5080 "Good" / RTX PRO 6000 Blackwell "Ideal"** |
| VRAM | **16 GB minimum** (footnote: more recommended; complex scenes need it) |
| Driver | Linux 595.58.03, Windows 595.97 |
| RAM | 32 GB |
| Storage | 50 GB SSD minimum |

Explicit exclusions on the same page: **"GPUs without RT Cores (A100, H100) are not supported"** — i.e. even NVIDIA datacenter cards need RT Cores. The aarch64 build is DGX Spark-only (NVIDIA DGX OS 7, driver 580.159.03). The container is Linux-only.

**AMD GPU verdict: definitively NO.** Nothing in the requirements page or Isaac Lab docs mentions ROCm, AMD, or any non-NVIDIA GPU. Isaac Sim's rendering stack is Omniverse RTX (CUDA + RT Cores + Vulkan-on-NVIDIA); its physics (PhysX GPU) is CUDA. There is no supported AMD path and no supported Arch path (Ubuntu/Windows only; wheels require GLIBC 2.35+ per Isaac Lab docs — CachyOS has that, but the OS gate is still Ubuntu/Win11, and the GPU gate is unconditional). ZLUDA is a community hack with no Isaac Sim support and no official statement — **[unverified]** that it fails, but nothing suggests otherwise; do not spend hours on it.

### 1.2 The pip route (`isaacsim` wheels)

Isaac Sim ships as PyPI wheels from `pypi.nvidia.com` — Isaac Lab's docs install it as the `isaacsim` extra: **`isaacsim[all,extscache]` version 6.2.0.0**, first launch downloads extensions (can take >10 min) and needs `OMNI_KIT_ACCEPT_EULA=yes` for headless EULA acceptance (source: [Isaac Lab Installation](https://isaac-sim.github.io/IsaacLab/main/source/isaaclab/installation.html), last updated 2026-11-23). Same NVIDIA hardware gates apply — pip install ≠ AMD support.

### 1.3 Isaac Lab (3.0.0, Nov 2026)

Big architectural change worth knowing: **Isaac Lab 3.0 installs Newton by default and runs "kit-less" — Isaac Sim is optional.** But its own system-requirements table still says GPU training needs **"a CUDA-capable NVIDIA GPU supported by the selected Newton solver and PyTorch"; default CUDA 13 stack requires Turing or newer (compute capability 7.5+)**, driver 595.58.03+ (source: [Isaac Lab Installation](https://isaac-sim.github.io/IsaacLab/main/source/isaaclab/installation.html)). Headless Newton simulation does not need RTX hardware, and Newton visualizers (`viser`, `rerun`) serve a web page with no display. **Still NVIDIA-only for GPU training.** (A CPU fallback technically exists inside Warp — see §2 — but Isaac Lab's supported/trained matrix is NVIDIA.)

### 1.4 Isaac Gym / Preview / OmniIsaacGym (legacy)

Isaac Gym is **"Now Deprecated… legacy software… no longer supported"**, downloadable only from archive, Preview 4 was the last release, and NVIDIA redirects users to Isaac Lab (source: [developer.nvidia.com/isaac-gym](https://developer.nvidia.com/isaac-gym)). It was a CUDA/PhysX-GPU stack with old Ubuntu/Python pins — **[unverified]** exact version pins, not re-fetched today — and never supported AMD. Ignore it entirely; anything it could do, MJWarp does better and is maintained.

### 1.5 Headless / streaming options (for the RTX-box or cloud path)

Isaac Sim supports headless operation plus **Livestream Clients** (WebRTC-based remote viewing — [Livestream Clients docs](https://docs.isaacsim.omniverse.nvidia.com/latest/installation/manual_livestream_clients.html)); the client package has its own EULA page ([license](https://docs.isaacsim.omniverse.nvidia.com/latest/common/license-isaac-sim-webrtc-streaming-client.html)). Isaac Lab's container guide covers CloudXR streaming and a `viser`/`rerun` browser visualization that needs no display (source: [Isaac Lab Installation → containers](https://isaac-sim.github.io/IsaacLab/main/source/isaaclab/installation.html)).

---

## 2. Newton physics engine and MuJoCo Warp (MJWarp)

- **Newton** ([newton-physics/newton](https://github.com/newton-physics/newton)): Apache-2.0, Linux Foundation project (Disney Research + Google DeepMind + NVIDIA). Built on NVIDIA Warp; integrates MJWarp as primary backend. README requirements: Python 3.11+, Linux x86-64/aarch64, Windows x86-64, **"macOS (CPU only)"** — which proves a CPU path exists. Examples accept `--device cpu` and `--viewer gl|usd|rtx|rerun|viser|null`. GPU acceleration = NVIDIA Turing+ (sm_75), driver R580+ since Warp 1.18. **Verdict: runnable on our machine on CPU (slow but real); GPU path is NVIDIA-only.**
- **MuJoCo Warp** ([google-deepmind/mujoco_warp](https://github.com/google-deepmind/mujoco_warp)): Apache-2.0, "GPU-optimized version of the MuJoCo physics simulator, **designed for NVIDIA hardware**… requires an NVIDIA GPU for fast simulation **but supports CPU for development and debugging**." Batch renderer is NVIDIA GPU ray-tracing (OptiX optional). **Verdict: NVIDIA for the big throughput numbers; CPU mode exists but is explicitly a dev/debug path, not a training-workhorse path.**
- **Warp** ([NVIDIA/warp](https://nvidia.github.io/warp/latest/user_guide/compatibility.html)): **"CPU-only execution is supported on all supported platforms for users without a compatible GPU or driver"**; macOS = CPU only. This is the underlying mechanism that makes Newton/MJWarp CPU-runnable.

---

## 3. Genesis (now "Genesis World")

Repo moved: `Genesis-Embroidered` → **[Genesis-Embodied-AI/genesis-world](https://github.com/Genesis-Embodied-AI/genesis-world)** (30.3k stars; previously "Genesis", now company-backed by Genesis AI; v1.0 blog May 2026). Apache-2.0. Key facts for us:

- **Compiler (Quadrants, a Taichi fork) targets CUDA, AMD ROCm, Apple Metal, Vulkan, x86, and ARM64** — the only major sim whose stated backend matrix explicitly includes AMD and plain x86 (source: repo README, "Compiler" section).
- PyTorch install documented as "CPU only (Linux/Windows)" alongside CUDA and Metal/MPS → **CPU fallback is an officially documented install path** (same README, uv section).
- Python **>=3.12,<3.15** — fits our 3.12 venv (not the system 3.14).
- Renderers: in-house **Nyx**, Luisa (ray-tracing DSL), Pyrender (rasterizer). Physics: rigid, FEM, MPM, PBD/SPH, IPC (IPC extra `pyuipc` = **NVIDIA GPU only**), SAP.
- Maturity: huge community, company-supported, but API churn risk is real (project renamed + v1.0 rewrite within 2026). Budget time for breakage on hackathon day if chosen as primary.

---

## 4. Alternatives that DO run on Linux + AMD/CPU

| Simulator | Licence | Install on Arch | CPU / AMD rendering | Learning-loop fit | LeRobot fit |
|---|---|---|---|---|---|
| **MuJoCo Playground** `playground>=1.0` ([repo](https://github.com/google-deepmind/mujoco_playground)) | Apache-2.0 | pip/uv, Python 3.12–3.14 | **Official CPU training command in README** (RSL-RL PPO, SO101PickCube, `--overrides='{"nworld": 64}'`); MuJoCo Studio web viewer for playback | Excellent: RL training, teleop, system-ID, sim2real deploy in one package | **Best**: SO-101 sim+real teleop, zero-shot sim2real pick-cube deploy — SO-101 is LeRobot's own arm ([LeRobot README](https://github.com/huggingface/lerobot)) |
| **MuJoCo** core ([repo](https://github.com/google-deepmind/mujoco)) | Apache-2.0 | `pip install mujoco`, monthly releases | CPU-native everywhere; WebGL in browser | Great for custom envs, rollout module, Menagerie robot models | Good (LeRobot sim2sim pipelines use MuJoCo MJCF) |
| **PyBullet** ([repo](https://github.com/bulletphysics/bullet3)) | zlib **[unverified licence — not fetched today]** | `pip install pybullet`, no deps | CPU-only; always worked on AMD | Aging; envs stale but famously robust | Weak (legacy Gym API) |
| **Brax** ([repo](https://github.com/google/brax)) | Apache-2.0 | pip (JAX) | JAX runs CPU; "designed for accelerator hardware" | **Only `brax/training` maintained as of 0.13.0**; README says use MuJoCo Playground for envs, MJX/MJWarp for physics | Indirect (its PPO trainer trains Playground envs well) |
| **MJX** ([MuJoCo XLA docs](https://mujoco.readthedocs.io/en/stable/mjx.html)) | Apache-2.0 | pip `mujoco-mjx` | JAX CPU or NVIDIA GPU | JAX-side alternative to MJWarp; Playground `rss2025` envs use it | OK (older Playground suite) |
| **robosuite v1.5** ([ARISE-Initiative/robosuite](https://github.com/ARISE-Initiative/robosuite)) | MIT **[unverified — LICENSE file not fetched]** | pip | MuJoCo CPU sim; optional Isaac Sim photorealistic rendering (skip that part here) | Strong manipulation benchmark; robomimic datasets | OK for BC/IL demos |
| **ManiSkill 3** ([mani-skill/ManiSkill](https://github.com/mani-skill/ManiSkill)) | Apache-2.0 code; **assets CC BY-NC 4.0 (non-commercial)** | `pip install mani_skill` + **Vulkan setup required for rendering** | Official table: **Linux / AMD GPU: CPU sim ✅, GPU sim ❌, Rendering ✅** — best-in-class AMD rendering story | Strong (manipulation, IL/RL baselines, VLA evals) | OK; envs usable via Gymnasium |
| **Genesis World** | Apache-2.0 | pip `genesis-world`, Py ≥3.12,<3.15 | Vulkan/ROCm/x86 compiler targets (§3) | Promising, newer/riskier | No first-party integration found |
| **Webots** ([cyberbotics.com](https://cyberbotics.com)) | Open source, Apache-2.0 per [repo LICENSE](https://github.com/cyberbotics/webots/blob/master/LICENSE) **[licence text not fetched today]** | Official packages: .deb / tar.bz2 / Snap — **no pacman package in scope; tar.bz2 runs without install** | OpenGL 3.3 renderer (wren) — runs on Mesa/AMD; ODE-fork physics, deterministic | Great GUI + Python API; RL possible but not GPU-parallel | Weak |
| **Gazebo (gz-sim)** ([gazebosim.org](https://gazebosim.org)) | Apache-2.0 **[unverified — docs not fetched today]** | Arch has community packages, but no package managers per task rules — tar/source route is heavy | ODE/DART/Bullet physics CPU; Ogre2 rendering works on Mesa/AMD in practice **[unverified]** | ROS-centric; heavyweight for a 1-day hackathon | Weak |
| **RaiSim** ([raisimTech/raisimLib](https://github.com/raisimTech/raisimLib)) | **Proprietary — "You should get a valid license and an activation key"** (README); raisimLib archived 2026-04-25, successor raisim2Lib | CMake build, Eigen dep | CPU rigid-body; viewers use Vulkan or OpenGL | Skip: licence friction + archive churn for a 1-day event | Weak |

**Skipped as requested:** CuteGPU and Kalman — unknown/not found; nothing credible surfaced during this pass.

---

## 5. In-browser "digital twin" visualiser (Python policy in the loop)

Realistic and low-risk, all verified:

- **Official MuJoCo WASM is first-party**: MuJoCo repo has a `wasm/` directory with JavaScript bindings; **[live.mujoco.org](https://live.mujoco.org)** runs MuJoCo Studio in WebAssembly where you can drag-and-drop your own MJCF models; [mujoco.org](https://mujoco.org) demos it on desktop/mobile with nothing installed (source: [mujoco README](https://github.com/google-deepmind/mujoco)). Community extension **mjswan** adds real-time policy control and interactive force application ([ttktjmt/mjswan](https://github.com/ttktjmt/mjswan), linked from the MuJoCo README) **[unverified — not fetched]**.
- **Recommended architecture for the hackathon demo**: Python (policy, PyTorch CPU) computes actions → streams joint states over WebSocket → **three.js** scene (or the MuJoCo WASM viewer) renders the twin in-browser. This runs on the AMD machine, on any judge's laptop, and needs zero GPU. Physics authority stays on CPU MuJoCo; the browser is display-only.
- **Rapier (Rust→WASM)** is a credible in-browser physics alternative if you want physics *inside* the browser tab **[unverified — docs not fetched]**; redundant when Python is driving the loop anyway.
- **Pyodide** (CPython in WASM) could run the policy in-tab, but PyTorch-in-Pyodide is heavy and slow — keep Python on the host, mark Pyodide as emergency-only **[unverified]**.

---

## 6. Cloud route if the hackathon demands Isaac (outline)

Verify-at-venue commands (NVIDIA box or cloud pod):

```bash
nvidia-smi                      # driver ≥ 595.58 (Linux) for Isaac Sim 6.2
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
pip install "isaaclab[isaacsim]==3.0.0" --index https://pypi.nvidia.com \
  --overrides https://raw.githubusercontent.com/isaac-sim/IsaacLab/v3.0.0/tools/wheel_builder/uv-overrides.txt \
  --torch-backend cu130 --index-strategy unsafe-best-match   # per Isaac Lab docs
OMNI_KIT_ACCEPT_EULA=yes isaacsim            # first launch: >10 min extension download
uvx --index https://pypi.nvidia.com --torch-backend cu130 --from "isaaclab==3.0.0" isaaclab demo zoo
```

Then headless + `--viz viser` (browser view) or the Isaac Sim WebRTC livestream client ([docs](https://docs.isaacsim.omniverse.nvidia.com/latest/installation/manual_livestream_clients.html)).

Providers (sources, prices as published Nov 2026):
- **RunPod** ([pricing](https://runpod.io/gpu-cloud/pricing), updated 2026-11-12): RTX 4090 24 GB **$0.89/hr** Secure / $0.34 Community; RTX 5090 32 GB $1.39/hr; A100 PCIe 80 GB $2.09/hr; H100 PCIe $2.89/hr; per-second billing. RTX 4090/5090 satisfy the RT-Cores + 16 GB VRAM gate.
- **Lambda / CoreWeave / Google Colab**: not price-verified today **[unverified]**. Colab free tier is unsuitable for Isaac Sim (no interactive GUI, no guaranteed GPU model, session limits); Colab works fine for MJWarp/Playground tutorials (MJWarp ships a Colab notebook — [mujoco_warp README](https://github.com/google-deepmind/mujoco_warp)).
- NVIDIA's own Isaac Automator provisions AWS/GCP/Azure workstations for Isaac Lab ([Isaac Lab docs → Cloud workstations](https://isaac-sim.github.io/IsaacLab/main/source/isaaclab/installation.html)).

Budget rule: if a cloud Isaac box is needed, rent **after** the local MuJoCo stack is already working, not before.

---

## 7. Tiered recommendation for OUR situation

**Tier 0 — do these two weeks before (this machine, no NVIDIA):**
1. Python **3.12** venv (system 3.14 is too new for the ecosystem): `uv venv --python 3.12`.
2. `pip install mujoco` + run a Menagerie SO-101/SO-100 model headless (verifies GL/EGL on Mesa).
3. `pip install "playground[rl]>=1.0"` and run the README **CPU train** of `SO101PickCube` (nworld 64) — this is the entire hackathon dry-run.
4. `pip install mani_skill` and verify Vulkan rendering on the 8060S (AMD render ✅ per its table).
5. Prototype the browser twin: Python WebSocket → three.js; test on a second device.
6. Skim Genesis install in a *separate* venv; do not make it primary.

**Tier 1 — what we run on the day (no NVIDIA available):**
MuJoCo Playground CPU training + MuJoCo Studio/three.js web viewer + LeRobot SO-101 tooling. Fallbacks: Genesis World (x86/Vulkan), ManiSkill CPU sim with Vulkan rendering.

**Tier 2 — only if the venue provides an RTX box or credits:**
Confirm `nvidia-smi` driver ≥ 595, rent nothing, run the §6 verify sequence, train with Isaac Lab `physics=newton_mjwarp`, view via `viser` in the judges' browsers. Timebox setup to 45 minutes; if the wheels/EULA/extensions stall, drop straight back to Tier 1 — same MJCF assets work in both stacks (Newton/MJWarp consume MuJoCo models; Isaac Lab has an MJCF importer too).

---

## 8. Hackathon-morning hardware checklist (5 minutes)

1. `nvidia-smi` → present? note driver version (≥595.58 needed for Isaac Sim 6.2).
   - **No NVIDIA → Tier 1. Done.**
2. `lspci | grep -i vga` → what GPU? (AMD 8060S expected → Vulkan present, Mesa current?)
3. `vulkaninfo --summary` → ICDs visible (needed by ManiSkill rendering / Genesis Vulkan backend).
4. `python --version` → if 3.13/3.14, activate our 3.12 venv (`uv venv --python 3.12`).
5. `python -c "import mujoco, torch; print(mujoco.__version__, torch.__version__)"`.
6. Internet? `ping pypi.nvidia.com` (Tier 2 needs it; Tier 1 should be pre-cached).
7. Decision matrix:
   - NVIDIA RTX, ≥16 GB VRAM, driver ≥595 → **Tier 2 Isaac**, 45-min timebox.
   - NVIDIA GTX/RTX older, <16 GB, driver <580 → MJWarp GPU or CPU Playground.
   - AMD/CPU only → **Tier 1** (Playground CPU / Genesis / ManiSkill).
   - No internet → everything must already be cached locally (Tier 0 pre-install makes this survivable).

---

## 9. Comparison table

| Simulator | Physics fidelity | Speed on CPU | Render on AMD | Python API | LeRobot integration | Licence | 1-day hackathon fit |
|---|---|---|---|---|---|---|---|
| Isaac Sim 6.2 | Excellent (PhysX/Newton, sensors) | Not usable (NVIDIA-only) | **❌ unsupported** | Yes | Indirect | Proprietary EULA | **❌ zero on our machine** |
| Isaac Lab 3.0 (Newton/MJWarp) | Excellent | CPU path exists, unsupported officially | ❌ (GPU sim NVIDIA) | Yes | Indirect (SO-101 tutorial exists in its deployment docs) | BSD-3 + Apache-2 | Cloud/RTX-box only |
| Isaac Gym Preview 4 | Good (legacy PhysX) | ❌ | ❌ | Legacy Gym | None | NVIDIA EULA, deprecated | ❌ ignore |
| Newton (standalone) | Good, differentiable | `--device cpu` works | GL/viser/rerun viewers OK | Yes | None first-party | Apache-2.0 | Good backup |
| MuJoCo Warp | Excellent (MuJoCo parity, minor gaps: no PGS/IMPLICITFAST-midpoint) | Explicitly "dev/debug" only | Viewer works; renderer NVIDIA | Yes | Via Playground | Apache-2.0 | GPU-only thruput |
| **MuJoCo Playground** | MuJoCo-grade | **Official CPU training command** | Studio web viewer (WASM/GL) | PyTorch | **Direct (SO-101 sim+real)** | Apache-2.0 | **★ Best** |
| MuJoCo core | Excellent | Native | Native + WASM | Yes | sim2sim pipelines | Apache-2.0 | ★ Backbone |
| Genesis World | Good multi-physics (rigid/FEM/MPM/SPH/IPC) | Documented CPU install | Vulkan/ROCm targets; Nyx renderer | Yes | None found | Apache-2.0 | Good, higher risk |
| ManiSkill 3 | Good (SAPIEN/PhysX) | CPU sim ✅ | **Rendering ✅ via Vulkan** | Gymnasium | Partial (envs for eval) | Apache-2.0 code / CC-BY-NC assets | Good |
| robosuite v1.5 | Good (MuJoCo) | Native CPU | Mesa OK in practice **[unverified]** | Yes | Partial (BC/demos) | MIT **[unverified]** | OK |
| Brax (training only) | MJX-grade | JAX CPU (slow) | n/a (headless) | JAX | None | Apache-2.0 | Fallback trainer only |
| PyBullet | Good (older) | Native CPU | CPU GL | legacy Gym | Weak | zlib **[unverified]** | Emergency fallback |
| Webots | Moderate (ODE fork) | Real-time CPU | OpenGL 3.3 ✅ | Yes | Weak | Apache-2.0 **[unverified]** | Niche |
| Gazebo gz-sim | Moderate | CPU | Mesa ✅ **[unverified]** | C++/Python/ROS | Weak | Apache-2.0 **[unverified]** | Too heavy for 1 day |
| RaiSim | Excellent rigid-body | CPU | Vulkan/OpenGL viewers | raisimPy | Weak | **Proprietary, key required** | ❌ licence friction |

---

## 10. Blunt "NOT possible" list (don't burn hours)

- **Isaac Sim on this Strix Halo machine: impossible.** RTX + RT Cores are a hard gate; no AMD/ROCm/ZLUDA path is documented anywhere official.
- **Isaac Sim on Arch: unsupported.** Ubuntu 22.04/24.04 or Windows 11 only; use Docker on Ubuntu or a cloud box instead.
- **GPU-parallel sim on the 8060S: not available** in ManiSkill (GPU sim ❌ on AMD), MJWarp (NVIDIA for speed), Newton (NVIDIA for acceleration), Warp (CUDA-only acceleration). AMD here = CPU simulation + (ManiSkill/Genesis/Webots) GPU *rendering* only.
- **Isaac Gym: dead.** Deprecated, archived; do not build on it.
- **MJWarp as a CPU training workhorse: don't** — its own README calls CPU "development and debugging".
- **PyTorch on system Python 3.14: ecosystem too new** — use the 3.12 venv.
- **pyuipc (Genesis IPC solver): NVIDIA GPU only** on Linux x86.

---

## 11. Source ledger & unverified items

Verified from primary sources on 2026-11-24:
Isaac Sim requirements ([NVIDIA docs](https://docs.isaacsim.omniverse.nvidia.com/latest/installation/requirements.html)) · Isaac Lab installation/versions ([docs](https://isaac-sim.github.io/IsaacLab/main/source/isaaclab/installation.html), [GitHub README](https://github.com/isaac-sim/IsaacLab)) · Isaac Gym deprecation ([NVIDIA](https://developer.nvidia.com/isaac-gym)) · Warp compatibility ([docs](https://nvidia.github.io/warp/latest/user_guide/compatibility.html)) · Newton ([README](https://github.com/newton-physics/newton)) · MuJoCo Warp ([README](https://github.com/google-deepmind/mujoco_warp)) · Genesis World ([README](https://github.com/Genesis-Embodied-AI/genesis-world)) · MuJoCo Playground ([README](https://github.com/google-deepmind/mujoco_playground)) · MuJoCo/WASM ([README](https://github.com/google-deepmind/mujoco)) · ManiSkill 3 system table ([README](https://github.com/mani-skill/ManiSkill)) · robosuite ([README](https://github.com/ARISE-Initiative/robosuite)) · Brax status ([README](https://github.com/google/brax)) · Webots ([cyberbotics.com](https://cyberbotics.com)) · RaiSim licence/archival ([raisimLib README](https://github.com/raisimTech/raisimLib)) · LeRobot ([README](https://github.com/huggingface/lerobot)) · RunPod prices ([pricing page](https://runpod.io/gpu-cloud/pricing), updated 2026-11-12).

Marked **[unverified]** (not fetched from primary source today, treat as leads): PyBullet zlib licence; robosuite MIT licence; Webots/Gazebo exact licence texts; Gazebo Mesa rendering behaviour; mjswan capabilities; Pyodide+PyTorch feasibility; Lambda/CoreWeave/Colab pricing & limits; ZLUDA-Isaac incompatibility (no official statement exists either way — absence of support is what's verified).

*Local facts (our machine's specs, Arch/CachyOS, free disk) are from the task brief, measured today by the team.*
