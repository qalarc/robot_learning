"""Gymnasium envs over sim/mujoco/so101_simple/so101_simple.xml + Robot Bus telemetry.

Why: "train in MuJoCo headlessly, watch in Three.js" — these envs give PPO (train_rl.py)
a fast, seeded reach/push task, and `attach_bus()` streams protocol `sim.obs` so the
Three.js puppet viewer can watch a training or demo run live. The bus is best-effort:
a down hub never blocks or crashes training.

XML contract (so101_simple.xml — joint order is FROZEN, do not reorder):
  qpos[0:5]  arm joints (radians): j1_base_yaw(z), j2_shoulder_pitch(y),
             j3_elbow_pitch(y), j4_wrist_pitch(y), j5_wrist_roll(z)
  qpos[5:7]  finger slides (metres): j6_finger_left(y, -0.018..0.002),
             j7_finger_right(y, -0.002..0.018); |slide|=0.018 -> open, ~0 -> closed
  qpos[7:14] cube freejoint (pos xyz, quat wxyz)
  ctrl[0:5]  arm position servos, ctrl[5:7] finger servos
Sites added in place (additive, collision-free): `ee` (fingertip midpoint, in the
wrist_roll body), `target` (reach goal), `zone` (push goal box centre, worldbody).

Frame: the model is already built x-forward / y-left / z-up in the robot base frame
(base_yaw pivots about +z; positive shoulder/elbow pitch tips links toward +x), which
matches docs/PROTOCOL.md — no coordinate conversion is applied or needed.

Action semantics (both envs): action ∈ [-1,1]^5 -> servo target = clip(qpos +
0.25 * action * (jnt_range hi-lo), jnt_range), fingers held open. Episode 150 steps,
frame_skip=10 (dt 0.02 s -> 50 Hz control, 3 s per episode).
"""

from __future__ import annotations

import asyncio
import sys
import threading
import time
from collections import deque
from pathlib import Path

import gymnasium
import mujoco
import numpy as np
from gymnasium import spaces

REPO = Path(__file__).resolve().parents[2]
DEFAULT_XML = REPO / "sim" / "mujoco" / "so101_simple" / "so101_simple.xml"

ARM_JOINT_NAMES = (
    "j1_base_yaw",
    "j2_shoulder_pitch",
    "j3_elbow_pitch",
    "j4_wrist_pitch",
    "j5_wrist_roll",
)
FINGER_JOINT_NAMES = ("j6_finger_left", "j7_finger_right")
FINGER_OPEN_CTRL = np.array([-0.018, 0.018])  # matches the "reach" keyframe
ACTION_SCALE = 0.25  # servo target = qpos + ACTION_SCALE * action * range_width

REACH_SCENARIO = "reach"
PUSH_SCENARIO = "push"


