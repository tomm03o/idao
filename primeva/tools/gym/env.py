"""Primeva locomotion gym: a procedurally built creature on real Primeva terrain.

Task: follow a commanded forward speed and yaw rate (the MotorCommand the
cognitive brain issues) while staying upright, using as little muscle
activation as possible (metabolic cost), with a periodic gait prior.

Gait prior (Siekmann et al. 2021, periodic reward composition): a phase clock
with the species' stride frequency defines, per foot, when it should bear load
(stance) and when it should be unloaded (swing). This shapes exploration toward
alternating gaits without any motion capture, which does not exist for
extinct animals.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import mujoco
import numpy as np

from bodyplan import build, load_plan

HERE = Path(__file__).resolve().parent


class Terrain:
    """Primeva heightmap patch (from `primeva_cli heightmap`) or flat ground."""

    def __init__(self, path: str | None, flat_size: float = 40.0):
        if path is None:
            self.n = 64
            self.size = flat_size
            self.heights = np.zeros((self.n, self.n), dtype=np.float64)
            self.name = "flat"
        else:
            meta = json.loads(Path(path + ".json").read_text())
            self.n = int(meta["samples"])
            self.size = float(meta["size_m"])
            self.heights = np.fromfile(path + ".f32", dtype=np.float32).astype(np.float64).reshape(self.n, self.n)
            self.name = Path(path).name
        self.elevation = max(float(self.heights.max()), 0.01)

    def hfield_spec(self) -> tuple[int, str]:
        half = self.size / 2.0
        return self.n, f"{half:.4f} {half:.4f} {self.elevation:.4f} 1.0"

    def height_at(self, x: np.ndarray | float, y: np.ndarray | float) -> np.ndarray:
        """Bilinear height in MuJoCo world coordinates (hfield centred at origin;
        rows run along +y, columns along +x)."""
        half = self.size / 2.0
        fx = np.clip((np.asarray(x) + half) / self.size * (self.n - 1), 0, self.n - 1.0001)
        fy = np.clip((np.asarray(y) + half) / self.size * (self.n - 1), 0, self.n - 1.0001)
        i0 = np.floor(fx).astype(int)
        j0 = np.floor(fy).astype(int)
        tx, ty = fx - i0, fy - j0
        h = self.heights
        return (h[j0, i0] * (1 - tx) * (1 - ty) + h[j0, i0 + 1] * tx * (1 - ty) + h[j0 + 1, i0] * (1 - tx) * ty
                + h[j0 + 1, i0 + 1] * tx * ty)


class LocomotionEnv:
    CONTROL_HZ = 50

    def __init__(self, plan_path: str, terrain_path: str | None, actuation: str = "muscle", seed: int = 0,
                 episode_seconds: float = 20.0):
        self.plan = load_plan(plan_path)
        self.terrain = Terrain(terrain_path)
        n, size = self.terrain.hfield_spec()
        self.body = build(self.plan, hfield_n=n, hfield_size=size, actuation=actuation)
        self.actuation = actuation
        self.model = mujoco.MjModel.from_xml_string(self.body.xml)
        # Terrain elevation data, normalised to [0, 1] as MuJoCo expects.
        self.model.hfield_data[:] = (self.terrain.heights / self.terrain.elevation).ravel().astype(np.float32)
        self.data = mujoco.MjData(self.model)
        self.rng = np.random.default_rng(seed)
        self.frame_skip = max(1, int(round(1.0 / (self.CONTROL_HZ * self.model.opt.timestep))))
        self.dt = self.frame_skip * self.model.opt.timestep
        self.max_steps = int(episode_seconds * self.CONTROL_HZ)

        m = self.model
        self.root_qpos = 7
        self.joint_ids = [j for j in range(m.njnt) if m.jnt_type[j] == mujoco.mjtJoint.mjJNT_HINGE]
        self.qpos_idx = np.array([m.jnt_qposadr[j] for j in self.joint_ids])
        self.qvel_idx = np.array([m.jnt_dofadr[j] for j in self.joint_ids])
        self.jnt_range = m.jnt_range[self.joint_ids].copy()
        self.torso_id = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "torso")
        self.foot_geoms = [mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, f + "_g") for f in self.body.feet]
        self.foot_sites = [mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_SITE, f + "_foot") for f in self.body.feet]
        self.ground_geom = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, "ground")
        # Any non-foot geom touching the ground ends the episode (fall).
        foot_and_distal = set(self.foot_geoms)
        for f in self.body.feet:  # metatarsi may brush the ground in a crouch
            g = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, f.replace("_toe", "_metatarsus") + "_g")
            if g >= 0:
                foot_and_distal.add(g)
        # Only feet (and metatarsi in a crouch) may touch the ground. Theropod
        # trackways show no tail-drag marks: the tail was carried, not leaned on.
        # (Allowing tail contact let early policies learn a non-biological
        # "tripod" sitting on the tail.)
        self.allowed_ground = foot_and_distal

        gait = self.plan.get("gait", {})
        self.stride_hz = float(gait.get("stride_frequency_hz", 0.4 * math.sqrt(9.81 / self.body.hip_height)))
        self.duty = float(gait.get("duty_factor", 0.6))
        self.max_speed = float(gait.get("max_speed_mps", 2.0))
        self.speed_curriculum = 0.35  # fraction of max speed sampled; raised by the trainer
        self.stand_h = self.body.standing_height

        # PD gains for the "motor" actuation mode.
        if actuation == "motor":
            self.tau_max = m.actuator_ctrlrange[:, 1].copy()
            self.kp = self.tau_max / 0.35
            self.kd = 0.04 * self.kp

        self.nu = m.nu
        self.act_dim = m.nu
        self.cmd_speed = 0.0
        self.cmd_yaw = 0.0
        self.phase = 0.0
        self.steps = 0
        self.prev_action = np.zeros(self.act_dim)
        self.obs_dim = len(self._observe(dummy=True))

    # ------------------------------------------------------------------ helpers
    def _terrain_samples(self) -> np.ndarray:
        """5x3 grid of terrain heights around the torso, in the heading frame,
        relative to the torso height (what the creature 'sees' of the ground)."""
        pos = self.data.xpos[self.torso_id]
        R = self.data.xmat[self.torso_id].reshape(3, 3)
        fwd = R[:, 0].copy()
        fwd[2] = 0.0
        fwd /= max(1e-6, np.linalg.norm(fwd))
        left = np.array([-fwd[1], fwd[0], 0.0])
        s = self.stand_h
        offs = [(dx, dy) for dx in (-0.5 * s, 0.0, 0.5 * s, 1.0 * s, 1.5 * s) for dy in (-0.4 * s, 0.0, 0.4 * s)]
        xs = np.array([pos[0] + dx * fwd[0] + dy * left[0] for dx, dy in offs])
        ys = np.array([pos[1] + dx * fwd[1] + dy * left[1] for dx, dy in offs])
        return (self.terrain.height_at(xs, ys) - pos[2]) / s

    def _foot_contacts(self) -> np.ndarray:
        f = np.zeros(len(self.foot_geoms))
        force = np.zeros(6)
        for k in range(self.data.ncon):
            c = self.data.contact[k]
            for fi, g in enumerate(self.foot_geoms):
                if (c.geom1 == g and c.geom2 == self.ground_geom) or (c.geom2 == g and c.geom1 == self.ground_geom):
                    mujoco.mj_contactForce(self.model, self.data, k, force)
                    f[fi] += abs(force[0])
        return f / (self.body.total_mass * 9.81)

    def _fell(self) -> bool:
        for k in range(self.data.ncon):
            c = self.data.contact[k]
            if c.geom1 == self.ground_geom and c.geom2 not in self.allowed_ground:
                return True
            if c.geom2 == self.ground_geom and c.geom1 not in self.allowed_ground:
                return True
        return False

    def _observe(self, dummy: bool = False) -> np.ndarray:
        d = self.data
        R = d.xmat[self.torso_id].reshape(3, 3)
        gravity_body = R.T @ np.array([0.0, 0.0, -1.0])
        lin_vel_body = R.T @ d.qvel[0:3]
        ang_vel_body = d.qvel[3:6]
        q = d.qpos[self.qpos_idx]
        qd = d.qvel[self.qvel_idx]
        height = (d.qpos[2] - float(self.terrain.height_at(d.qpos[0], d.qpos[1]))) / self.stand_h
        phase = 2 * math.pi * self.phase
        act = d.act.copy() if self.model.na > 0 else np.zeros(0)
        terrain = np.zeros(15) if dummy else self._terrain_samples()
        contacts = np.zeros(len(self.foot_geoms)) if dummy else self._foot_contacts()
        return np.concatenate([
            [height], gravity_body, lin_vel_body, ang_vel_body * 0.25, q, qd * 0.1, act,
            [self.cmd_speed / self.max_speed, self.cmd_yaw], [math.sin(phase), math.cos(phase)],
            terrain, np.minimum(contacts, 2.0), self.prev_action,
        ]).astype(np.float32)

    # --------------------------------------------------------------------- API
    def reset(self) -> np.ndarray:
        mujoco.mj_resetData(self.model, self.data)
        half = self.terrain.size / 2.0 - 5.0
        x, y = self.rng.uniform(-half, half, size=2)
        yaw = self.rng.uniform(-math.pi, math.pi)
        z = float(self.terrain.height_at(x, y)) + self.stand_h + 0.03
        self.data.qpos[0:3] = (x, y, z)
        self.data.qpos[3:7] = (math.cos(yaw / 2), 0.0, 0.0, math.sin(yaw / 2))
        self.data.qpos[self.qpos_idx] += self.rng.normal(0.0, 0.03, size=len(self.qpos_idx))
        mujoco.mj_forward(self.model, self.data)
        self.steps = 0
        self.phase = self.rng.uniform()
        self.cmd_speed = self.rng.uniform(0.0, self.max_speed * self.speed_curriculum)
        self.cmd_yaw = self.rng.uniform(-0.4, 0.4) if self.rng.uniform() < 0.5 else 0.0
        self.prev_action[:] = 0.0
        return self._observe()

    def set_command(self, speed: float, yaw_rate: float) -> None:
        self.cmd_speed, self.cmd_yaw = speed, yaw_rate

    def _apply_action(self, action: np.ndarray) -> np.ndarray:
        a = np.clip(action, -1.0, 1.0)
        if self.actuation == "muscle":
            # excitation in [0, 1]; centred at 0.5 * (a + 1)
            self.data.ctrl[:] = 0.5 * (a + 1.0)
        else:
            lo, hi = self.jnt_range[:, 0], self.jnt_range[:, 1]
            target = np.where(a >= 0, a * hi, -a * lo)  # 0 = rest pose, +-1 = joint limits
            return target
        return None

    def step(self, action: np.ndarray):
        target = self._apply_action(action)
        energy = 0.0
        for _ in range(self.frame_skip):
            if target is not None:
                q = self.data.qpos[self.qpos_idx]
                qd = self.data.qvel[self.qvel_idx]
                tau = np.clip(self.kp * (target - q) - self.kd * qd, -self.tau_max, self.tau_max)
                self.data.ctrl[:] = tau
                energy += float(np.mean(np.abs(tau * qd) / self.tau_max))
            mujoco.mj_step(self.model, self.data)
        self.steps += 1
        self.phase = (self.phase + self.stride_hz * self.dt) % 1.0

        d = self.data
        R = d.xmat[self.torso_id].reshape(3, 3)
        up = R[2, 2]
        heading = math.atan2(R[1, 0], R[0, 0])
        v_world = d.qvel[0:2]
        v_fwd = v_world[0] * math.cos(heading) + v_world[1] * math.sin(heading)
        yaw_rate = d.qvel[5]
        height = d.qpos[2] - float(self.terrain.height_at(d.qpos[0], d.qpos[1]))

        # --- reward terms ---
        r_vel = math.exp(-((v_fwd - self.cmd_speed) ** 2) / 0.12)
        r_yaw = math.exp(-((yaw_rate - self.cmd_yaw) ** 2) / 0.25)
        r_up = max(0.0, up)
        # Horizontal trunk posture (bird-like theropod posture): sine of the
        # trunk pitch is the world-z component of the body x axis.
        pitch_sin = float(R[2, 0])
        r_posture = math.exp(-((pitch_sin / 0.25) ** 2))
        r_height = math.exp(-(((height - self.stand_h) / (0.15 * self.stand_h)) ** 2))
        contacts = self._foot_contacts()
        # periodic gait prior: foot i is in stance when its phase < duty
        r_gait = 0.0
        for i in range(len(contacts)):
            ph = (self.phase + 0.5 * i) % 1.0
            stance = ph < self.duty
            loaded = contacts[i] > 0.05
            r_gait += 1.0 if stance == loaded else 0.0
        r_gait /= max(1, len(contacts))
        if self.cmd_speed < 0.15:
            r_gait = 1.0 if np.all(contacts > 0.05) else 0.5  # standing still: both feet down
        if self.actuation == "muscle":
            effort = float(np.mean(d.act ** 2)) if self.model.na else 0.0
        else:
            effort = energy / self.frame_skip
        smooth = float(np.mean((action - self.prev_action) ** 2))
        reward = (1.0 * r_vel + 0.3 * r_yaw + 0.2 * r_up + 0.3 * r_posture + 0.3 * r_height + 0.4 * r_gait
                  - 0.15 * effort - 0.05 * smooth + 0.2)
        self.prev_action = np.clip(action, -1.0, 1.0)

        fell = height < 0.5 * self.stand_h or up < 0.45 or abs(pitch_sin) > 0.6 or self._fell()
        terminated = bool(fell)
        truncated = self.steps >= self.max_steps
        if terminated:
            reward -= 2.0
        info = {"v_fwd": v_fwd, "cmd": self.cmd_speed, "up": up, "height": height}
        return self._observe(), float(reward), terminated, truncated, info

    def validate_terrain(self, samples: int = 200) -> float:
        """Max |our bilinear lookup - MuJoCo ray hit| over random points (metres)."""
        geomgroup = np.zeros(6, dtype=np.uint8)
        geomgroup[0] = 1
        worst = 0.0
        half = self.terrain.size / 2.0 - 1.0
        gid = np.zeros(1, dtype=np.int32)
        for _ in range(samples):
            x, y = self.rng.uniform(-half, half, size=2)
            top = self.terrain.elevation + 5.0
            dist = mujoco.mj_ray(self.model, self.data, np.array([x, y, top]), np.array([0, 0, -1.0]), geomgroup, 1, -1, gid)
            if dist >= 0 and gid[0] == self.ground_geom:
                worst = max(worst, abs((top - dist) - float(self.terrain.height_at(x, y))))
        return worst
