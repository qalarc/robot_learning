// physics.js — Rapier world: table, arm bodies/joints, task objects.
// TWO PHYSICS MODES:
//   mode "kinematic" (DEFAULT): arm bodies are kinematic-position-based and follow the
//     servo FK exactly (deterministic, demos never break). Task objects stay dynamic.
//     Grasp = attach-on-close (kinematic follow, Gripper.cs "graspAssist" lineage).
//   mode "dynamic": arm bodies are dynamic, chained with Rapier revolute joints driven by
//     PD position motors (configureMotorPosition) toward the (servo-quantised) targets,
//     plus prismatic jaw joints. Experimental — toggle in the HUD (?physics=dynamic).
// All physics runs in the THREE frame (Y-up); frames.js converts at the edges.

import RAPIER from "@dimforge/rapier3d-compat";
import * as THREE from "three";
import { r2t, quatRobotToThree, t2r } from "./frames.js";
import { matToQuat } from "./frames.js";

export const GRAVITY = -9.81;
const FINGERS_GROUP = (0x0001 << 16) | 0xffff;      // membership 1, collide with everything
const HELD_GROUP = (0x0002 << 16) | 0xfffd;         // membership 2, skip fingers (0x0001)
const FINGER_COLLIDER_GROUP = (0x0001 << 16) | 0xfffd; // collide with all except held(2)

export class Physics {
  static async create() {
    await RAPIER.init();
    return new Physics();
  }

  constructor() {
    Physics.RAPIER = RAPIER;
    this.RAPIER = RAPIER;
    this.world = new RAPIER.World({ x: 0, y: GRAVITY, z: 0 });
    this.world.timestep = 1 / 60;
    this.mode = "kinematic";
    this.arm = null;      // { bodies[], joints[], baseBody, jaws[] }
    this.objects = new Map(); // id -> {body, size, grasped, group}
    this.buildTable();
  }

  // ---------------------------------------------------------------- table
  buildTable() {
    // worktop top at three y=0, spanning three x ±0.45, z −0.65..0.05 (robot frame ±0.45 x, −0.05..0.65 fwd)
    const top = RAPIER.ColliderDesc.cuboid(0.45, 0.02, 0.36)
      .setTranslation(0, -0.02, -0.30).setFriction(0.9);
    const topBody = this.world.createRigidBody(RAPIER.RigidBodyDesc.fixed());
    this.world.createCollider(top, topBody);
    // floor well below, so knocked-off objects land (OOB watchdog resets)
    const floor = RAPIER.ColliderDesc.cuboid(3, 0.02, 3).setTranslation(0, -0.78, 0).setFriction(0.8);
    const floorBody = this.world.createRigidBody(RAPIER.RigidBodyDesc.fixed());
    this.world.createCollider(floor, floorBody);
  }