# --------------------------------------------------------------------------- bus
class BusPublisher:
    """Lazy, never-blocking Robot Bus client for high-rate topics.

    Hub down => send() is a no-op and we retry in a daemon thread every 10 s;
    hub up   => sends are fire-and-forget into the bus client's own loop, so a
    stalled socket can never back-pressure the training loop.
    """

    def __init__(self, name: str, url: str | None = None, obs_hz: float = 30.0):
        self.name = name
        self.url = (
            url  # None -> bus_client.resolve_url ($ROBOT_BUS_URL / bus.port / 8890)
        )
        self._min_dt = 1.0 / obs_hz if obs_hz and obs_hz > 0 else 0.0
        self._last: dict[str, float] = {}
        self._bus = None  # SyncBus once connected
        self._loop = None
        self._next_attempt = 0.0
        self._connecting = False
        self._failed = False
        self._lock = threading.Lock()

    # -- connection ------------------------------------------------------
    def _ensure(self) -> None:
        if self._bus is not None or self._connecting:
            return
        now = time.monotonic()
        if now < self._next_attempt:
            return
        self._next_attempt = now + 10.0  # if it fails, wait 10 s before retrying
        self._connecting = True
        threading.Thread(target=self._connect, daemon=True).start()

    def _connect(self) -> None:
        try:
            agents_dir = str(REPO / "agents")
            if agents_dir not in sys.path:
                sys.path.insert(0, agents_dir)
            from bus_client import SyncBus  # lazy: keeps gym-only use dependency-free

            bus = SyncBus(name=self.name, url=self.url, roles=("sim",))
            with self._lock:
                self._bus = bus
                self._loop = bus._loop
        except Exception:
            with self._lock:
                self._bus = None
                self._loop = None
        finally:
            self._connecting = False

    def _mark_dead(self) -> None:
        with self._lock:
            self._bus = None
            self._loop = None
            self._next_attempt = 0.0  # reconnect soon

    # -- rate gate -------------------------------------------------------
    def due(self, topic: str, hz: float | None = None) -> bool:
        bus = self._bus
        if bus is None:
            if self._failed:
                self._failed = False
                self._mark_dead()
            self._ensure()
            return False
        dt = 1.0 / hz if hz else self._min_dt
        return time.monotonic() - self._last.get(topic, 0.0) >= dt

    # -- send (fire-and-forget, never raises) ----------------------------
    def send(self, topic: str, data, hz: float | None = None) -> bool:
        bus, loop = self._bus, self._loop
        if bus is None or loop is None:
            self._ensure()
            return False
        if not self.due(topic, hz):
            return False
        self._last[topic] = time.monotonic()
        try:
            fut = asyncio.run_coroutine_threadsafe(bus.client.send(topic, data), loop)
            fut.add_done_callback(self._on_sent)
        except Exception:
            self._mark_dead()
            return False
        return True

    def _on_sent(self, fut) -> None:
        try:
            if fut.exception() is not None:
                self._failed = True
        except Exception:
            pass

    @property
    def connected(self) -> bool:
        return self._bus is not None

    def close(self) -> None:
        bus = self._bus
        with self._lock:
            self._bus, self._loop = None, None
        if bus is not None:
            try:
                bus.close()
            except Exception:
                pass


def attach_bus(
    env: gymnasium.Env,
    name: str = "mujoco",
    obs_hz: float = 30.0,
    url: str | None = None,
) -> gymnasium.Env:
    """Attach a BusPublisher to an env; sim.obs then streams from reset()/step()."""
    env.bus = BusPublisher(name=name, url=url, obs_hz=obs_hz)
    return env


