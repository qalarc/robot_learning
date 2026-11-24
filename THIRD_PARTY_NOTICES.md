# Third-party notices

This repo is MIT (see LICENSE). Bundled third-party assets keep their own licences:

| asset | where | licence |
|---|---|---|
| three.js build | `sim/armsmith_web/vendor/three.*.js` | MIT — https://github.com/mrdoob/three.js |
| three.js STLLoader | `sim/armsmith_web/vendor/loaders/STLLoader.js` | MIT (three.js examples) |
| Rapier3D compat (WASM) | `sim/armsmith_web/vendor/rapier_es_compatible.js` | MIT OR Apache-2.0 — https://github.com/dimforge/rapier |
| SO-101 STL meshes + calibrated MJCF (TheRobotStudio / Hugging Face LeRobot) | `sim/mujoco/so101_official/` (LICENSE there), `sim/armsmith_web/assets/so101/` (LICENSE there) | Apache-2.0 — https://github.com/TheRobotStudio/SO-ARM101 |
| MediaPipe hand landmarker model | `vision/hand_tracking/models/hand_landmarker.task` | Apache-2.0 — https://developers.google.com/mediapipe |
| CC0 hand photo fixture | `vision/hand_tracking/fixtures/` (SOURCES.txt) | CC0 (Wikimedia Commons) |

The design of the web simulator is a port of our Unity project
[armsmith-robot-arms](https://github.com/fivelidz/armsmith-robot-arms).
Project page: https://qalarc.com/projects/robots/
