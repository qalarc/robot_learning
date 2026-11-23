# 02 — The agent network: how everything talks

Two layers: the **Robot Bus** (this repo, event-driven, latency-critical) and the
**qalarc agent ecosystem** (the rest of the machine: MCP servers, consoles, monitors).
They stay loosely coupled on purpose — a hackathon loop must survive the whole internet
being down. docs/PROTOCOL.md is the wire spec; this page is the map.

## Layer 1 — the Robot Bus (ours, port 8890)

```
                 ┌───────────────────────── hub.py (dumb relay + logger) ─────────────────────┐
                 │  everything → runs/bus/*.jsonl (the dataset)   GET /health /roster /stats │
                 └───────────────────────────────────────────────────────────────────────────┘
   armsmith-web ─┤ sim.obs 30Hz, sim.event            (three.js+rapier, :8891, bus client)
   fake-sim ─────┤ same protocol, headless, faults    (testing without a browser)
   mujoco env ───┤ same protocol                     (training/eval physics)
   stall-controller ─ ctl.stall, ctl.recovery, sim.cmd   (the conductor, L0→L4)
   laya (S1) ← HTTP :8798  ·  glm-s2 (Ollama :11434) ← called BY the controller, not on the bus
   hand-tracker ─┤ vision.hands, vision.frame         (MediaPipe → EE teleop)
   tape-tracker / marker-pose ─┤ vision.tape, vision.marker   (OpenCV lineage)
   codex / humans ─┤ sim.cmd via agents/cli.py        (shell-native; Codex reads AGENTS.md)
```

Design rules that make it work: one JSON envelope; blackboard broadcast with high-rate
opt-in; directed messages for request/reply; nobody is a single point of failure except
the hub (and every client survives its absence — reconnect + retry); everything logged.

## Layer 2 — the existing qalarc ecosystem (when to bridge, when not)

| system | where | role | bridge into the bus? |
|---|---|---|---|
| **Laya serve** | `:8798` `mcp_finetune/serve.py` | S1 typed decisions | YES — `control/laya_client.py` (HTTP, `X-Laya-Domain: robot-ops`) |
| **GUT trainer / console** | MCP `gut-trainer`, `:8797` | train/gate/register domains | burst use, offline: rows → train → register → serve hot-reloads |
| **Jev** | MCP `jev_decide` | calibrated remote gates | optional L2 if network is good; default off |
| **Ollama** | `:11434` | S2 `glm-4.7-flash-abl:alexei-v3` | YES — `control/glm_s2.py` |
| **Blender MCP** | blender_* tools | props, URDF→GLB | off-bus; drop files into `sim/armsmith_web/assets/` |
| **nexus / concierge fleet** | other MCPs | investigation/monitoring | NO on the day — different domain, latency, failure modes |
| **Codex** | shell (unlimited on the day) | builder | YES via `agents/cli.py` + `AGENTS.md` |
| **qalcode orchestrator (GLM 5.3 + Flash)** | Task tool | planning/delegation | spawned me; use for big parallel legs |

Rule of thumb: **models are called, sensors publish, controllers orchestrate, humans and
Codex interrupt politely (announce on `ctl.recovery`)**. Anything that must never die
(hub, sim, controller) is one process each, restartable in one command, and its state is
the log — not RAM.

## Port registry (this machine)

| port | what |
|---|---|
| **8890** | Robot Bus hub (fallback walks up; real port → `runs/bus.port`) |
| **8891** | armsmith-web static server |
| **8892** | vision preview page (suggested) |
| 8798 / 8797 | Laya serve / GUT trainer console (existing) |
| 11434 | Ollama |
| 876x–878x, 9200 | existing qalarc services — leave alone |

## Failure modes (designed for)

- Hub down → every client degrades to local operation, reconnects; the sim keeps running
  human control; nothing crashes.
- Laya down → controller fail-opens to S2 directly (logged).
- GLM down/slow → scripted bounded recovery; max 3/episode, then teleop request.
- Bus log grows → it's line-JSONL; rotate by date; never truncate mid-run (it IS the data).
- Two agents fight over the arm → last writer wins per sim tick, but `ctl.recovery`
  announces takeovers; the controller backs off during foreign recoveries.

## Adding a new agent (the 60-second recipe)

1. Pick a unique name; read docs/PROTOCOL.md.
2. `from agents.bus_client import SyncBus` (python) or copy `sim/armsmith_web/src/bus.js`
   (JS) — hello, subscribe, publish.
3. Register it in `agents/registry.json` (name, roles, topics).
4. Never send anything you wouldn't want logged forever.