# --------------------------------------------------------------------------- base
class _SO101Base(gymnasium.Env):
    """Shared plumbing: model load, joint bookkeeping, servo step, bus payload."""

    metadata = {"render_modes": []}

    scenario = "reach"

    def __init__(
        self,
        xml_path: str | Path | None = None,
        frame_skip: int = 10,
        episode_length: int = 150,
        success_threshold: float = 0.015,
        hold_steps: int = 3,
    ):
        xml_path = Path(xml_path) if xml_path else DEFAULT_XML
        self.model = mujoco.MjModel.from_xml_path(str(xml_path))
        self.data = mujoco.MjData(self.model)
        self.frame_skip = int(frame_skip)
        self.episode_length = int(episode_length)
        self.success_threshold = float(success_threshold)
        self.hold_steps = int(hold_steps)
        self.bus: BusPublisher | None = None

        # joint/actuator addresses by name — robust even if someone edits the XML
        jids = [
            mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_JOINT, n)
            for n in ARM_JOINT_NAMES
        ]
        assert all(j >= 0 for j in jids), "arm joints missing from XML"
        self.arm_jids = np.array(jids)
        self.qadr = np.array([self.model.jnt_qposadr[j] for j in jids])
        self.vadr = np.array([self.model.jnt_dofadr[j] for j in jids])
        self.jnt_range = self.model.jnt_range[jids].copy()  # (5,2) radians
        self.range_lo = self.jnt_range[:, 0]
        self.range_hi = self.jnt_range[:, 1]
        self.range_width = self.range_hi - self.range_lo

        fids = [
            mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_JOINT, n)
            for n in FINGER_JOINT_NAMES
        ]
        self.finger_qadr = np.array([self.model.jnt_qposadr[j] for j in fids])

        aids = [
            mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_ACTUATOR, f"a_{n}")
            for n in ARM_JOINT_NAMES
        ]
        faids = [
            mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_ACTUATOR, f"a_{n}")
            for n in FINGER_JOINT_NAMES
        ]
        assert all(a >= 0 for a in aids + faids), "actuators missing from XML"
        self.arm_ctrladr = np.array([self.model.actuator_ctrladr[a] for a in aids])
        self.finger_ctrladr = np.array([self.model.actuator_ctrladr[a] for a in faids])

        self.ee_sid = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_SITE, "ee")
        assert self.ee_sid >= 0, "ee site missing (re-run the XML site patch)"
        self.target_sid = mujoco.mj_name2id(
            self.model, mujoco.mjtObj.mjOBJ_SITE, "target"
        )
        self.zone_sid = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_SITE, "zone")

        # cube free body (used by push env + bus "objects")
        cube_jid = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_JOINT, "cube_free")
        self.cube_bodyid = self.model.jnt_bodyid[cube_jid] if cube_jid >= 0 else -1
        self.cube_qadr = self.model.jnt_qposadr[cube_jid] if cube_jid >= 0 else None
        cube_gid = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_GEOM, "g_cube")
        self.cube_geom_id = int(cube_gid)
        self.gripper_gids = {
            int(mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_GEOM, g))
            for g in ("g_fingertip_left", "g_fingertip_right", "g_palm")
        }

        self._ep = 0
        self._step = 0
        self._held = 0
        self._last_reward = 0.0
        self._last_dist = float("inf")
        self._goal = np.zeros(3)
        self._dist_hist: deque = deque(maxlen=30)
        self._stall_steps = 0

    # -- spaces (set here, dims fixed by subclass obs builder) -----------
    def _arm_action_space(self) -> spaces.Box:
        return spaces.Box(low=-1.0, high=1.0, shape=(5,), dtype=np.float32)

    # -- helpers ---------------------------------------------------------
    def _ee_pos(self) -> np.ndarray:
        return self.data.site_xpos[self.ee_sid].copy()

    def _ee_quat(self) -> np.ndarray:
        quat = np.empty(4)
        mujoco.mju_mat2Quat(quat, self.data.site_xmat[self.ee_sid])
        return quat

    def _gripper_open_frac(self) -> float:
        s_left = self.data.qpos[self.finger_qadr[0]]  # -0.018 (open) .. 0.002 (closed)
        s_right = self.data.qpos[self.finger_qadr[1]]  # -0.002 (closed) .. 0.018 (open)
        spread = (-s_left + s_right) / 2.0  # -0.002 .. 0.018
        return float(np.clip((spread + 0.002) / 0.020, 0.0, 1.0))

    def _cube_pose(self) -> tuple[np.ndarray, np.ndarray]:
        if self.cube_qadr is None:
            return np.zeros(3), np.array([1.0, 0, 0, 0])
        qadr = self.cube_qadr
        return (
            self.data.qpos[qadr : qadr + 3].copy(),
            self.data.qpos[qadr + 3 : qadr + 7].copy(),
        )

    def _cube_grasped(self) -> bool:
        if self.cube_qadr is None:
            return False
        for i in range(self.data.ncon):
            con = self.data.contact[i]
            names = {int(con.geom1), int(con.geom2)}
            if self.cube_geom_id in names and names & self.gripper_gids:
                return True
        return False

    def _objects(self) -> list[dict]:
        pos, quat = self._cube_pose()
        return [
            {
                "id": "cube",
                "pos": [round(float(v), 5) for v in pos],
                "quat": [round(float(v), 5) for v in quat],
                "grasped": self._cube_grasped(),
            }
        ]

    def _stall_state(self) -> dict:
        # deterministic L0-ish heuristic: no 1 mm improvement over the last 30 steps
        self._dist_hist.append(self._last_dist)
        if self._step >= 45 and len(self._dist_hist) >= 30:
            if min(self._dist_hist) - self._last_dist < 0.001:
                self._stall_steps += 1
            else:
                self._stall_steps = 0
        stalled = self._stall_steps > 0
        return {
            "stalled": bool(stalled),
            "score": round(min(1.0, self._stall_steps / 30.0), 3),
            "steps": int(self._stall_steps),
            "reasons": ["no_progress"] if stalled else [],
        }

    def _stage(self, success: bool) -> str:
        return "done" if success else self.scenario

    def bus_payload(self, *, done: bool = False, success: bool = False) -> dict:
        """Full protocol `sim.obs` data dict (docs/PROTOCOL.md)."""
        goal = self._goal
        payload = {
            "ep": self._ep,
            "step": self._step,
            "t": round(float(self.data.time), 4),
            "scenario": self.scenario,
            "control": "rl",
            "q": [round(float(v), 5) for v in self.data.qpos[self.qadr]],
            "dq": [round(float(v), 5) for v in self.data.qvel[self.vadr]],
            "gripper": round(self._gripper_open_frac(), 4),
            "ee": {
                "pos": [round(float(v), 5) for v in self._ee_pos()],
                "quat": [round(float(v), 5) for v in self._ee_quat()],
            },
            "objects": self._objects(),
            "goal": {"pos": [round(float(v), 5) for v in goal]},
            "progress": {
                "dist_to_goal": round(float(self._last_dist), 5),
                "reward": round(float(self._last_reward), 5),
                "stage": self._stage(success),
            },
            "done": bool(done),
            "success": bool(success),
            "stall": self._stall_state(),
        }
        return payload

    def _publish(self, **kw) -> None:
        bus = self.bus
        if bus is None or not bus.due("sim.obs"):
            return
        bus.send("sim.obs", self.bus_payload(**kw))

    # -- gym plumbing ----------------------------------------------------
    def _reset_common(self) -> None:
        mujoco.mj_resetDataKeyframe(self.model, self.data, 0)  # key "reach"
        self._step = 0
        self._held = 0
        self._last_reward = 0.0
        self._dist_hist.clear()
        self._stall_steps = 0

    def _servo_step(self, action: np.ndarray) -> np.ndarray:
        action = np.clip(np.asarray(action, dtype=np.float64).reshape(5), -1.0, 1.0)
        q = self.data.qpos[self.qadr]
        target = np.clip(
            q + ACTION_SCALE * action * self.range_width, self.range_lo, self.range_hi
        )
        self.data.ctrl[self.arm_ctrladr] = target
        self.data.ctrl[self.finger_ctrladr] = FINGER_OPEN_CTRL
        for _ in range(self.frame_skip):
            mujoco.mj_step(self.model, self.data)
        return action

    def close(self):
        if self.bus is not None:
            self.bus.close()
            self.bus = None


