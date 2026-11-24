# training/colab — free cloud GPUs for the learning loop

**One-file handoff**: pack on superlocal → upload to Colab/Kaggle → Run all → download
checkpoints. This is the concrete answer to "can a Colab T4 help?" — yes: superlocal has
no NVIDIA GPU, but the *train* leg of the loop doesn't need one until the end.

Files:

* `robot_learning_colab.ipynb` — the notebook (9 cells; verified against lerobot 0.7.0)
* `_fixture/` — tiny synthetic bus log + generator, used to test `pack_for_colab.sh`

## The 5-step runbook (Colab)

1. **Pack on superlocal** (make sure the work you want is committed — the bundle
   snapshots git HEAD):

   ```bash
   scripts/pack_for_colab.sh --bus-log runs/bus/<latest>.jsonl
   # or web-recorder episodes:
   scripts/pack_for_colab.sh --episodes-dir runs/rl/live_reach_1
   ```

   → `robot_learning_colab_bundle.zip` (~1 MB for repo-only; dataset adds a little).

2. **Upload** the bundle to a new Colab notebook (folder icon → upload). The notebook
   also accepts a bare `dataset.zip`, and *skips uploads entirely* if the dataset is on
   the Hugging Face hub — in that case point the train cell at it:

   ```
   --dataset.repo_id=<user>/<dataset>     # and delete the --dataset.root line
   ```

3. **Runtime → Change runtime type → T4 GPU** (free tier). Kaggle: Settings →
   Accelerator → GPU T4 ×2.

4. **Run all.** Expect ~5 min setup, ~25–40 min ACT training (6000 steps, state-only),
   a sanity L1 print at the end, and `act_so101_checkpoints.zip` downloading.
   See the notebook intro cell for the full time table and the honest "not executed on
   Colab" note. If a lerobot CLI flag ever renames, cell 5 prints `lerobot-train --help`.

5. **Download checkpoints** (`act_so101_checkpoints.zip`), unpack on superlocal, and
   roll the policy in `sim/armsmith_web` — the loop closes there. Update
   `runs/metrics.json`; the final table is nines before/after.

## Kaggle variant

Same notebook, two differences:

* **Data in**: make a Kaggle *Dataset* from the bundle zip (kaggle.com/datasets →
  New Dataset → upload), attach it under **Add Input**. Cell 2 finds `dataset.zip`
  automatically (`/kaggle/input`).
* **Quota**: ~30 h GPU/week — many ACT runs fit; SmolVLA-with-cameras runs do not
  (state-only datasets can't train SmolVLA anyway; it needs camera frames).
* Output lands in `/kaggle/working`; download from the Output tab.

## HF Jobs alternative (one-liner, no browser)

If you have `hf` CLI authed, you can skip Colab entirely with a hosted T4 job
(flag spellings evolve — check `hf jobs run --help` first; not executed from here):

```bash
hf jobs run --target t4-small -- \
  bash -lc "git clone https://github.com/qalarc/robot_learning.git &&
            pip install 'lerobot[training]' &&
            lerobot-train --dataset.repo_id=<user>/<dataset> --policy.type=act \
              --policy.push_to_hub=false --steps=6000 --batch_size=8 \
              --output_dir=/tmp/act_so101 --job_name=so101_hfjobs"
```

Needs the dataset pushed to the HF hub (no zip upload) and pushes the model back to
the hub (`--policy.repo_id=<user>/<model>` instead of `push_to_hub=false` if you want
a specific destination).

## Honest verification status (2026-11-24)

* **Not executed on Colab/Kaggle** — impossible from this machine. JSON-linted, all
  cells compile, and the *code path* was smoke-run locally: the pack script converted
  `_fixture/bus_log.jsonl` (2 eps / 88 frames), the adapter cell logic, the exact
  `lerobot-train` flags, checkpoint layout (`checkpoints/NNNNNN/pretrained_model` +
  `last`), and `get_policy_class(...).from_pretrained` → `select_action` were all
  exercised against lerobot **0.7.0** with the CPU training venv.
* **0.7 quirks baked in** (each one bit the smoke run, hence verified):
  `--dataset.root` is the dataset dir itself; ACT needs `observation.environment_state`
  or images (cell 4 adds it); `--policy.push_to_hub=false` required; existing
  `--output_dir`/dataset dirs fail unless cleared (cells 4/6 clear them — Run-all twice
  is safe); `--dataset.eval_split` needs ≥2 episodes per task.
* `pip install 'lerobot[training]'` on Colab resolving to something newer than 0.7.0
  is the main residual risk — cell 5's `--help` print is the escape hatch.

## Fixture

`_fixture/make_fixture.py` regenerates `_fixture/bus_log.jsonl` (~56 KiB, deterministic)
mimicking fake_sim's bus traffic. Test the whole chain locally:

```bash
training/.venv/bin/python training/colab/_fixture/make_fixture.py
scripts/pack_for_colab.sh --bus-log training/colab/_fixture/bus_log.jsonl --out /tmp/bundle.zip
unzip -l /tmp/bundle.zip
```
