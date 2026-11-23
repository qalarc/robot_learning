# 04 — LeRobot + MuJoCo for a 1-Day "Learning Loop" Hackathon

> Researched 2026-11-24 from official sources (huggingface.co/docs/lerobot, github.com/huggingface/lerobot,
> mujoco readthedocs + google-deepmind/mujoco source, PyPI JSON). Every non-obvious fact carries a source URL.
> Items I could not confirm are marked **[unverified]** — do not rely on them without checking.
>
> Our rig: 6-DOF SO-101-style arm (Feetech STS3215, parallel gripper) · AMD Ryzen AI Max+ 395 (32 threads) ·
> Radeon 8060S iGPU · **no NVIDIA/CUDA** · CachyOS/Arch, Python venv.

---

## 0. TL;DR for our box

- **LeRobot stable = 0.7.0** (PyPI, released 2026-11-05), Python ≥ 3.12, PyTorch ≥ 2.7 < 2.16.
  Source: https://pypi.org/project/lerobot/ , https://github.com/huggingface/lerobot
- **MuJoCo stable = 4.0.1** (released 2026-11-11), Python ≥ 3.11. Since 4.0 the `mujoco` pip package is a
  meta-package: `mujoco-core` (engine + classic OpenGL/egl/glfw/osmesa + viewer) + `mujoco-studio` + `glfw` +
  `pyopengl`. For headless sim you can install just `pip install mujoco-core` (depends only on numpy).
  Source: https://pypi.org/project/mujoco/ (package README)
- **MuJoCo sim is fully CPU-native** — 1-day loop (sim demos → LeRobotDataset → train ACT → eval) is realistic on CPU
  for a tiny dataset.
- **LeRobot's official stance on CPU training is blunt**: the Compute & Hardware Guide lists "CPU only → Don't train.
  Use Colab or rent a GPU" (https://huggingface.co/docs/lerobot/hardware_guide). Training a *big* ACT run on CPU is
  indeed impractical, but a hackathon-sized dataset (10–20 short episodes, downscaled images, few thousand steps)
  is CPU-feasible in ~1–3 h on 32 threads **[estimate — see §2.3]**. Fallback: HF Jobs (`--job.target=a10g-small`).

---

## 1. LeRobot (Hugging Face)

### 1.1 Install — CPU-only route

```bash
# venv, Python 3.12 (docs recommend conda/miniforge, but any ≥3.12 venv works per install docs)
python -m venv .venv && source .venv/bin/activate

# Core + dataset loading + training. NO policy/env extras needed for ACT-only CPU work.
pip install 'lerobot[training]'          # = dataset extra (datasets, av, torchcodec) + accelerate + trackio

# Optional, per workflow (docs: https://huggingface.co/docs/lerobot/installation):
pip install 'lerobot[core_scripts]'      # lerobot-record / -replay / -calibrate (+viz)
pip install 'lerobot[core_scripts,feetech]'  # record with SO-101 (Feetech via rustypot)
pip install 'lerobot[pusht]'             # gym-pusht sim env; '[aloha]' = gym-aloha; '[libero]' (Linux), '[metaworld]'
pip install 'lerobot[hilserl]'           # HIL-SERL RL + gym-hil (MuJoCo) sim teleop/record
```

