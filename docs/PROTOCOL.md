# Robot Bus Protocol v1

One small, boring contract so that **every** agent, simulator, sensor and controller in the
ecosystem can talk: the Three.js sim, the Python tools, Codex (through a shell), the Laya
System-1 classifier, the local GLM System-2 reasoner, Jev, MediaPipe trackers, and — on the
day — the real arm.

Reference implementation: `agents/hub.py` (relay) and `agents/bus_client.py` (clients).

## Transport

* **WebSocket**, JSON text frames, one envelope per frame.
* Hub: `python agents/hub.py` → `ws://127.0.0.1:8890/ws`.
  If the port is busy the hub walks upward and writes the real port to `runs/bus.port`.
  Clients resolve: explicit URL → `$ROBOT_BUS_URL` → `runs/bus.port` → `8890`.
* Same port speaks HTTP: `GET /health`, `/roster`, `/stats`, `/recent`.

## Envelope

```json
{"v":1,"id":"<uuid>","ts":1729800000.123,"src":"<agent name>","topic":"<dot.topic>",
 "to":"<optional agent name>","data":{...}}
```

| field | meaning |
|---|---|
| `id` | unique per message; replies echo the request's `id` |
| `ts` | epoch seconds (UTC, float) |
| `src` | sender name from the roster |
| `topic` | `kind.subkind` |
| `to` | **optional** — deliver to exactly one client |
| `data` | free-form; the hub never looks inside |

## Session

1. On connect send `bus.hello` → `data: {"name": "...", "roles": ["sim"], "caps": ["ik","rapier"]}`.
   The hub answers `bus.roster` (addressed to you) with `{"you": "<your name>", "clients": [...]}`.
   **Names must be unique** — if taken you are renamed `name#2`; always use the `you` value.
2. `bus.join` / `bus.leave` are broadcast so everyone can track who is online.
3. `bus.sub` → `data: {"topics": ["sim.obs", ...]}` opts in to high-rate topics.

## Delivery rules

* **Blackboard by default:** every client receives every topic, *except* high-rate ones.
* **High-rate (opt-in):** `sim.obs`, `vision.hands`, `vision.tape`, `vision.marker`, `vision.frame`.
  (Keeps a reasoning agent from being flooded at 30 Hz.)
* **Directed:** a message with `"to": "<name>"` goes only to that client.
* **Request/reply:** a request carries `id`; the responder replies with the same `id`,
  `"to": request.src`, `topic = request.data.reply_to || "<src>.reply"`.
* Everything is logged by the hub to `runs/bus/<timestamp>.jsonl` (image payloads stripped).
  **That log is the dataset** for every learning loop in the repo.

## Units and frames

SI everywhere: metres, radians, seconds. **Robot base frame**, right-handed:
`+x` forward into the workspace, `+y` left, `+z` up. (The Three.js page is Y-up and converts
internally: `three.x = x`, `three.y = z`, `three.z = -y`.)

## Topics

### `sim.cmd` → to the simulator (`armsmith-web`)

`data: {"cmd": "<name>", "args": {...}, "reply_to": "<topic, optional>"}`

| cmd | args | reply |
|---|---|---|
| `joint` | `{"q":[rad per joint]}` | — |
| `ee` | `{"pos":[x,y,z], "yaw"?:rad, "pitch"?:rad, "gripper"?:0..1, "mode"?:"absolute"\|"relative"}` | — |
| `gripper` | `{"open":0..1}` | — |
| `scenario` | `{"name":"reach"\|"pick_place"\|"push_to_zone"\|"stack"}` | — |
| `reset` | `{"scenario"?:str, "seed"?:int}` | — |
| `mode` | `{"control":"ik"\|"joint"\|"script"\|"mocap"\|"off"}` | — |
| `play` | `{"actions":[[...],...], "fps":30}` | — |
| `snapshot` | `{"w":640,"h":480,"cam":"free"\|"wrist"\|"env"}` | `{"jpeg_b64":..., "cam":..., "step":...}` |
| `set` | `{"obs_hz":30, "record":true}` | — |
| `ping` | `{}` | `{"pong":true,"step":n}` |

### `sim.obs` — simulator telemetry (high-rate, default 30 Hz)

