# tools_for_codex.md — driving the robot sim from your shell

You are Codex. You work through a shell. This is your control panel for the
Robot Bus: drive the arm, read telemetry, grab camera frames, replay recorded
episodes. Everything speaks protocol v1 (`docs/PROTOCOL.md`) via the hub.

**The one binary:** `sim/py/.venv/bin/python` (venv; do NOT use system python/pip).
Everything below assumes repo root = `/home/fivelidz/projects/GLM_projects/robot_learning`.
Shorthand used in examples:

```bash
cd /home/fivelidz/projects/GLM_projects/robot_learning
alias RBC='sim/py/.venv/bin/python agents/cli.py'      # every example: RBC <cmd>
```

Every subcommand prints compact JSON on stdout and exits **0 on success, 1 on
failure** — so `&&` chains and `if RBC ...; then` work. Add `--pretty` for
readable JSON.

## Before you drive

```bash
RBC roster                                  # who is on the bus? (hub HTTP)
RBC --to fake-sim cmd --json '{"cmd":"ping"}'   # is the target sim answering?
```

If `roster` fails: no hub — start one (`python agents/hub.py`) or fix
`ROBOT_BUS_URL` / `runs/bus.port`. If `ping` times out: the sim named by
`--to` is not connected (see docs/02b_codex_tooling.md).

## The 15 commands you will use most

**1. roster — who's online** (always do this first)

```bash
RBC roster
# {"ok":true,"clients":[{"name":"fake-sim","roles":["sim"],...},...]}
```

**2. ping — is the sim alive** (correlated request/reply)

```bash
RBC --to fake-sim cmd --json '{"cmd":"ping"}'
# {"ok":true,"reply":{"pong":true,"step":42,"ep":0},"from":"fake-sim"}
```

**3. obs — read telemetry** (N frames, one JSON per line)

```bash
RBC --to fake-sim obs --n 3 --hz 5
# {"ep":0,"step":51,"t":1.7,"scenario":"reach","control":"ik","ee_pos":[0.1,0.0,0.3],
#  "gripper":1.0,"dist_to_goal":0.246,"stage":"reach","stalled":false,...}
# omit --n to stream until Ctrl-C
```

**4. reset — start an episode reproducibly** (ALWAYS pass a seed)

```bash
RBC --to fake-sim reset --seed 7
RBC --to fake-sim reset --seed 7 --scenario pick_place
```

**5. scenario — pick the task**

```bash
RBC --to fake-sim scenario pick_place   # reach | pick_place | push_to_zone | stack
```

**6. ee — move the end-effector** (metres, robot base frame; THE safe way to move)

```bash
RBC --to fake-sim ee --x 0.25 --y 0.0 --z 0.10 --grip 1.0
RBC --to fake-sim ee --x 0 --y 0 --z 0.05 --relative   # relative nudge
```

**7. grip — open/close the gripper** (1 = open, 0 = closed)

```bash
RBC --to fake-sim grip 0.0     # close (grasps if an object is within 8 cm)
```

**8. joint — raw joint targets in radians** (debugging only; see rules below)

```bash
RBC --to fake-sim joint --q 0.1 0.2 0.3 0.4 0.5 0.6
```

**9. mode — control mode**

```bash
RBC --to fake-sim mode ik      # ik | joint | script | mocap | off
```

**10. snapshot — grab a camera frame** (writes a JPEG, prints path + size)

```bash
RBC --to fake-sim snapshot --cam wrist --out /tmp/rl_b2/frame.jpg
# {"ok":true,"path":"/tmp/rl_b2/frame.jpg","bytes":331,"cam":"wrist","step":94}
# cam: free | wrist | env ; then read the image or feed it to a vision tool
```

**11. stall — why did it fail?** (ask BEFORE designing any fix)

```bash
RBC stall
# {"ok":true,"ep":0,"step":153,"obs_stall":{"stalled":true,"score":1.0,
#  "steps":152,"reasons":["no_progress"]},"ctl_stall":{...detector+laya verdict...}}
```

**12. tail — recent bus traffic** (topic backlog + live follow)

```bash
RBC tail --topic sim.event --n 5
RBC tail --topic ctl.recovery --n 3
```

**13. cmd — any raw sim.cmd** (`ping`/`snapshot` auto-wait for the reply)

```bash
RBC --to fake-sim cmd --json '{"cmd":"set","args":{"obs_hz":10}}'
RBC --to fake-sim cmd --json '{"cmd":"ee","args":{"pos":[0.2,0.05,0.15],"gripper":0.5}}'
```

**14. demo — scripted reach-grasp-lift smoke test**