  // ---------------------------------------------------------------- arm
  // Build arm bodies + joints for the current mode. fkJoint(i) supplies {pos, quat} per joint.
  buildArm(cfg, fkSample) {
    this.destroyArm();
    const R = RAPIER, W = this.world;
    const threeQuat = (robotQuat) => {
      const q = quatRobotToThree(robotQuat);
      return { x: q[1], y: q[2], z: q[3], w: q[0] };
    };
    const pose = (i) => fkSample(i); // {pos:[x,y,z] robot, quat:[w,x,y,z] robot}

    const baseBody = W.createRigidBody(RigidBodyDescFixedAt(r2t([0, 0, 0])));
    // pedestal + bracket colliders on the fixed base
    W.createCollider(R.ColliderDesc.cylinder(0.0312, 0.055)
      .setTranslation(r2t([cfg.panPivot[0] / 2, cfg.baseHeight / 2, 0])[0], r2t([cfg.panPivot[0] / 2, cfg.baseHeight / 2, 0])[1], r2t([cfg.panPivot[0] / 2, cfg.baseHeight / 2, 0])[2]), baseBody);
    W.createCollider(R.ColliderDesc.cuboid(0.02, 0.033, 0.02)
      .setTranslation(...r2t([cfg.panPivot[0] + cfg.liftOffset[0] / 2, cfg.liftOffset[1], cfg.baseHeight + cfg.liftOffset[2] / 2])), baseBody);

    const bodies = [], joints = [];
    for (let i = 0; i < 5; i++) {
      const p = pose(i);
      const desc = this.mode === "dynamic"
        ? R.RigidBodyDesc.dynamic().setLinearDamping(0.5).setAngularDamping(1.0)
        : R.RigidBodyDesc.kinematicPositionBased();
      desc.setTranslation(r2t(p.pos)[0], r2t(p.pos)[1], r2t(p.pos)[2])
        .setRotation(threeQuat(p.quat));
      const body = W.createRigidBody(desc);
      bodies.push(body);

      // colliders (body-local, three frame; local Y = bone direction)
      const j = cfg.joints[i];
      if (i === 0) {
        W.createCollider(R.ColliderDesc.cylinder(0.024, 0.034).setTranslation(0, 0.01, 0), body);
      } else if (i === 4) {
        // roll link = palm area
        W.createCollider(R.ColliderDesc.cuboid(0.024, 0.02, 0.024).setTranslation(0, 0.016, 0), body);
      } else {
        W.createCollider(R.ColliderDesc.capsule(Math.max(0.01, j.linkLength / 2 - 0.02), j.linkRadius)
          .setTranslation(0, j.linkLength / 2, 0), body);
      }
    }

    if (this.mode === "dynamic") {
      // chain revolute joints: base->pan (yaw about Y), pan->lift .. wrist->roll (pitch/roll)
      const mk = (parentBody, childBody, anchor1, axis, limits) => {
        const data = R.JointData.revolute(anchor1, { x: 0, y: 0, z: 0 }, axis);
        const joint = W.createImpulseJoint(data, parentBody, childBody, true);
        joint.setLimits(limits[0], limits[1]);
        joint.configureMotorPosition(0, 260, 14);
        joint.setMotorMaxForce(34);
        return joint;
      };
      joints.push(mk(baseBody, bodies[0], { x: r2t(cfg.panPivot)[0], y: r2t(cfg.panPivot)[1], z: r2t(cfg.panPivot)[2] }, { x: 0, y: 1, z: 0 }, [cfg.joints[0].min, cfg.joints[0].max]));
      for (let i = 1; i < 5; i++) {
        // bone vector from joint i-1 origin to joint i origin, in joint i-1 local frame:
        // at zero pose this is straight up the bone dir => three local +Y * linkLength(prev)
        const L = i === 1
          ? Math.hypot(cfg.liftOffset[0], cfg.liftOffset[1], cfg.liftOffset[2])
          : cfg.joints[i - 1].linkLength;
        const axis = i === 4 ? { x: 0, y: 1, z: 0 } : { x: 0, y: 0, z: -1 }; // roll about bone (local Y); pitch about left (local -Z at zero)
        joints.push(mk(bodies[i - 1], bodies[i], { x: 0, y: L, z: 0 }, axis, [cfg.joints[i].min, cfg.joints[i].max]));
      }
    }

    // jaws (dynamic mode only — kinematic fingers are visual + attach-only)
    const jaws = [];
    if (this.mode === "dynamic") {
      for (const sign of [+1, -1]) {
        const p = pose(4);
        const jd = R.RigidBodyDesc.dynamic().setLinearDamping(2).setAngularDamping(2)
          .setTranslation(r2t(p.pos)[0], r2t(p.pos)[1], r2t(p.pos)[2]).setRotation(threeQuat(p.quat));
        const jaw = W.createRigidBody(jd);
        const col = W.createCollider(
          R.ColliderDesc.cuboid(0.006, cfg.gripperLength / 2, 0.015)
            .setTranslation(0, 0.014 + 0.02 + cfg.gripperLength / 2, -sign * (cfg.gripperWidth / 2))
            .setFriction(1.2), jaw);
        col.setCollisionGroups(FINGER_COLLIDER_GROUP);
        const data = R.JointData.prismatic({ x: 0, y: 0.036, z: 0 }, { x: 0, y: 0, z: 0 }, { x: 0, y: 0, z: -1 });
        const joint = W.createImpulseJoint(data, bodies[4], jaw, true);
        joint.setLimits(-cfg.gripperWidth / 2, cfg.gripperWidth / 2);
        joint.configureMotorPosition(0, 200, 10);
        joint.setMotorMaxForce(18);
        jaws.push({ body: jaw, joint, sign });
      }
    }

    this.arm = { cfg, baseBody, bodies, joints, jaws };
    return this.arm;
  }

