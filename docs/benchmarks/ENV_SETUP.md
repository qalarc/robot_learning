# Environment setup — the two venvs

Two separate, never-mixed environments (rule from `AGENTS.md`):

| venv | python | for | reproduce with |
|---|---|---|---|
| `sim/py/.venv` | 3.12 | light: mujoco, opencv, mediapipe, websockets — bus, vision, sim tools | `scripts/setup_sim_env.sh` (documented by that script; not duplicated here) |
| `training/.venv` | 3.12 | heavy: torch + lerobot — datasets, ACT/SmolVLA training | `scripts/setup_training_env.sh` |

Both scripts are idempotent (re-run = verify + no-op when healthy), use `uv`
(`~/.local/bin/uv`), and never need sudo. Never install into system python.

## training/.venv (the CPU-only torch + lerobot stack)

```bash
scripts/setup_training_env.sh          # ~2 min from scratch; instant if already OK
training/.venv/bin/python training/_smoke/smoke_dataset.py     # smoke: build + read dataset
training/.venv/bin/python training/test_converter.py           # converter end-to-end test
```

Installed (2026-11-24): **lerobot 0.7.0, torch 2.15.0+cpu, torchvision 0.29.2+cpu,
torchcodec 0.17.0+cpu, datasets 5.2.0, numpy 2.2.6**, python 3.12.13.
Exact pins: `training/requirements-freeze.txt` (rebuild from it with
`uv pip install --python training/.venv/bin/python -r training/requirements-freeze.txt
--extra-index-url https://download.pytorch.org/whl/cpu` — the `+cpu` pins force the cpu index
for torch packages, PyPI for the rest).

### The CPU-torch-first ordering (why the script is shaped that way)

1. `uv venv training/.venv --python 3.12`
2. **torch from the cpu index FIRST** (`--index-url https://download.pytorch.org/whl/cpu`) so
   nothing later can pull the CUDA build as a dependency.
3. `uv pip install "lerobot[training]"` — its resolver still grabs the **PyPI**
   `torchvision`/`torchcodec` wheels (same version numbers, CUDA builds): they crash at import
   with `RuntimeError: operator torchvision::nms does not exist`. So the script then
4. force-reinstalls `torchvision` + `torchcodec` from the cpu index (`+cpu` wheels), and
5. uninstalls `nvidia-ml-py` — the only `nvidia-*` package that leaks in (via `trackio[gpu]`;
   a pure-Python NVML binding, not CUDA libs).

### The no-nvidia-wheels check (run after ANY install into training/.venv)

```bash
uv pip list --python training/.venv/bin/python | grep -i '^nvidia'   # must print NOTHING
training/.venv/bin/python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
# expect: 2.15.0+cpu False
```
`uv pip check` should also pass (verified compatible, 69 packages).

### Memory / runtime notes (this box: 124 GB RAM + 124 GB zram, 32 threads, NO NVIDIA)

- `free -g` **available** memory is the gate: heavy training only if > 14 GB available.
  (Install itself is light: <1 GB RAM, ~3 GB disk; venv currently ~2.7 GB.)
- Verified run: ACT 11M-param tiny config, batch 2 → **0.3 s/step on CPU**, loss 0.905 after
  step 1. Real ACT (512 dim, resnet18, batch 8+) will be ~50-100× slower per step; budget
  accordingly — keep hackathon training runs to minutes, checkpoint often
  (`--save_checkpoint true --save_freq 500`), never background long runs without checking
  memory first (OOM kills agent panes first by design on this machine).
- OOM popups: relay through `oom-report`, don't paste raw kernel lines.

### Video notes

System **ffmpeg n8.0.1** is detected and used through torchcodec/libav (SVT-AV1 encoder,
CPU-only, no GPU codecs). Datasets built from bus logs are state-only (`use_videos=False` —
the hub strips image payloads, so there is nothing to encode). Camera datasets from the web
sim record MP4 fine on this path; if video ever breaks, pass `use_videos=False` to get PNG
frames instead (smoke-tested).

## ROCm / HIP status on this AMD box

`/opt/rocm` exists on this machine (amdgcn, hiprand, llvm, ...), but the CPU torch wheels
report `torch.version.hip = None` and `torch.cuda.is_available() = False` — **no ROCm/HIP
path is wired up**, and getting one would mean swapping in `torch ...+rocm*` wheels from the
pytorch rocm index (a different, untested stack). Verdict: train on CPU, or on torch ROCm
builds only if a benchmark proves the need. Do not install CUDA torch "just in case" — it
poisons the venv (see check above).