# --------------------------------------------------------------------------- reach
class SO101ReachEnv(_SO101Base):
    """Seeded random target above the table, inside reachable space.

    obs (19, float32): [qpos(5), qvel(5), ee_pos(3), target_pos(3), target-ee(3)]
    reward: -||ee-target|| + 10*success(dist<15 mm held 5 steps) - 0.01*||a||^2
    terminated on success, truncated at 150 steps.
    """

    scenario = REACH_SCENARIO

    def __init__(self, **kw):
        kw.setdefault("success_threshold", 0.015)
        super().__init__(**kw)
        self.action_space = self._arm_action_space()
        high = np.full(19, np.inf, dtype=np.float32)  # 5+5+3+3+3 — matches _obs()
        self.observation_space = spaces.Box(-high, high, dtype=np.float32)

    def _sample_goal(self) -> np.ndarray:
        r = self.np_random.uniform(0.12, 0.28)
        phi = self.np_random.uniform(-0.6, 0.6)
        z = self.np_random.uniform(0.06, 0.20)
        return np.array([r * np.cos(phi), r * np.sin(phi), z])

    def _obs(self) -> np.ndarray:
        q = self.data.qpos[self.qadr]
        dq = self.data.qvel[self.vadr]
        ee = self._ee_pos()
        delta = self._goal - ee
        return np.concatenate([q, dq, ee, self._goal, delta]).astype(np.float32)

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self._reset_common()
        self._ep += 1
        self._goal = self._sample_goal()
        self.model.site_pos[self.target_sid] = self._goal
        mujoco.mj_forward(self.model, self.data)
        self._last_dist = float(np.linalg.norm(self._goal - self._ee_pos()))
        info = {
            "seed": seed,
            "success": False,
            "ee_pos": self._ee_pos(),
            "goal": self._goal.copy(),
        }
        if self.bus is not None:
            self.bus.send(
                "sim.event",
                {
                    "kind": "episode_start",
                    "ep": self._ep,
                    "scenario": self.scenario,
                    "seed": seed,
                },
            )
            self._publish()
        return self._obs(), info

    def _dist(self) -> float:
        return float(np.linalg.norm(self._goal - self._ee_pos()))

    def step(self, action):
        action = self._servo_step(action)
        self._step += 1
        dist = self._dist()
        self._last_dist = dist
        success = False
        if dist < self.success_threshold:
            self._held += 1
        else:
            self._held = 0
        if self._held >= self.hold_steps:
            success = True
        reward = -dist + 10.0 * float(success) - 0.01 * float(action @ action)
        self._last_reward = reward
        terminated = success
        truncated = (self._step >= self.episode_length) and not success
        obs = self._obs()
        info = {
            "dist_to_goal": dist,
            "success": success,
            "is_success": success,
            "ee_pos": self._ee_pos(),
            "goal": self._goal.copy(),
            "stall": self._stall_state(),
        }
        if self.bus is not None:
            self._publish(done=terminated or truncated, success=success)
            if terminated or truncated:
                self.bus.send(
                    "sim.event",
                    {
                        "kind": "episode_end",
                        "ep": self._ep,
                        "step": self._step,
                        "success": success,
                    },
                )
        return obs, reward, terminated, truncated, info


