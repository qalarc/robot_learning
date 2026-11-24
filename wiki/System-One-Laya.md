# System One Laya

**Laya is our fine-tuned typed-decision model — not a chat model: a frozen state string in, calibrated probabilities out, in ~1.35 s warm on CPU.** Lineage and gate law: [docs/09_gut_review.md](../docs/09_gut_review.md).

## What it is

Laya comes from **GUT** ("Guided Unconscious Thinking", `github.com/qalarc/gut-finetuned`, HF `Qalarc/Laya-GUT-Finetune`, local `~/projects/GLM_projects/Laya_integrations/` — read-only for us): a pipeline that distils a big model's judgement into a small calibrated classifier (collect → normalise → train RLCD → gate → register → serve), with ~29 domains (1.5k–16k rows each) and 10 registered checkpoints. Here it serves as **System 1** for the `robot-ops` domain: `POST :8798/v1/systemone` with header `X-Laya-Domain: robot-ops`, called by `control/laya_client.py`.

## The frozen robot-ops schema

`control/robot_ops.schema.json` (criteria_version `2026-11-24.1`) defines four heads: `progress` (advancing/stalled/regressing/done/unsafe), `failure_mode` (grip_slip / unreachable_or_ik_residual / collision / bad_perception / controller_error / none), `recoverable` (yes/no), `escalate` (yes/no). **Criteria are frozen** — changing any label after row #1 invalidates the whole dataset; new behaviour means a new domain version. The schema also carries the workspace box (x 0.05–0.30, y ±0.18, z 0.02–0.25 m) and the 10-skill vocabulary System 2 may use.

## How rows are produced

Exactly one code path: the stall controller renders the state template, gets the S2 plan + outcome, and `to_dataset_row` appends a soft-labelled row to `data/robot-ops.jsonl` (see [The Learning Loop](The-Learning-Loop.md)). Rows are never hand-written — dataset shape drift is silent poison (it bit GUT twice).

## Train → gate → register (the gate law)

> Held-out teacher-agreement **≥ 0.85** AND calibration **ECE ≤ 0.10** AND no label receiving <5% probability on >20% of examples. No pass, no register. No exceptions.

Flywheel: copy `data/robot-ops.jsonl` to the Laya repo as `datasets/robot-ops.jsonl` → `python mcp_finetune/train.py --dataset datasets/robot-ops.jsonl --epochs 4` (~1 h/1k rows CPU; local iGPU or free Kaggle T4 also work) → gate table → `gut_register` on PASS → serve.py hot-reloads. GUT experience: calibration (not accuracy) is the usual bottleneck — budget a `--polish-epochs 1` confidence-transfer pass.

## Current dataset status (24 Nov)

**Not trained.** Only **4 real labelled rows** exist; ~250 give an honest r1, ~1.5k the calibration gate. Until a checkpoint passes, serve falls back to the base English model — verdicts are schema-shaped but uncalibrated. That baseline is deliberately shown on the day as the "before" curve.

## Use + feasibility

**FOR**: every stall + a slow heartbeat — never per control tick. **On the one-day clock**: run the loop overnight (fake_sim) to accumulate rows; train r1 whenever ≥250 exist; only the falling-escalation curve depends on it. **Feasibility**: 1.35 s warm / 27 s cold on CPU; if the Laya runner moves to the ROCm torch iGPU path, GUT's own requirement doc suggests ~17–23 ms/decision — per-tick System 1 becomes possible, but that is their repo's call, not ours.

## See also

- [The Learning Loop](The-Learning-Loop.md) — where Laya sits (L1/L2)
- [System Two alexei](System-Two-alexei.md) — the teacher
- [Training](Training.md) — compute options for the fine-tune