CPU-specific notes from the install guide (https://huggingface.co/docs/lerobot/installation):

- LeRobot **defaults to TorchCodec for video decode → needs `ffmpeg`**. With PyTorch ≥ 2.10 (TorchCodec ≥ 0.10) a
  **system-wide ffmpeg** is supported (e.g. `sudo pacman -S ffmpeg`); on older torch it must come from conda-forge.
- PyPI Linux torch wheels are CUDA-13 builds; on a no-CUDA box install CPU wheels *first* to save disk:
  `pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision`
  then `pip install --index-url https://download.pytorch.org/whl/cpu torchcodec` (install guide's CUDA-variant
  section notes TorchCodec should also come from the CPU index in that case).
- Keyboard teleop (pynput global hooks) only works on X11 / Windows / macOS-with-permissions — **not Wayland/headless**
  (https://huggingface.co/docs/lerobot/il_robots#troubleshooting).

### 1.2 LeRobotDataset v3.0 (current schema)

Docs: https://huggingface.co/docs/lerobot/lerobot-dataset-v3 (v3.0 ships in `lerobot ≥ 0.4.0`; 0.7.0 is current).

Layout (v3 = file-based, many episodes per shard):

```
meta/info.json        # schema: features (name→dtype/shape), fps, path templates, codebase version
meta/stats.json       # per-feature mean/std/min/max used for normalization
meta/tasks.parquet    # task string → integer id
meta/episodes/        # per-episode records (length, tasks, byte/frame offsets), chunked parquet
data/                 # frame-level Parquet shards, each typically holds MANY episodes
videos/               # MP4 shards per camera, episodes concatenated, resolved via metadata
```

- Tabular columns use the standard feature names: `observation.state`, `action`, `timestamp`,
  `observation.images.<cam>` etc. Camera names in the recording config become dataset keys
  (`observation.images.wrist`, …) and a trained policy expects exactly those names/resolutions later
  (https://huggingface.co/docs/lerobot/il_robots#record-a-dataset).
- Loading: `LeRobotDataset("user/repo")`, random access `dataset[i]` → dict of torch tensors;
  temporal windows via `delta_timestamps={"observation.images.cam": [-0.1, 0.0]}` → `[T,C,H,W]` stacks.
  `StreamingLeRobotDataset` streams from the Hub without downloading.
- **Creating from your own arrays (no robot needed)** — verified against source
  (https://github.com/huggingface/lerobot/blob/main/src/lerobot/datasets/lerobot_dataset.py,
  `create`/`add_frame`/`save_episode`/`finalize` docstrings): `add_frame` takes a dict of feature-name→value and
  **must include a `'task'` key**; you *must* call `finalize()` before push/reload or the parquet footers are corrupt
  (https://huggingface.co/docs/lerobot/lerobot-dataset-v3#common-issues).

### 1.3 Policies & what fits a hackathon

Official table (https://huggingface.co/docs/lerobot/hardware_guide), peak VRAM @ batch 8, AdamW:

| Group | Policies | Peak VRAM (BS 8) | Notes for us |
|---|---|---|---|
| Light BC | `act`, `vqbet`, `tdmpc` | ~2–6 GB | **ACT is the hackathon default** |
| Diffusion | `diffusion`, `multi_task_dit` | ~8–14 GB | slower (RTX-4090: ~2–4 h for 5 ep/45k frames) |
| Small VLA | `smolvla` | ~10–16 GB | needs transformers extra + GPU |
| Large VLA | `pi0`, `pi0_fast`, `pi05`, `xvla`, `wall_x` | ~24–40 GB | cloud only |
| RL | `sac` (HIL-SERL) | config-dep. | see https://huggingface.co/docs/lerobot/hilserl |

Official wall-clock anchors (5 epochs, ~50 episodes, ~45k frames @30 fps, 640×480): ACT on RTX 4090 ≈ 30–60 min;
ACT on Apple-silicon MPS ≈ 6–14 h. VLAs are multi-hour even on A100s. Imitation typically converges in **5–10
epochs**, so set `--steps` accordingly (default is 100,000 steps — usually far more than a small dataset needs).
Source: https://huggingface.co/docs/lerobot/hardware_guide + https://huggingface.co/docs/lerobot/il_robots#train-a-policy

Also available (README policy table): Pi0/Pi0Fast/Pi0.5, SmolVLA, GR00T N1.7, VQ-BeT, TDMPC, HIL-SERL, plus many
2026 additions (EO-1, XVLA, WALL-OSS, world models, reward models):
https://github.com/huggingface/lerobot#sota-models

### 1.4 Train / resume / eval / inference commands

All verified from https://huggingface.co/docs/lerobot/il_robots:

```bash
lerobot-train \
  --dataset.repo_id=${HF_USER}/my_dataset \
  --policy.type=act \
  --output_dir=outputs/train/act_arm \
  --job_name=act_arm \
  --policy.device=cpu \            # cuda | mps | cpu (guide shows cuda/mps; cpu accepted for training)
  --policy.push_to_hub=false

# Resume from a checkpoint (config is reloaded, optimizer + step counter restored):
lerobot-train \
  --config_path=outputs/train/act_arm/checkpoints/last/pretrained_model/train_config.json \
  --resume=true

# Checkpoints land in  outputs/train/<job_name>/checkpoints/<step>/pretrained_model
```

- Eval in sim: `lerobot-eval --policy.path=<repo-or-path> --env.type=libero --env.task=libero_object
  --eval.n_episodes=10` (README example; env extras `libero`, `metaworld`, `pusht`, `aloha`).
- Real-robot deployment: **`lerobot-rollout`** replaced plain record-with-policy; strategies:
  `base` (no recording), `sentry` (record+upload), `highlight` (keystroke ring buffer), `dagger` (human-in-the-loop
  data collection), `episodic`. **Async/smooth inference** for slow VLAs: `--inference.type=rtc`.
- If local CPU/GPU isn't enough: `lerobot-train ... --job.target=a10g-small` runs on HF Jobs (pay-per-second,
  `t4-small`/`l4x1`/`a10g-large`/`a100-large` flavors; list via `hf jobs hardware`).

### 1.5 Teleoperation & recording tooling (SO-100/SO-101)

Verified: https://huggingface.co/docs/lerobot/so101 + https://huggingface.co/docs/lerobot/il_robots

- CLI tools: `lerobot-find-port`, `lerobot-setup-motors --robot.type=so101_follower/--teleop.type=so101_leader`,
  `lerobot-calibrate`, `lerobot-teleoperate`, `lerobot-record`, `lerobot-replay`, `lerobot-rollout`.
  (`lerobot-find-cameras` existed in earlier versions — current 0.7 name **[unverified]**.)
- Python API: `from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig`;
  `from lerobot.teleoperators.so_leader import SO101Leader, SO101LeaderConfig`. Leader arm uses mixed-gearing
  STS3215 (1/191–1/345) so it's back-drivable; follower uses 6× 1/345 motors.
- Recording controls: `→`/`n` next episode, `←`/`r` re-record, `ESC`/`q` stop+encode+upload; cadence report shows
  whether you actually hit the target fps (timestamps are derived from frame index — a 25 Hz session "claims" 30).
- Teleop device types: leader arm, **keyboard, gamepad, phone** (README hardware list). Meta Quest appears in the
  third-party hardware/plugin list (README "Third-Party Hardware"). Camera-based teleop (MediaPipe/ARKit/Apple
  Vision Pro, Homunculus-style) — mentioned by the community but not in the pages I checked **[unverified]**.

### 1.6 Simulation & MuJoCo inside LeRobot; human-in-the-loop

- **gym-hil** (https://github.com/huggingface/gym-hil) — MuJoCo-based manipulator env used both for sim
  imitation-learning *and* HIL-SERL RL. Install `pip install -e ".[hilserl]"` (pulls `gym-hil>=0.1.14` + `placo`).
  Record/teleop-in-sim flow: https://huggingface.co/docs/lerobot/main/en/il_sim —
  `python -m lerobot.rl.gym_manipulator --config_path=env_config.json` (tasks like `PandaPickCubeGamepad-v0` /
  `PandaPickCubeKeyboard-v0`, fps 10), eval via `python -m lerobot.rl.eval_policy --config_path=...`.
  Source module: `src/lerobot/rl/gym_manipulator.py` (verified in repo tree).
- Sim env packages: `gym-pusht` (push-T), `gym-aloha`, `hf-libero`, `metaworld` (installation guide).
- HIL-SERL guide: https://huggingface.co/docs/lerobot/hilserl ; HIL sim variant: `./hilserl_sim`.
- EnvHub lets you implement/distribute custom sim envs for `lerobot-eval` (README).

### 1.7 Notable datasets on the Hub

- `lerobot/pusht` (push-T), `lerobot/aloha_mobile_cabinet` (README examples),
  `lerobot/svla_so101_pickplace` (SO-101, used as the docs showcase dataset in the visualizer).
- Browse everything tagged `LeRobot`: https://huggingface.co/datasets?other=LeRobot (il_robots tip). For
  SO-100/SO-101 community datasets specifically, search the Hub for "so101" — I did not enumerate them here
  **[unverified]**.
- Visualizer (no install): https://huggingface.co/spaces/lerobot/visualize_dataset

### 1.8 Known CPU-only gotchas

1. **Official guidance says don't train on CPU** (hardware_guide). Reality check for hackathons: ACT with small
   images and a few-k-step budget is workable **[estimate]**; diffusion/SmolVLA/VLAs are not.
2. TorchCodec/ffmpeg: install system ffmpeg (torch ≥ 2.10) or dataset loading breaks; torchcodec wheel itself
   should come from the CPU index on non-CUDA machines (installation guide).
3. `--dataset.image_transforms.backend=gpu` is refused on CPU — leave transforms on the dataloader backend.
4. Default `--steps=100000` massively overshoots a hackathon dataset; also match `--policy.scheduler_decay_steps`
   and `--save_freq` to your step budget (hardware_guide "Schedule and checkpoints").
5. pynput keyboard teleop = X11 only; recording control keys work in any interactive terminal (Wayland OK).
6. `lerobot-record` appends a timestamp to `repo_id` (use `--dataset.no_stamp=true` to keep it exact) and requires
   `--resume=true` + `--dataset.root` to append episodes to an existing dataset.

---

## 2. MuJoCo

### 2.1 Version & install

- **4.0.1** (PyPI 2026-11-11; changelog: https://mujoco.readthedocs.io/en/4.0.1/changelog.html), Python ≥ 3.11,
  docs: https://mujoco.readthedocs.io/en/stable/ and https://mujoco.org.
- `pip install mujoco` → mujoco-core + mujoco-studio (Studio viewers, new Filament renderer `mujoco.mjrf`) + glfw +
  pyopengl. **Minimal headless: `pip install mujoco-core`** (numpy only) — ideal for RL/data-collection workers
  without any rendering (PyPI package README).

### 2.2 Rendering on Linux with an AMD iGPU

Verified from the rendering guide (https://mujoco.readthedocs.io/en/stable/programming/rendering.html) and the
bindings source (`python/mujoco/rendering/classic/gl_context.py`):

> "On Linux, MuJoCo currently supports **GLX** for rendering to an X11 window, **OSMesa** for headless software
> rendering, and **EGL** for hardware accelerated headless rendering."

- Backend selection via the `MUJOCO_GL` env var; valid Linux values: `glfw`/`glx`, `egl`, `osmesa`, or `disable`;
  anything invalid raises at import (gl_context.py). Example:
  `MUJOCO_GL=egl python render.py` (hardware-accelerated headless via EGL — works with Mesa/Radeon) or
  `MUJOCO_GL=osmesa` (safe pure-CPU fallback; needs osmesa libs present).
- With a desktop session, GLFW (default) "just works" on X11; on Wayland prefer `MUJOCO_GL=egl` for offscreen
  frames. For the hackathon's offscreen RGB streams, `egl` is the fast path; `osmesa` is the guaranteed-works
  fallback.

### 2.3 Core API essentials

```python
import mujoco
model = mujoco.MjModel.from_xml_path("scene.xml")     # or from_xml_string(xml)
data = mujoco.MjData(model)
mujoco.mj_step(model, data)                            # advance one timestep
data.qpos / data.qvel                                  # generalized position/velocity
data.ctrl[:] = ...                                     # actuator commands (position targets for <position>)
data.qfrc_applied / data.xfrc_applied                  # direct generalized / Cartesian force injection
model.actuator_gainprm[:, 0] = kp                      # position servo: gain kp, damping via kv
model.actuator_biasprm[:, 2] = -kv                     # (ctrl = kp*target; bias = -kv*qvel - kp*qpos)
mujoco.mj_forward(model, data)                         # recompute sensors/derived without stepping
# Offscreen RGB (classic renderer):
renderer = mujoco.Renderer(model, height=480, width=640)
renderer.update_scene(data, camera="wrist_cam")        # named <camera> from MJCF
rgb = renderer.render()                                # HxWx3 uint8
```

Sources: Python API docs https://mujoco.readthedocs.io/en/stable/python.html (MjModel/MjData/mj_step);
actuator `<position kp= kv=>` semantics: https://mujoco.readthedocs.io/en/stable/XMLreference.html (actuator/position);
sensors (`<jointpos>`, `<framelinvel>`, `<touch>`…): XMLreference; cameras: `<camera name= mode= pos=>` in modeling docs.

### 2.4 SO-101 MJCF/URDF availability

Verified via GitHub API listing of https://github.com/TheRobotStudio/SO-ARM100/tree/main/Simulation/SO101:

| File | URL |
|---|---|
| **`so101_new_calib.xml`** (MJCF, current calibration) | https://github.com/TheRobotStudio/SO-ARM100/blob/main/Simulation/SO101/so101_new_calib.xml |
| `so101_new_calib_camera.xml` (MJCF + camera) | …/blob/main/Simulation/SO101/so101_new_calib_camera.xml |
| `so101_new_calib.urdf`, `so101_leader_new_calib.urdf` | same directory |
| `scene.xml`, `joints_properties.xml`, `so101_old_calib.*` | same directory |
| BOM/assembly README | https://github.com/TheRobotStudio/SO-ARM100 (linked from LeRobot's SO-101 docs) |

LeRobot ships kinematics/PLACO assets for SO-101 behind the `kinematics` extra (`placo` dep), but I could not
confirm an exact in-repo SO-101 MJCF path — use the TheRobotStudio files above **[unverified: exact LeRobot path]**.
LeRobot's own MuJoCo env lives at `src/lerobot/rl/gym_manipulator.py` (verified) and gym-hil ships its own
Panda MJCF models (il_sim docs).

### 2.5 Performance on a 32-thread box (no CUDA)

- **Per-thread `mjData` sampling** (the recommended pattern — MuJoCo "was designed for multi-threading"):
  create one `MjData` per thread and step them independently (OpenMP template shown in docs).
  https://mujoco.readthedocs.io/en/stable/programming/simulation.html#multithreading
- **Within-step parallelism**: with a thread pool (`mju_threadpool`), parts of the pipeline (collision detection,
  constraint solving **across islands**) run on worker threads. "Sleeping islands" is the documented feature
  (changelog: https://github.com/google-deepmind/mujoco/blob/main/doc/changelog.rst).
- **`mujoco.rollout`** — vectorized open-loop rollouts on an internal thread pool: pass a *sequence* of `MjData`
  (one per thread) and trajectories run in parallel; `rollout.Rollout(nthread=N)` context manager or
  `persistent_pool=True` reuse the pool; `shutdown_persistent_pool()` to close.
  https://mujoco.readthedocs.io/en/stable/python.html (rollout section) + source
  https://github.com/google-deepmind/mujoco/blob/main/python/mujoco/rollout.py
- **MJX** (JAX port): MJX-JAX "runs on Nvidia and AMD GPUs" (per JAX platform support) plus CPU/TPU; **MJX-Warp
  targets NVIDIA GPUs specifically**. Practical verdict for us: MJX-JAX-on-CPU is possible but usually slower than
  plain multithreaded C MuJoCo at our model sizes; MJX-Warp is off the table (no NVIDIA).
  https://mujoco.readthedocs.io/en/stable/mjx.html (intro: "MJX-JAX runs on… Nvidia and AMD GPUs")
- **Gymnasium**: `gymnasium.envs.mujoco.MujocoEnv` wraps MuJoCo (https://gymnasium.farama.org/api/mujoco/);
  for custom arms a minimal `gymnasium.Env` subclass (code below) is simpler and dependency-light.

---

## 3. Minimal working code

### 3.1 MuJoCo headless model + step loop + offscreen RGB render

```python
# pip install mujoco (or mujoco-core for headless)   ; export MUJOCO_GL=egl (or osmesa)
import os
os.environ.setdefault("MUJOCO_GL", "egl")  # egl = AMD/Mesa hardware path; osmesa = CPU fallback

import mujoco

model = mujoco.MjModel.from_xml_path("so101_new_calib.xml")  # TheRobotStudio SO-101 MJCF
data  = mujoco.MjData(model)

# drive joints with position actuators (names from the MJCF)
for name, target in {"1": 0.1, "2": -0.3, "3": 0.5}.items():
    data.ctrl[model.actuator(name).id] = target

for _ in range(200):
    mujoco.mj_step(model, data)

renderer = mujoco.Renderer(model, height=480, width=640)
renderer.update_scene(data, camera=mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_CAMERA, 0) if False else None)
# If the MJCF has a named camera, use renderer.update_scene(data, camera="my_cam")
frame = renderer.render()          # HxWx3 uint8 — feed straight into the dataset writer below
renderer.close()
```

### 3.2 Minimal Gymnasium env (custom, no gymnasium-MujocoEnv plumbing)

```python
import os; os.environ.setdefault("MUJOCO_GL", "egl")
import gymnasium as gym
import mujoco, numpy as np
from gymnasium import spaces

class SO101PickEnv(gym.Env):
    metadata = {"render_modes": ["rgb_array"]}

    def __init__(self, xml_path, n_joints=6):
        self.model = mujoco.MjModel.from_xml_path(xml_path)
        self.data = mujoco.MjData(self.model)
        self.n_joints = n_joints
        self.action_space = spaces.Box(-1.0, 1.0, shape=(n_joints,), dtype=np.float32)
        self.observation_space = spaces.Box(-np.inf, np.inf, shape=(2 * n_joints,), dtype=np.float32)

    def _obs(self):
        return np.concatenate([self.data.qpos[: self.n_joints],
                               self.data.qvel[: self.n_joints]]).astype(np.float32)

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        mujoco.mj_resetData(self.model, self.data)
        return self._obs(), {}

    def step(self, action):
        self.data.ctrl[: self.n_joints] = action          # position targets
        mujoco.mj_step(self.model, self.data, nstep=10)   # sim 10x per control step
        reward = -float(np.linalg.norm(self.data.qvel[: self.n_joints]))  # placeholder
        return self._obs(), reward, False, False, {}

    def render(self):
        if not hasattr(self, "_r"):
            self._r = mujoco.Renderer(self.model, 480, 640)
        self._r.update_scene(self.data)
        return self._r.render()
```

### 3.3 Convert episode dicts → LeRobotDataset v3 (with camera stream)

Verified against `LeRobotDataset.create/add_frame/save_episode/finalize` docstrings (lerobot 0.7 source) and the
v3 docs "Common Issues" (`finalize()` is mandatory).

```python
import numpy as np
from lerobot.datasets.lerobot_dataset import LeRobotDataset

FPS = 30
IMG_SHAPE = (480, 640, 3)   # HWC uint8

features = {
    "observation.state":     {"dtype": "float32", "shape": [6]},
    "action":                {"dtype": "float32", "shape": [6]},   # 6 joints; +1 if gripper counted
    "observation.images.front": {"dtype": "video", "shape": list(IMG_SHAPE)},
}

dataset = LeRobotDataset.create(
    repo_id="local_user/sim_so101_pickplace",   # local-only until you push_to_hub()
    fps=FPS,
    root="data/sim_so101_pickplace",            # local dir; omit for $HF_LEROBOT_HOME default
    features=features,
    robot_type="so101",
    use_videos=True,                            # cameras stored as MP4 (use_videos=False → images)
    image_writer_threads=4,
)

def make_episode(env, policy, n_steps=300, seed=0):
    obs, _ = env.reset(seed=seed)
    frames = []
    for _ in range(n_steps):
        img = env.render()                                   # HWC uint8 from MuJoCo Renderer
        frames.append({
            "observation.state": np.asarray(obs[:6], dtype=np.float32),
            "action": np.asarray(env.action_space.sample(), dtype=np.float32),  # ← your recorded actions
            "observation.images.front": np.asarray(img, dtype=np.uint8),
            "task": "pick the cube",                          # REQUIRED key (verified in source docstring)
        })
    return frames

for ep in episodes:                 # episodes = list of frame-dict lists from your sim/web-simulator recorder
    for frame in ep:
        dataset.add_frame(frame)
    dataset.save_episode()

dataset.finalize()                  # MUST be called before reload/push (docs: parquet corrupt otherwise)
# dataset.push_to_hub()            # optional
```

Then sanity-check: `LeRobotDataset("local_user/sim_so101_pickplace", root="data/sim_so101_pickplace")[0]`
returns tensors incl. `observation.images.front` of shape `[3, 480, 640]`.

### 3.4 Train ACT on it (CLI, CPU)

```bash
lerobot-train \
  --dataset.repo_id=local_user/sim_so101_pickplace \
  --dataset.root=data/sim_so101_pickplace \
  --policy.type=act \
  --policy.device=cpu \
  --steps=5000 \
  --batch_size=8 \
  --save_freq=1000 \
  --output_dir=outputs/train/act_sim_arm \
  --job_name=act_sim_arm \
  --policy.push_to_hub=false
# ACT auto-adapts to the state/action/camera schema saved in the dataset (il_robots docs).
# Tune ACT horizon: --policy.chunk_size / --policy.n_action_steps [names per ACT config — verify locally]
```

**Timing expectation** — the official guide only anchors *GPU/MPS* numbers (ACT: 30–60 min on a 4090 for
5 epochs/45k frames; 6–14 h on M-series MPS) and says "CPU only: don't train"
(https://huggingface.co/docs/lerobot/hardware_guide). For our 32-thread box with a deliberately tiny dataset
(~10 ep × 10 s × 30 fps ≈ 3k frames, 320×240 images, 5k steps) **[estimate: ~1–3 h CPU; start it in background]**.
If it's too slow, shrink images in §3.3 or offload: `lerobot-train ... --job.target=t4-small`.

### 3.5 Inference on CPU

```bash
# CLI (real robot): lerobot-rollout --policy.path=outputs/train/act_sim_arm/checkpoints/last/pretrained_model \
#   --robot.type=so101_follower --robot.port=/dev/ttyACM0 --robot.id=my_arm \
#   --robot.cameras='{front:{type:opencv,index_or_path:0,width:640,height:480,fps:30}}' \
#   --task="pick the cube" --strategy.type=base --inference.type=rtc
```

```python
# Python inference loop on CPU (no hardware):
import torch
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.policies.factory import make_policy   # policy factory used by lerobot-train internally

ds_meta = LeRobotDataset("local_user/sim_so101_pickplace", root="data/sim_so101_pickplace").meta
policy = torch.load("outputs/train/act_sim_arm/checkpoints/last/pretrained_model/policy.pt", map_location="cpu")
policy.eval()

obs = {                                   # must match the dataset's feature names/shapes
    "observation.state": torch.zeros(1, 6),
    "observation.images.front": torch.zeros(1, 3, 480, 640),
}
with torch.inference_mode():
    action = policy.select_action(obs)    # ACT returns action-chunk steps on successive calls
print(action)
```

The obs-dict contract (`select_action`, normalized inputs, `push_to_hub=false` checkpoints under
`checkpoints/last/pretrained_model/`) follows the il_robots tutorial and policy deployment docs
(https://huggingface.co/docs/lerobot/inference). If `torch.load(policy.pt)` differs in your installed version,
prefer the checkpoint-dir loading path shown in `lerobot-rollout` **[API name check flagged: `make_policy`
import path unverified — see unverified list]**.

---

## 4. The 1-day learning loop (timed plan, CPU-first)

| Time | Step | Concrete action |
|---|---|---|
| 09:00–09:45 | Setup | venv + `lerobot[training]` + `mujoco`; download SO-101 MJCF (§2.4); smoke-test §3.1 |
| 09:45–11:00 | Demo collection | Drive the arm in sim (MJCF actuators or gym-hil `PandaPickCubeKeyboard-v0`); log (obs, action, RGB) tuples; or teleop with keyboard if `lerobot[core_scripts]` + X11 |
| 11:00–11:30 | Dataset build | Convert recordings with §3.3. Target: **10–20 episodes, 5–10 s each, same camera + task string** (il_robots "tips": consistent grasps, visible object, do-the-task-yourself-from-camera test) |
| 11:30–11:45 | Sanity check | Reload dataset, view one episode in the Hub visualizer or `lerobot-dataset-viz` |
| 11:45–14:00 | Train ACT (lunch overlaps) | §3.4, 5k steps, batch 8; watch trackio (`trackio show --project lerobot`) |
| 14:00–15:00 | Eval | Roll out the policy in your sim loop (§3.5 obs contract); record success rate over ≥10 fixed seeds |
| 15:00–15:45 | **Failure review** | Watch failures frame-by-frame; classify: gripper timing? start-state distribution? camera crop? |
| 15:45–16:30 | Corrective demos | Add 5–10 episodes targeting the failure mode *only* (same task string; `--resume`-style append via fresh dataset merge or re-record) |
| 16:30–17:30 | Retrain + final eval | Resume from last checkpoint or fresh 5k-step run; measure improvement |
| 17:30–18:00 | Demo prep | Pick best checkpoint, prepare `lerobot-rollout` command + sim GIF |

Loop principle: **short episodes → cheap retrain → error-driven data**, not more hyperparameters (this matches the
il_sim docs' warning to fix the dataset before touching ACT hyperparameters).

---

## 5. Which policy when (decision table)

| Situation | Use | Why | Cost anchor (official, hardware_guide) |
|---|---|---|---|
| Default hackathon: 10–50 short demos, 1 camera, CPU | **ACT** | smallest "Light BC" model, single-shot chunks, auto-adapts to schema | 2–6 GB VRAM @ BS8; CPU-tiny feasible [estimate] |
| Need multi-task prompts in one dataset | SmolVLA or multitask DiT | task-conditioned; SmolVLA needs `lerobot[smolvla]` + GPU | 10–16 GB VRAM |
| Smooth contact-rich trajectories | Diffusion | better multimodality, slower | 8–14 GB VRAM, ~2–4 h/4090 |
| Discrete/action-token RL-adjacent demo | VQ-BeT | Light BC group | 2–6 GB VRAM |
| Closed-loop correction by a human during rollout | DAgger strategy (`lerobot-rollout --strategy.type=dagger`) | HIL data collection built into deployment | n/a |
| RL on real arm with human takeover | HIL-SERL (`lerobot[hilserl]` + gym-hil) | documented RL loop, sim-first path exists (il_sim → hilserl_sim) | see HIL-SERL guide |
| Big VLA flex/finetune | Pi0/Pi0.5/SmolVLA on HF Jobs | `--job.target=a100-large` etc. | 24–40 GB VRAM |

---

## 6. Sources (all fetched 2026-11-24)

- LeRobot docs: index, installation, lerobot-dataset-v3, hardware_guide, so101, il_robots, il_sim (main branch),
  inference — under https://huggingface.co/docs/lerobot/
- LeRobot repo + README: https://github.com/huggingface/lerobot ; source files
  `src/lerobot/datasets/lerobot_dataset.py`, `src/lerobot/utils/feature_utils.py`, `src/lerobot/rl/gym_manipulator.py`
- PyPI JSON: https://pypi.org/pypi/lerobot/json (0.7.0), https://pypi.org/pypi/mujoco/json (4.0.1)
- MuJoCo docs/source: https://mujoco.readthedocs.io/en/stable/programming/rendering.html (GLX/OSMesa/EGL),
  `doc/programming/simulation.rst` (multithreading/islands), `doc/python.rst` (rollout), `doc/mjx.rst` (device
  support), `python/mujoco/rendering/classic/gl_context.py` (MUJOCO_GL), `python/mujoco/rollout.py`
- SO-101 models: https://github.com/TheRobotStudio/SO-ARM100/tree/main/Simulation/SO101
- gym-hil: https://github.com/huggingface/gym-hil ; Gymnasium MuJoCo: https://gymnasium.farama.org/api/mujoco/

## 7. Flagged [unverified] — verify before relying

1. CPU ACT training wall-clock on this box (~1–3 h for the tiny run) — **my estimate**, not an official number;
   official CPU guidance is "don't train, use Colab/Jobs".
2. Exact in-repo path of SO-101 kinematics/MJCF *inside* LeRobot — not confirmed; use TheRobotStudio URLs (verified).
3. ACT extra hyperparameter flag names (`--policy.chunk_size`, `--policy.n_action_steps`) — inferred from ACT
   config conventions; check `python -c "from lerobot.policies.act import ACTConfig"` or `lerobot-train --help`.
4. `torch.load(.../policy.pt)` + `policy.select_action` loading shape — pattern from docs, exact file name in
   0.7 checkpoints not confirmed; prefer `lerobot-rollout`/`make_policy` path.
5. `lerobot-find-cameras` CLI name in 0.7 — older versions had it; not confirmed today.
6. VR/AR teleop specifics: Meta Quest = third-party plugin (README list, verified mention); MediaPipe/ARKit/Apple
   Vision Pro teleop — community tools, not in checked docs.
7. Enumeration of "notable public SO-100/SO-101 datasets" on the Hub — only the three named datasets verified;
   the rest is unenumerated.
