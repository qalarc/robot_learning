# 02b — Codex tooling: how the pieces fit

Companion to `agents/tools_for_codex.md` (the cheat-sheet Codex actually reads)
and `docs/PROTOCOL.md` (the wire contract). This doc is the map: what talks to
what, how URLs resolve, what to do when it doesn't work, and how to test the
whole stack headlessly.

## The pieces

```
                 ┌──────────────────────────── ws://127.0.0.1:<port>/ws
                 │            + HTTP /health /roster /stats /recent
   ┌─────────────┴──┐      ┌────────────────┐      ┌────────────────┐
   │  agents/hub.py │◄────►│ sim page       │      │ python tools   │
   │  (relay, dumb) │      │ armsmith-web   │      │ agents/cli.py  │
   │  - routes by   │      │ (Three.js +    │      │ agents/        │
   │    topic + "to"│      │  Rapier, the   │      │  replay.py     │
   │  - blackboard: │      │  real sim)     │      │ fake_sim.py    │
   │    all topics  │      └────────────────┘      └───────┬────────┘
   │    to all,     │      ┌────────────────┐              │
   │    high-rate   │◄────►│ fake-sim       │      ┌───────┴────────┐
   │    opt-in via  │      │ (headless stub)│      │ Codex          │
   │    bus.sub     │      └────────────────┘      │ (your shell)   │
   │  - logs every- │      ┌────────────────┐      │ agents/cli.py  │
   │    thing to    │◄────►│ controllers/   │      │ + curl/urllib  │
   │    runs/bus/   │      │ models (S1/S2) │      └────────────────┘
   └────────────────┘      └────────────────┘
```

* **hub** (`agents/hub.py`) — dumb relay + roster + logger. One port serves
  WebSocket (`/ws`) and HTTP (`/health`, `/roster`, `/stats`, `/recent`).
  Its JSONL log **is the dataset** for every learning loop.
* **sim page** (`sim/armsmith_web`, served at `http://127.0.0.1:8891/`) — the
  browser sim. Needs WebGL; publishes `sim.obs`/`sim.event`, consumes `sim.cmd`.
* **python tools** — `cli.py` (drive + read), `fake_sim.py` (headless sim),
  `replay.py` (recorded-episode playback). All built on `agents/bus_client.py`
  (`SyncBus` = thread-backed sync facade; `BusClient` = asyncio).
* **Codex** — works through a shell, so `agents/cli.py` *is* its hands. Cheatsheet:
  `agents/tools_for_codex.md`.

Nobody is special: every component is just a client with a name on the roster.

## URL / port resolution

Every tool resolves the bus the same way (see `bus_client.resolve_url`):

1. explicit `--url` flag (e.g. `--url ws://127.0.0.1:8896/ws`)
2. `$ROBOT_BUS_URL` env
3. `runs/bus.port` — the hub writes its actual port here on startup (it walks
   upward if the default is taken)
4. default `ws://127.0.0.1:8890/ws`

Consequences worth knowing:

