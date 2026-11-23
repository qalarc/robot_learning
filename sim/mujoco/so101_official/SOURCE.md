# SO-101 official model — provenance

- Files: `Simulation/SO101/so101_new_calib.xml` + `Simulation/SO101/assets/*.stl` (13 meshes)
  + root `LICENSE`, downloaded from
  **https://github.com/TheRobotStudio/SO-ARM100** (branch `main`) via raw.githubusercontent.com
  on **2026-11-24** by the robot_learning bench agent.
- GitHub API was rate-limited, so files were fetched from raw.githubusercontent.com;
  the mesh list was derived from `mesh="..."` references in so101_new_calib.xml
  (meshdir="assets"), and each URL was verified (HTTP 200) before download.
- All files < 3 MB (largest: wrist_roll_pitch_so101_v2.stl, 2.7 MB); total 16 MB.
- Load verification (mujoco 4.0.1): MjModel.from_xml_path OK — nq=6 nv=6 nu=6,
  8 bodies, 30 geoms, steps without warnings.
- Directory layout mirrors the repo (xml sits next to `assets/` so relative meshdir works).
- Licence: TheRobotStudio/SO-ARM100 LICENSE (see LICENSE file here) — check it before
  redistributing anything built on these meshes.