  destroyArm() {
    if (!this.arm) return;
    for (const j of this.arm.joints) this.world.removeImpulseJoint(j, true);
    for (const jw of this.arm.jaws || []) this.world.removeImpulseJoint(jw.joint, true);
    for (const b of [this.arm.baseBody, ...this.arm.bodies]) this.world.removeRigidBody(b);
    this.arm = null;
  }

  setMode(mode, cfg, fkSample) {
    this.mode = mode === "dynamic" ? "dynamic" : "kinematic";
    return this.buildArm(cfg, fkSample);
  }

  // ---------------------------------------------------------------- per-tick
  // kinematic: pose bodies from FK; dynamic: PD-drive joint motors to servo targets.
  updateArm(angles, servoTargetAngles, fkOut, closeAmount, cfg) {
    const R = this.RAPIER, arm = this.arm;
    if (!arm) return;
    const threeQuat = (robotQuat) => {
      const q = quatRobotToThree(robotQuat);
      return { x: q[1], y: q[2], z: q[3], w: q[0] };
    };
    if (this.mode === "kinematic") {
      for (let i = 0; i < arm.bodies.length; i++) {
        const p = fkOut.joints[i];
        arm.bodies[i].setNextKinematicTranslation({ x: r2t(p.pos)[0], y: r2t(p.pos)[1], z: r2t(p.pos)[2] });
        arm.bodies[i].setNextKinematicRotation(threeQuat(p.quat));
      }
    } else {
      // servo-quantised targets straight into the PD position motors
      for (let i = 0; i < arm.joints.length; i++) {
        arm.joints[i].configureMotorPosition(servoTargetAngles[i], 260, 14);
      }
      // jaws: prismatic motor target = inward displacement from rest (in metres)
      const halfOpen = cfg.gripperWidth / 2;
      const inward = halfOpen - 0.001 - (halfOpen - 0.006) * closeAmount;
      for (const jw of arm.jaws) jw.joint.configureMotorPosition(-jw.sign * inward, 200, 10);
    }
  }

  step() { this.world.step(); }

  // ---------------------------------------------------------------- objects
  // addTaskObject(id, posRobot, opts {size, color, quatRobot})
  addObject(id, posRobot, opts = {}) {
    const size = opts.size ?? 0.045;
    const R = this.RAPIER;
    const t = r2t(posRobot);
    const desc = R.RigidBodyDesc.dynamic().setLinearDamping(0.4).setAngularDamping(0.6)
      .setCcdEnabled(true).setTranslation(t[0], t[1], t[2]);
    const body = this.world.createRigidBody(desc);
    const col = R.ColliderDesc.cuboid(size / 2, size / 2, size / 2)
      .setFriction(0.9).setRestitution(0.05).setDensity(opts.density ?? 140);
    const collider = this.world.createCollider(col, body);
    const rec = { id, body, size, grasped: false, collider, color: opts.color ?? 0xe6c84a, holdOffset: null, holdQuat: null };
    this.objects.set(id, rec);
    return rec;
  }

  removeObject(id) {
    const rec = this.objects.get(id);
    if (!rec) return;
    this.world.removeRigidBody(rec.body);
    this.objects.delete(id);
  }

  setHeldGroups(rec, held) {
    if (!rec.collider) return;
    rec.collider.setCollisionGroups(held ? HELD_GROUP : 0xffff << 16 | 0xffff);
  }

