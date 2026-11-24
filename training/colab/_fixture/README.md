# _fixture — pack test input

* `bus_log.jsonl` — synthetic hub log in the exact shape `training/to_lerobot_dataset.py`
  consumes: `sim.cmd` ("ee" commands from "cli") paired with `sim.obs` (from "fake-sim",
  carrying `q`, `gripper`, `scenario`, and the `last_cmd` echo). 2 episodes
  (`reach` 40 frames, `pick_place` 48 frames), ~56 KiB, byte-deterministic.

* `make_fixture.py` — regenerates it (stdlib only):

  ```bash
  training/.venv/bin/python training/colab/_fixture/make_fixture.py
  ```

Purpose: end-to-end test of `scripts/pack_for_colab.sh` without a live sim, and the
local smoke run of the notebook's adapter → train → checkpoint-load path (see
`training/colab/README.md` → Honest verification status). Keep this dir tiny (<5 MB).
