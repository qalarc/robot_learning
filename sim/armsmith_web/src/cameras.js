// cameras.js — free (orbit) / wrist / env cameras + custom orbit controls.
// Controls: RMB drag = orbit, RMB+wheel = zoom, MMB drag = pan. (LMB + wheel drive the
// IK target — see ui.js — so the camera deliberately avoids them.)

import * as THREE from "three";
import { r2t } from "./frames.js";

export class Cameras {
  constructor(canvas) {
    this.canvas = canvas;
    const aspect = () => canvas.clientWidth / Math.max(1, canvas.clientHeight);

    this.free = new THREE.PerspectiveCamera(50, aspect(), 0.05, 20);
    this.orbit = { theta: 0.9, phi: 1.05, r: 0.95, center: new THREE.Vector3(0.05, 0.10, -0.12) };
    this.applyOrbit();

    this.env = new THREE.PerspectiveCamera(45, aspect(), 0.05, 20);
    this.env.position.set(0.55, 0.85, -0.95);
    this.env.lookAt(0.1, 0.0, -0.25);

    this.wrist = new THREE.PerspectiveCamera(80, aspect(), 0.01, 5);
    this.current = this.free;
    this.mainName = "free";
  }

  applyOrbit() {
    const { theta, phi, r, center } = this.orbit;
    const sp = Math.sin(phi), cp = Math.cos(phi);
    this.free.position.set(
      center.x + r * sp * Math.cos(theta),
      center.y + r * cp,
      center.z + r * sp * Math.sin(theta));
    this.free.lookAt(center);
  }

  orbitBy(dx, dy) {
    this.orbit.theta -= dx * 0.005;
    this.orbit.phi = Math.min(1.5, Math.max(0.15, this.orbit.phi - dy * 0.005));
    this.applyOrbit();
  }
  zoomBy(d) { this.orbit.r = Math.min(2.5, Math.max(0.3, this.orbit.r * (1 + d * 0.001))); this.applyOrbit(); }
  panBy(dx, dy) {
    const c = this.orbit.center;
    // pan in the camera's horizontal plane
    const fwd = new THREE.Vector3(); this.free.getWorldDirection(fwd); fwd.y = 0; fwd.normalize();
    const right = new THREE.Vector3(fwd.z, 0, -fwd.x); // left-handed trick: right = fwd x up
    c.addScaledVector(right, -dx * 0.001 * this.orbit.r);
    c.addScaledVector(fwd, dy * 0.001 * this.orbit.r);
    this.applyOrbit();
  }

  // wrist cam rides the gripper tool frame (three coords)
  updateWrist(eePosThree, eeQuatThree) {
    const fwd = new THREE.Vector3(0, 0, 1).applyQuaternion(eeQuatThree);
    const up = new THREE.Vector3(0, 1, 0).applyQuaternion(eeQuatThree);
    this.wrist.position.copy(eePosThree).addScaledVector(fwd, -0.01);
    const m = new THREE.Matrix4().lookAt(this.wrist.position, eePosThree.clone().addScaledVector(fwd, 0.1), up);
    this.wrist.quaternion.setFromRotationMatrix(m);
  }

  select(name) {
    this.mainName = name;
    this.current = name === "wrist" ? this.wrist : name === "env" ? this.env : this.free;
    this.current.aspect = this.canvas.clientWidth / Math.max(1, this.canvas.clientHeight);
    this.current.updateProjectionMatrix();
  }

  byName(name) { return name === "wrist" ? this.wrist : name === "env" ? this.env : name === "free" ? this.free : this.current; }
}