  // grasp attach/detach (Gripper.cs assist lineage): object within graspRadius of the TCP
  // when jaws close (>0.55) is attached; released when jaws open (<0.15).
  updateGrasp(tcpThree, eeQuatThree, closeAmount, graspAssist, eeVelThree) {
    let event = null;
    const heldRec = [...this.objects.values()].find((o) => o.grasped);

    if (graspAssist && closeAmount > 0.55 && !heldRec) {
      let best = null, bestD = 0.12;
      for (const rec of this.objects.values()) {
        if (rec.grasped) continue;
        const p = rec.body.translation();
        const d = Math.hypot(p.x - tcpThree.x, p.y - tcpThree.y, p.z - tcpThree.z);
        if (d < bestD) { bestD = d; best = rec; }
      }
      if (best) {
        best.grasped = true;
        const p = best.body.translation(), q = best.body.rotation();
        const q3 = new THREE.Quaternion(q.x, q.y, q.z, q.w);
        // hold offset relative to the gripper frame (keeps grabbed orientation, Gripper.cs)
        const inv = eeQuatThree.clone().invert();
        best.holdOffset = new THREE.Vector3(p.x - tcpThree.x, p.y - tcpThree.y, p.z - tcpThree.z).applyQuaternion(inv);
        best.holdQuat = inv.clone().multiply(q3);
        if (this.mode === "dynamic") {
          best.body.setBodyType(this.RAPIER.RigidBodyType.KinematicPositionBased, true);
          this.setHeldGroups(best, true);
        }
        event = { kind: "grasp", id: best.id };
      }
    }
    if (closeAmount < 0.15 && heldRec) {
      heldRec.grasped = false;
      if (this.mode === "dynamic") {
        heldRec.body.setBodyType(this.RAPIER.RigidBodyType.Dynamic, true);
        this.setHeldGroups(heldRec, false);
      }
      // inherit EE velocity so a moving release throws naturally
      if (eeVelThree) heldRec.body.setLinvel({ x: eeVelThree.x, y: eeVelThree.y, z: eeVelThree.z }, true);
      event = { kind: "drop", id: heldRec.id };
    }
    // follow: held object rides the gripper
    const held = [...this.objects.values()].find((o) => o.grasped);
    if (held && held.holdOffset) {
      const p = new THREE.Vector3().copy(tcpThree)
        .add(held.holdOffset.clone().applyQuaternion(eeQuatThree));
      const q = eeQuatThree.clone().multiply(held.holdQuat);
      if (this.mode === "dynamic") {
        held.body.setNextKinematicTranslation({ x: p.x, y: p.y, z: p.z });
        held.body.setNextKinematicRotation({ x: q.x, y: q.y, z: q.z, w: q.w });
      } else {
        held.body.setTranslation({ x: p.x, y: p.y, z: p.z }, false);
        held.body.setRotation({ x: q.x, y: q.y, z: q.z, w: q.w }, false);
      }
    }
    return event;
  }

  // snapshot in robot frame for sim.obs
  objectsSnapshot() {
    const out = [];
    for (const rec of this.objects.values()) {
      const p = rec.body.translation(), q = rec.body.rotation();
      const qr = quatThreeToRobotQ(q);
      out.push({ id: rec.id, pos: t2r([p.x, p.y, p.z]), quat: qr, grasped: rec.grasped });
    }
    return out;
  }
}

function RigidBodyDescFixedAt(t) {
  return Physics.RAPIER.RigidBodyDesc.fixed().setTranslation(t[0], t[1], t[2]);
}
Physics.RAPIER = null; // set after init

// three quat {x,y,z,w} -> robot quat [w,x,y,z]
export function quatThreeToRobotQ(q) {
  const { x, y, z, w } = q;
  const m = [
    [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
    [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
    [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
  ];
  // B^T of frames.js B: robot->three coords (t.x=r.x, t.y=r.z, t.z=-r.y)
  const B = [[1, 0, 0], [0, 0, -1], [0, 1, 0]];
  const R = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
  for (let i = 0; i < 3; i++)
    for (let j = 0; j < 3; j++) {
      let s = 0;
      for (let a = 0; a < 3; a++)
        for (let b = 0; b < 3; b++) s += B[a][i] * m[a][b] * B[b][j];
      R[i][j] = s;
    }
  return matToQuat(R);
}