* Start the hub FIRST; it publishes the real port. If you pin `ROBOT_BUS_URL`
  to a fixed port and that port is taken by something else, the hub will move
  but your clients will still knock on the stale door — pin only when you
  control the port (that's what `agents/test_cli.sh` does on port 8896).
* HTTP endpoints live on the same port: `curl 127.0.0.1:<port>/roster`.
* The target SIM name is a separate resolution: `--to` flag →
  `$ROBOT_SIM_NAME` → `armsmith-web` (the browser sim; registry:
  `agents/registry.json`).

## Testing without a browser: the fake_sim workflow

`agents/fake_sim.py` is a protocol-complete stub: 6 slew-limited joints, an
abstract EE (0.5 m/s), grasp-on-distance, full `sim.obs` schema at 30 Hz with
the stall block, request/reply for `snapshot`/`ping`, `sim.event` on episode
boundaries, deterministic under a seed, and injectable faults:

```bash
sim/py/.venv/bin/python agents/hub.py &                        # or reuse a running one
sim/py/.venv/bin/python agents/fake_sim.py --ep-len 3000 &     # default: ws://...:8890/ws

sim/py/.venv/bin/python agents/cli.py --to fake-sim reset --seed 7
sim/py/.venv/bin/python agents/cli.py --to fake-sim ee --x 0.25 --y 0.1 --z 0.05 --grip 1
sim/py/.venv/bin/python agents/cli.py --to fake-sim demo --seed 7
```

Reproduce the classic stall deterministically:

```bash
sim/py/.venv/bin/python agents/fake_sim.py --fault ik_residual &   # EE stops 7 cm above target
# ...drive EE toward the goal; after 30 steps without progress:
sim/py/.venv/bin/python agents/cli.py stall                        # stalled:true, no_progress
```

`--fault slip` drops a grasped object once lifted >5 cm. After `--ep-len`
steps (default 300) the episode auto-ends and resets, seeded — so long-running
tests keep producing fresh episodes without supervision.

Full stack check in one command: `bash agents/test_cli.sh` — boots a scratch
hub on port 8896 + a fake sim, runs every CLI subcommand, replay dry-run/CSV,
the demo, a bad-target regression, and a fault-injection smoke, kills only its
own processes, prints `CLI TEST: n/n passed`.

## Replay: deterministic regression against the live bus

The hub logs every envelope (image payloads stripped) to
`runs/bus/<timestamp>.jsonl`. `agents/replay.py` extracts the `sim.cmd`
frames, splits them into episodes at each `reset`, and re-sends them at the
recorded pace × `--speed` — same commands, new sim state, comparable outcome:

```bash
sim/py/.venv/bin/python agents/replay.py runs/bus/20261124-033119.jsonl --dry-run
sim/py/.venv/bin/python agents/replay.py runs/bus/20261124-033119.jsonl --ep 0 --speed 4
sim/py/.venv/bin/python agents/replay.py runs/bus/20261124-033119.jsonl --export-csv /tmp/rl_b2/actions.csv
```

This is the "run → capture → find the failure → fix → run again" loop: the
captured `--ep N` becomes the regression suite for the fix.

## Troubleshooting

| symptom | likely cause | fix |
|---|---|---|
| `bus unreachable ...` from any CLI call | hub not running, or stale `ROBOT_BUS_URL` / `runs/bus.port` | start `python agents/hub.py`; check the port it prints; unset a stale `$ROBOT_BUS_URL` |
| CLI hits "404 File not found" on `<port>` | ANOTHER service owns that port (hub walked away to the next one) | read the hub's stdout / `runs/bus.port` for the real port; pin ports only when you own them |
| `no sim.obs within timeout` | no simulator connected | `roster`; start `agents/fake_sim.py` (headless) or the browser page at `http://127.0.0.1:8891/` |
| `no reply ... timeout` on ping/snapshot | target name wrong or sim wedged | `--to <live name from roster>`; restart the sim |
| `no connected client named 'armsmith-web'` | browser sim not open | open `http://127.0.0.1:8891/` in a browser, or use `--to fake-sim` |
| WebGL missing / blank page | headless box, no GPU GL | use `fake_sim.py` — same protocol, no browser; three.js sim needs WebGL2 |
| `stall` shows `ctl_stall: null` but `obs_stall` set | controller (`control/stall_controller.py`) not running | start it; `obs_stall` comes from the sim's own detector meanwhile |
| obs floods your terminal | 30 Hz stream | use `--n` and `--hz` (`--n 3 --hz 5`) |
| everything passes alone, fails together | port collision with another agent's scratch stack | `test_cli.sh` pins 8896 via `ROBOT_BUS_URL`; copy that isolation pattern |

## Style notes (for extending, not driving)

* One process per concern; every component must survive the hub being down
  (clients fail fast with a clear JSON error, exit 1).
* `SyncBus` for scripts/CLIs; `BusClient` inside asyncio programs (see
  `fake_sim.py` for the pattern).
* Any new sim.cmd verb goes in the protocol table first, then fake_sim, then
  cli sugar — the stub is the executable spec.
* Don't edit `hub.py` / `bus_client.py` to add features; they are the frozen
  reference implementation (`agents/test_bus.py` guards them).