# --------------------------------------------------------------------------- push
class SO101PushEnv(_SO101Base):
    """Push the cube into a random zone on the table.

    obs (24, float32): [qpos(5), qvel(5), ee(3), cube(3), zone(3), cube-zone(3)]
    reward: -||cube-zone|| + 10*success(dist<25 mm held 5 steps) - 0.01*||a||^2
    """

    scenario = PUSH_SCENARIO

    def __init__(self, **kw):
        kw.setdefault("success_threshold", 0.025)
        super().__init__(**kw)
        assert self.cube_qadr is not None, "push env needs the cube freejoint"
        if self.zone_sid < 0:
            raise ValueError("push env needs the `zone` site in the XML")
        self.action_space = self._arm_action_space()
        high = np.full(22, np.inf, dtype=np.float32)  # 5+5+3+3+3+3 — matches _obs()
        self.observation_space = spaces.Box(-high, high, dtype=np.float32)

    def _sample_goal(self) -> np.ndarray:
        while True:
            zone = np.array(
                [
                    self.np_random.uniform(0.15, 0.27),
                    self.np_random.uniform(-0.10, 0.10),
                    0.02,
                ]
            )
            cube = np.array(
                [
                    self.np_random.uniform(0.16, 0.24),
                    self.np_random.uniform(-0.08, 0.08),
                    0.02,
                ]
            )
            if np.linalg.norm(zone - cube) > 0.06:
                return zone, cube

    def _obs(self) -> np.ndarray:
        q = self.data.qpos[self.qadr]
        dq = self.data.qvel[self.vadr]
        ee = self._ee_pos()
        cube, _ = self._cube_pose()
        delta = cube - self._goal
        return np.concatenate([q, dq, ee, cube, self._goal, delta]).astype(np.float32)

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self._reset_common()
        self._ep += 1
        self._goal, cube0 = self._sample_goal()
        self.model.site_pos[self.zone_sid] = self._goal
        self.data.qpos[self.cube_qadr : self.cube_qadr + 3] = cube0
        self.data.qvel[:] = 0.0
        mujoco.mj_forward(self.model, self.data)
        cube, _ = self._cube_pose()
        self._last_dist = float(np.linalg.norm(self._goal - cube))
        info = {"seed": seed, "success": False, "cube": cube, "goal": self._goal.copy()}
        if self.bus is not None:
            self.bus.send(
                "sim.event",
                {
                    "kind": "episode_start",
                    "ep": self._ep,
                    "scenario": self.scenario,
                    "seed": seed,
                },
            )
            self._publish()
        return self._obs(), info

    def _dist(self) -> float:
        cube, _ = self._cube_pose()
        return float(np.linalg.norm(self._goal - cube))

    def step(self, action):
        action = self._servo_step(action)
        self._step += 1
        dist = self._dist()
        self._last_dist = dist
        success = False
        if dist < self.success_threshold:
            self._held += 1
        else:
            self._held = 0
        if self._held >= self.hold_steps:
            success = True
        reward = -dist + 10.0 * float(success) - 0.01 * float(action @ action)
        self._last_reward = reward
        terminated = success
        truncated = (self._step >= self.episode_length) and not success
        obs = self._obs()
        cube, _ = self._cube_pose()
        info = {
            "dist_to_goal": dist,
            "success": success,
            "is_success": success,
            "cube": cube,
            "goal": self._goal.copy(),
            "stall": self._stall_state(),
        }
        if self.bus is not None:
            self._publish(done=terminated or truncated, success=success)
            if terminated or truncated:
                self.bus.send(
                    "sim.event",
                    {
                        "kind": "episode_end",
                        "ep": self._ep,
                        "step": self._step,
                        "success": success,
                    },
                )
        return obs, reward, terminated, truncated, info
