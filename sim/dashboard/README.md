# Mission-control dashboard (`sim/dashboard/`)

The hackathon command centre: one dark, zero-build page (plain HTML/CSS/JS — no bundler,
no CDN, no canvas libs) that watches the **Robot Bus** and answers the only question the
judges care about: *is the loop actually learning?* The five-part loop — run → capture →
find the failure → fix → run again — is visible in one glance.

## Launch (one command)

```bash
bash sim/dashboard/serve.sh        # ensure hub :8890, sim :8891, dashboard :8892
bash sim/dashboard/serve.sh --stop # kill ONLY the pids recorded in runs/dashboard.pids
```

`serve.sh` is idempotent: anything already answering on a port is left alone (and never
killed by `--stop`, since only pids it started are recorded). It prints the URLs:

| URL | what |
|---|---|
| http://127.0.0.1:8892/ | **mission control** (this dashboard) |
| http://127.0.0.1:8891/?view=puppet | puppet viewer (also embedded in the dashboard's iframe) |
| http://127.0.0.1:8891/ | the local three.js sim (drive it yourself) |
| ws://127.0.0.1:8890/ws | the Robot Bus hub (`GET /health /roster /stats /recent`) |

No hub on 8890? `serve.sh` starts one with `sim/py/.venv` (needs the websockets package)
and logs to `runs/dashboard-hub.log`.

Manual alternative (no script): start the hub, then
`python3 -m http.server 8891 --bind 127.0.0.1 --directory sim/armsmith_web` and the same
for `sim/dashboard` on 8892.

## Panels

- **Header row** — run / policy / stage / fps / timesteps / elapsed from the latest
  `train.metrics`; bus-online banner (goes "bus offline — retrying…" and retries every 3 s
  forever; the page never errors).
- **NINES card** — the demo headline number: `nines = −log₁₀(failure_rate)`. Baseline
  nines (from `baseline_failure_rate` / `baseline_nines`) sit beside it with a ▲/▼ arrow
  (before → after). Green = the loop made things more reliable than baseline.
- **Charts** — plain-canvas line charts (autoscaled, gridlines, last-value labels):
  success_rate vs timesteps and ep_rew_mean vs timesteps. Points accumulate client-side
  from `train.metrics` (capped at 2000).
- **Stall loop** — counters accumulated live from the bus: stalls seen (`ctl.stall`,
  deduped per ep:step), recoveries by source (`ctl.recovery.data.source`:
  glm-s2 / scripted / human), escalation ok/fail — an episode that *ends* in success after
  a recovery was issued in it counts as an escalation success (via `sim.event
  episode_end`).
- **Bus roster** — `GET <hub>/roster` every 3 s: name / roles / uptime / rx-tx.
- **Puppet viewer** — iframe of `http://127.0.0.1:8891/?view=puppet` (override with
  `?puppet=<url>`; a `?hub=` on the dashboard is forwarded to the iframe).

Params: `?hub=ws://127.0.0.1:8890/ws` · `?puppet=http://127.0.0.1:8891/?view=puppet`.

## The `train.metrics` contract

The dashboard (and puppet HUD) accept the first present of each alias:

| field | alias | used for |
|---|---|---|
| `run` | `run_name` | header |
| `policy` | `algo` | header |
| `stage` | — | header (`train`/`eval`/…) |
| `timesteps` | `global_step`, `ts` | charts x-axis, header |
| `fps` | — | header |
| `success_rate` | `success_pct` (÷100), `success` | chart + nines |
| `failure_rate` | `1 − success_rate` | nines |
| `baseline_failure_rate` | `baseline_success_rate`, `baseline_nines` | baseline nines |
| `nines` | computed as `−log₁₀(max(failure_rate, 1e-9))` | big number |
| `ep_rew_mean` | `reward_mean`, `rew_mean` | chart |
| `elapsed_s` | — | elapsed |

The trainer just publishes `bus.send("train.metrics", {...})` on the hub — no subscriber
needed (blackboard delivery; the dashboard subscribes anyway).

## Testing / demo without a real trainer

```bash
# fake trainer: rising success curve (baseline_failure_rate 0.97) + 30 Hz 5-joint arm
ROBOT_BUS_URL=ws://127.0.0.1:8890/ws \
  sim/py/.venv/bin/python sim/dashboard/test/fake_publisher.py
# flags: --hz 30 --metrics-every 1 --ramp 120 --start-step 120 --duration 0

# headless test (isolated hub + fake publisher + Chromium DOM assertions)
bash sim/dashboard/test/smoke_dashboard.sh
```

`smoke_dashboard.sh` asserts the nines element holds a number, baseline nines beside it,
the run header filled, the bus banner online, and mujoco-demo on the roster.

## Hackathon demo recipe (2 min before judging)

```bash
bash sim/dashboard/serve.sh
ROBOT_BUS_URL=ws://127.0.0.1:8890/ws sim/py/.venv/bin/python sim/dashboard/test/fake_publisher.py &
# projector → http://127.0.0.1:8892/   (nines climbing, arm mirroring in the iframe)
```

On the day, swap the fake publisher for the real one: the MuJoCo training process
publishes `sim.obs` (puppet view mirrors it) and `train.metrics` (nines climb) — the
same page, no changes. If the venue Wi-Fi dies, everything here is loopback.

## Design notes

- One process per concern; every component survives the hub being down (fetch/WebSocket
  wrapped, retries every 3 s, last-known data stays on screen).
- The dashboard is a passive blackboard reader: it never publishes, never commands.
- `runs/dashboard.pids` is the only state file it owns (`serve.sh`); the bus log stays
  untouched (`runs/bus/*.jsonl` is the dataset).
