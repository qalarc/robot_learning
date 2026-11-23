# LeRobot API notes — lerobot 0.7.0, dataset format v3.0 (introspected, not from docs)

**Pin: `lerobot==0.7.0` / `torch==2.15.0+cpu` / `torchvision==0.29.2+cpu` / `torchcodec==0.17.0+cpu` /
`datasets==5.2.0` / python 3.12.13 / `numpy==2.2.6`.** Everything below was introspected from the
installed package on 2026-11-24 (`inspect.signature` + docstrings + executed smoke runs in
`training/_smoke/`). This file is the API contract other agents code against. Re-verify after any
`lerobot` version bump — this library restructures its modules every minor release.

## 0. Gotchas found the hard way (read first)

1. **Never `uv pip install lerobot` alone.** Its resolver pulls `torchvision`/`torchcodec` from
   PyPI — same version numbers, but built against CUDA torch — which crashes at import with
   `RuntimeError: operator torchvision::nms does not exist` on a CPU-only torch. Fix: install
   torch from `--index-url https://download.pytorch.org/whl/cpu` FIRST, then after lerobot,
   force `--reinstall-package torchvision --reinstall-package torchcodec ... --index-url .../cpu`.
   `scripts/setup_training_env.sh` does all of this in order.
2. **`nvidia-ml-py` can leak in** via `trackio[gpu]` (a lerobot dep). It's a pure-Python NVML
   binding, not CUDA wheels — but repo policy is zero `nvidia-*` packages, so the setup script
   uninstalls it.
3. **Image/video features MUST declare `names` with the channel axis**, e.g.
   `names: ["height", "width", "channel"]`. `lerobot.utils.feature_utils.dataset_to_policy_features`
   checks `names[2] in ("channel", "channels")` to decide HWC→CHW; `names=None` crashes
   `make_policy` with `TypeError: 'NoneType' object is not subscriptable`. State/action features
   accept `names: None` or axis dicts (`{"joints": None}`).
4. **`lerobot-train` CLI syntax changed**: it is now tyro-style flags (`--policy.type act
   --steps 1000`), NOT the old draccus `policy.type=act steps=1000` dotted form. Old-style args
   are rejected as "unrecognized arguments".
5. **Disable hub pushes when training locally**: `--policy.push_to_hub false` (defaults to TRUE).
   Also consider `--save_checkpoint false` for smoke runs (a full ACT checkpoint + optimizer
   state is ~45 MB+ and would bloat small dirs).

## 1. `LeRobotDataset` — `lerobot.datasets.lerobot_dataset`

Module-level `CODEBASE_VERSION = "v3.0"` (dataset layout version; loader warns/refuses on
mismatch). Old public docs reference `lerobot.common.datasets.*` / `v2.x` — **gone**. Everything
now lives in `lerobot.datasets.*` (`feature_utils`, `dataset_writer`, `dataset_reader`,
`video_utils`, `image_writer`, `factory`, `sampler`, ...).

### `create()` — write-mode constructor
```python
LeRobotDataset.create(
    repo_id: str,                     # 'user/name' style id, also used as metadata key
    fps: int,                         # frames per second of collection
    features: dict,                   # feature spec, see §2
    root: str | Path | None = None,   # local dir; default $HF_LEROBOT_HOME/{repo_id}
    robot_type: str | None = None,    # stored in metadata (e.g. "so101")
    use_videos: bool = True,          # True: images stored as MP4; False: PNG/image feature
    tolerance_s: float = 1e-4,        # timestamp sync tolerance
    image_writer_processes: int = 0,  # async image writers (0 = threads only)
    image_writer_threads: int = 0,
    video_backend: str | None = None,
    rgb_encoder / depth_encoder ... = None,   # RGBEncoderConfig etc.
) -> LeRobotDataset
```
Returns a write-mode dataset backed by a `DatasetWriter`. The verified write flow (smoke-tested
end-to-end, video path included):

```python
ds = LeRobotDataset.create(repo_id, fps=30, features=features, root=root,
                           robot_type="so101", use_videos=...)
for episode in episodes:
    for frame in episode:
        ds.add_frame({...frame..., "task": "pick_place"})  # 'task' key REQUIRED
    ds.save_episode()      # encodes videos (if any), writes parquet, updates metadata
ds.finalize()              # MANDATORY: writes parquet footers/metadata; idempotent
```
- `add_frame(frame: dict)`: values may be numpy/torch; dtype+shape validated against `features`.
- `save_episode(episode_data: dict | None = None, parallel_encoding: bool = True)`: omit
  `episode_data` to flush the buffer built by `add_frame`.
- `finalize()`: "must be called after data collection/conversion, otherwise footer metadata
  won't be written to the parquet files and the dataset will be invalid."

### `__init__()` — read mode
```python
LeRobotDataset(repo_id, root=None, episodes: list[int] | None = None,
               episode_filter=None, image_transforms=None,
               delta_timestamps: dict[str, list[float]] | None = None,
               tolerance_s=1e-4, revision=None, force_cache_sync=False,
               download_videos=True, video_backend=None, return_uint8=False, ...)
```
Attributes seen after load: `len(ds)` (frames), `ds.num_episodes`, `ds.fps`,
`ds.features` (dict of feature spec incl. auto columns), `ds.meta.tasks` (DataFrame-like:
index `task`, column `task_index`).

### Auto-managed columns (do NOT add these to `features`)
`timestamp` f32[1], `frame_index` i64[1], `episode_index` i64[1], `index` i64[1],
`task_index` i64[1] — see `lerobot.datasets.feature_utils.DEFAULT_FEATURES`. `timestamp`
values are computed for you from `fps` + call order.