```bash
RBC --to fake-sim demo --seed 7
# runs reset→ik→above→descend→close→lift→park, prints final obs
```

**15. replay — re-run a recorded episode** (deterministic regression testing)

```bash
sim/py/.venv/bin/python agents/replay.py runs/bus/<ts>.jsonl --dry-run   # action table
sim/py/.venv/bin/python agents/replay.py runs/bus/<ts>.jsonl --ep 0 --speed 2
sim/py/.venv/bin/python agents/replay.py runs/bus/<ts>.jsonl --export-csv /tmp/rl_b2/actions.csv
```

## Choosing the sim: `--to`

| how the target is picked | precedence |
|---|---|
| `--to <name>` flag (before OR after the subcommand) | 1st |
| `$ROBOT_SIM_NAME` env | 2nd |
| `armsmith-web` (the browser sim) | default |

Bus URL: `--url` flag → `$ROBOT_BUS_URL` → `runs/bus.port` → `ws://127.0.0.1:8890/ws`.

## Envelope / protocol summary

One JSON text frame per message over `ws://127.0.0.1:<port>/ws`:

| field | meaning |
|---|---|
| `v` | protocol version (1) |
| `id` | unique; **replies echo the request's id** |
| `ts` | epoch seconds (UTC float) |
| `src` | sender's roster name |
| `topic` | `kind.subkind` |
| `to` | optional — directed delivery to one client |
| `data` | free-form payload; the hub never looks inside |

Topics you will touch:

| topic | direction | shape |
|---|---|---|
| `sim.cmd` | you → sim | `{"cmd":"ee","args":{"pos":[x,y,z],"gripper":0..1},"reply_to":...}` |
| `sim.obs` | sim → all (30 Hz, opt-in sub) | full telemetry incl. `stall` block |
| `sim.event` | sim → all | `{"kind":"episode_start\|episode_end\|grasp\|drop\|stall\|...","ep":..,"step":..}` |
| `ctl.stall` | controller → all | detector + System-1 verdict + dossier |
| `ctl.recovery` | controller → all | who took over, what plan, which cmds issued |
| `log` | anyone → all | `{"level":"info\|warn\|error","msg":...}` |

`sim.cmd` verbs: `joint{q}` · `ee{pos,yaw?,pitch?,gripper?,mode}` ·
`gripper{open}` · `scenario{name}` · `reset{scenario?,seed?}` ·
`mode{control}` · `play{actions,fps}` · `snapshot{w,h,cam}` → reply ·
`set{obs_hz,record}` · `ping{}` → reply.

Units: SI — metres, radians, seconds. Base frame: `+x` forward, `+y` left,
`+z` up. Workspace box: x 0.05–0.30, y ±0.18, z 0.02–0.25.

## Rules of engagement (hard)

1. **Never send joint targets outside the arm's limits** — and don't use raw
   `joint`/`ee` values outside the workspace box (x 0.05–0.30, y ±0.18,
   z 0.02–0.25). Prefer `ee` with in-box coordinates; reasoners get symbolic
   skills only. Bounds are enforced in `control/glm_s2.py::validate_plan`, not
   trusted to the model.
2. **Reset between episodes, always with a `seed`** (`reset --seed 7`) — the
   bus log is the dataset; seeds make episodes reproducible and replayable.
3. **Reading a snapshot:** the reply's `jpeg_b64` is decoded and written to
   `--out`. Check `bytes` > 0, then treat the path like any image (view it,
   run CV on it). `--cam wrist` = gripper camera, `env` = room, `free` = orbit.
4. **Announce takeovers**: before you start driving outside a script, publish
   `ctl.recovery` (or at least `log`) saying you have control — never assume
   you are the only one moving the arm.
5. **Poll `roster` before driving** — if the sim you target isn't listed, your
   command silently goes nowhere (the CLI fails loudly on a bad `--to`, but a
   disconnected-after-roster sim can still eat a fire-and-forget cmd).
6. **Ask `stall` before designing a fix** — the dossier tells you why it
   failed; don't guess.
7. The hub log `runs/bus/*.jsonl` **is the training dataset** — never truncate
   or edit it mid-run.

## Troubleshooting in 10 seconds

* `bus unreachable ...` → hub down: `python agents/hub.py &` (writes the real
  port to `runs/bus.port`), or wrong `ROBOT_BUS_URL`.
* `no sim.obs within timeout` → no sim connected: start
  `python agents/fake_sim.py` (headless) or open `http://127.0.0.1:8891/`.
* `no reply ... timeout` → your `--to` name isn't a live client: re-check
  `roster`.
* Everything else: `agents/test_cli.sh` proves the whole stack works — run it
  to bisect hub vs sim vs CLI.