```json
{"ep":3,"step":140,"t":4.7,"scenario":"pick_place","control":"ik",
 "q":[...],"dq":[...],"gripper":1.0,"ee":{"pos":[x,y,z],"quat":[w,x,y,z]},
 "objects":[{"id":"cube","pos":[..],"quat":[..],"grasped":false}],
 "goal":{"pos":[..]},
 "progress":{"dist_to_goal":0.071,"reward":-0.4,"stage":"reach|grasp|lift|place|done|fail"},
 "done":false,"success":false,
 "stall":{"stalled":true,"score":0.8,"steps":45,"reasons":["no_progress"]},
 "last_cmd":{"cmd":"ee","args":{...}}}
```

### `sim.event`

`data: {"kind":"episode_start|episode_end|grasp|drop|collision|stall|recovery|scenario_change", "ep":.., "step":.., ...}`

### `vision.hands` (high-rate)

```json
{"hands":[{"handedness":"Right","world":[[x,y,z] × 21],"img":[[x,y,z] × 21],
          "pinch":0.2,"fist":0.1,"ee_target":[x,y,z]}],
 "fps":27.5,"t":12.3}
```
`world` = MediaPipe world landmarks (metres-ish, origin at the hand's geometric centre —
**not** an absolute position). `ee_target` = the retargeted target **in robot base frame**.

### `vision.frame` (high-rate, ≤10 fps) — annotated preview JPEG

`data: {"from":"hands|tape|marker","jpeg_b64":"...","w":1280,"h":720}`

### `vision.tape` (high-rate) — colour/HSV tracker (the "blue tape" lineage)

`data: {"targets":[{"id":1,"cx":0.62,"cy":0.50,"area":0.03,"bbox":[x,y,w,h]}],
         "w":1280,"h":720,"steer":0.24}`  — `steer` ∈ [−1, 1], positive = target is right of centre.

### `vision.marker` (high-rate) — ArUco / AprilTag 6-DoF pose

`data: {"markers":[{"id":0,"pos_m":[x,y,z] (camera frame),"yaw_deg":..}],"w":..,"h":..}`

### `ctl.stall` — the controller's escalation record

`data: {"ep":..,"step":..,"detector":{...},"laya":{...typed verdict, probabilities, confidence},
         "dossier":"<compact state string sent to System 2>"}`

### `ctl.recovery` — a recovery plan was issued

`data: {"ep":..,"step":..,"source":"glm-s2|scripted|human","plan":{...},
         "issued":[{"cmd":"ee","args":{...}}]}`

### `log`

`data: {"level":"info|warn|error","msg":"..."}`

### `train.metrics` — live training telemetry (broadcast, ≤5 Hz)

```json
{"run":"rl_20261124-041200","env":"reach","policy":"PPO","stage":"train|eval|demo",
 "timesteps":123456,"fps":45678,"elapsed_s":12.4,"ep_rew_mean":12.3,"ep_len_mean":95.0,
 "ep_success_rate":0.42,"failure_rate":0.58,"nines":0.237,
 "baseline_failure_rate":0.97,"baseline_nines":0.013,"n_envs":16,"source":"mujoco"}
```

`nines = -log10(failure_rate)` — the hackathon headline metric (99% success = 2 nines).
Publishers include `baseline_*` once a random/scripted baseline has been measured so
dashboards can render before → after.

### Puppet view — "train headless, watch in Three.js"

Any simulator (MuJoCo, an RL worker, a replay) may publish `sim.obs` with its own `src`
(e.g. `"mujoco"`); the web viewer's `?view=puppet` mode renders those states through the
same rig instead of stepping its own physics. `q` is always the 5 joint radians in
ArmConfig order + `gripper` 0..1.

## Ground rules for anything on the bus

1. Never publish raw joint commands outside the arm's limits — symbolic skills only from reasoners.
2. Reset (`sim.cmd reset`) between episodes; always pass a `seed` when you want reproducibility.
3. Image payloads go only in `vision.frame`, `snapshot` replies, at ≤10 fps.
4. Reasoners subscribe to what they need; never assume you are the only one driving the arm.
   Announce takeover with `ctl.recovery` (`"source"` tells everyone who is in control).