### `__getitem__` + `delta_timestamps` (windowed sampling)
`ds[i]` returns one frame (dict of tensors + strings). Passing
`delta_timestamps={"observation.state": [-0.1, 0.0], "action": [0.0, 0.1, 0.2]}` (seconds)
returns stacked windows: `(T, *feature_shape)` float tensors **plus** a boolean
`"<feature>_is_pad"` mask per windowed feature (True where the requested timestamp fell
outside the episode). Verified shapes: state `(2,6)`, `action` `(3,6)`, `action_is_pad (3,)`.

## 2. Feature spec (`features` dict for `create()`)

```python
features = {
    "observation.state":      {"dtype": "float32", "shape": (6,),  "names": {"joints": None}},
    "action":                 {"dtype": "float32", "shape": (4,),  "names": {"joints": None}},
    "observation.images.cam": {"dtype": "video",  # or "image" when use_videos=False
                               "shape": (96, 96, 3),           # HWC at write time
                               "names": ["height", "width", "channel"]},  # REQUIRED, see gotcha 3
}
```
- Feature **name conventions** (policies key off these): `observation.state`,
  `observation.images.<cam>`, `observation.environment_state`, `action`, `reward`.
- Dtypes: numpy-style strings (`"float32"`, `"uint8"`, `"int64"`, `"string"`); images at write
  time are uint8 HWC arrays (writer converts/scales); read-back gives float32 CHW in [0,1].
- Enums: `lerobot.configs.types.FeatureType` → `STATE VISUAL ENV ACTION REWARD LANGUAGE`.
- Validation helpers live in `lerobot.datasets.feature_utils`
  (`validate_frame`, `validate_feature_dtype_and_shape`, `get_hf_features_from_features`).

## 3. Dataloader / collate

No custom collate needed: `LeRobotDataset` is a plain `torch.utils.data.Dataset` of dicts;
standard `DataLoader(ds, batch_size=4, shuffle=True, num_workers=0)` yields
`{key: stacked_tensor}` (`task` becomes `list[str]`). Verified batch keys and shapes:
`observation.state (B,7)`, `action (B,dim)`, `observation.images.cam (B,3,H,W)` float32,
`timestamp (B,)`, `frame_index/episode_index/index/task_index (B,) int64`, `task: list`.
Higher-level: `lerobot.datasets.factory.make_dataset(TrainPipelineConfig)` wires
delta-timestamps from the policy config (`resolve_delta_timestamps`) and image transforms.

## 4. Training entrypoints (console_scripts actually installed — enumerated from metadata)

`lerobot-train`, `lerobot-eval`, `lerobot-record`, `lerobot-replay`, `lerobot-rollout`,
`lerobot-teleoperate`, `lerobot-info`, `lerobot-dataset-viz`, `lerobot-edit-dataset`,
`lerobot-env-server`, `lerobot-policy-server`, `lerobot-find-cameras`, `lerobot-find-port`,
`lerobot-find-joint-limits`, `lerobot-setup-motors`, `lerobot-setup-can`, `lerobot-calibrate`,
`lerobot-annotate`, `lerobot-imgtransform-viz`, `lerobot-build-mp4-sidecar`,
`lerobot-train-tokenizer`, `lerobot-convert-dcp`.
There is **no** `python -m lerobot.scripts.train` anymore — it's
`lerobot.scripts.lerobot_train:main`.

### Minimal verified CPU training run (executed; 1 step, loss 0.905)
```bash
training/.venv/bin/lerobot-train \
  --policy.type act --policy.device cpu --policy.push_to_hub false \
  --policy.dim_model 64 --policy.n_heads 2 --policy.dim_feedforward 128 \
  --policy.n_encoder_layers 1 --policy.n_decoder_layers 1 \
  --policy.chunk_size 10 --policy.n_action_steps 10 --policy.use_vae false \
  --policy.pretrained_backbone_weights null \        # null = no torchvision weight download
  --dataset.repo_id local/my_ds --dataset.root datasets/my_ds \
  --steps 1 --batch_size 2 --num_workers 0 \
  --output_dir training/_smoke/act_ckpt --job_name smoke --save_checkpoint false --log_freq 1
```
Config objects: `lerobot.configs.train.TrainPipelineConfig` (fields: dataset, env, policy,
output_dir, job_name, steps, batch_size, num_workers, optimizer, scheduler, save_checkpoint,
save_freq, trackio, eval, ema, peft, ...), `lerobot.configs.default.DatasetConfig` (repo_id,
root, episodes, video_backend, ...). ACT knobs: `lerobot.policies.act.configuration_act.ACTConfig`.

## 5. Video / ffmpeg on this box

- System **ffmpeg n8.0.1** (found on PATH); video writing used SVT-AV1 via libav, CPU only,
  no GPU codecs involved. torchcodec 0.17.0+cpu decoded the MP4s at read time without issue.
- If video is ever a problem: pass `use_videos=False` to `create()` → images stored as
  PNG/image-feature instead of MP4 (no ffmpeg involved); the smoke script tests that path too.
- The hub strips image payloads from bus logs, so **bus-log-derived datasets are state-only**
  (`use_videos=False`, no image features at all).

## 6. Where our code plugs in

- `training/to_lerobot_dataset.py` — bus log / web-recorder → dataset (uses §1 flow).
- `training/test_converter.py` — fixture + assertions (§3 shapes).
- `training/_smoke/smoke_dataset.py` — reference write/read flow incl. video + PNG paths.
