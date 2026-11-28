"""Procedural musculoskeletal creature builder: body-plan JSON -> MuJoCo MJCF.

First-principles model (see docs/research/05_biomeccanica_muscoli.md):
  * Segments are capsules. Their density is set so the total equals the body
    mass, with pneumatic (air-sac) segments lighter, as in theropods and
    sauropods.
  * Each hinge DOF gets an antagonistic pair of Hill-type muscles (MuJoCo's
    built-in muscle model: activation dynamics, force-length, force-velocity,
    passive force).
  * Peak isometric force F0 = sigma * PCSA, with sigma = 0.3 MPa (vertebrate
    skeletal muscle). PCSA = muscle volume / fibre length. Muscle volume comes
    from the muscle-mass fraction of the limb (from palaeo reconstructions)
    split across joints.
  * Moment arms scale with segment length, so torque capacity follows
    allometry automatically for any body size.
Coordinate frame: MuJoCo z-up, +x is the creature's forward direction.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

G = 9.81
MUSCLE_DENSITY = 1060.0      # kg/m3
SPECIFIC_TENSION = 3.0e5     # Pa, vertebrate skeletal muscle max isometric stress


@dataclass
class Segment:
    name: str
    length: float
    radius: float
    angle_deg: float          # rest direction in the sagittal plane: 0 = straight down, +90 = forward
    density_factor: float = 1.0


@dataclass
class Joint:
    name: str
    axis: tuple[float, float, float]
    range_deg: tuple[float, float]
    muscle_share: float       # fraction of the chain's muscle mass on this DOF
    moment_arm_k: float       # moment arm = k * segment length (proximal segment of the joint)


@dataclass
class MuscleSpec:
    joint: str
    sign: int                 # +1 / -1: direction the muscle pulls the joint
    f0: float                 # N
    gear: float               # moment arm in metres


@dataclass
class BuiltBody:
    xml: str
    standing_height: float     # torso height above ground in the rest pose
    total_mass: float
    muscles: list[MuscleSpec] = field(default_factory=list)
    feet: list[str] = field(default_factory=list)
    hip_height: float = 0.0


def _seg_vec(length: float, angle_deg: float, up: bool = False) -> tuple[float, float, float]:
    a = math.radians(angle_deg)
    dz = length * math.cos(a)
    return (length * math.sin(a), 0.0, dz if up else -dz)


def _capsule_volume(length: float, radius: float) -> float:
    return math.pi * radius * radius * length + 4.0 / 3.0 * math.pi * radius ** 3


def _fmt(v) -> str:
    return " ".join(f"{x:.5f}" for x in v)


def build(plan: dict, hfield_n: int = 2, hfield_size: str = "20 20 1 0.5", actuation: str = "muscle") -> BuiltBody:
    """Builds the MJCF for a body plan. The terrain hfield is declared with the
    given sample count / size; its elevation data is filled in at runtime.

    actuation = "muscle": antagonistic Hill-type muscle pairs (ctrl = excitation 0..1).
    actuation = "motor":  one torque motor per DOF whose limit is the stronger
                          muscle's peak torque (F0 * moment arm), i.e. the same
                          physiological capacity, driven by a PD controller."""
    mass = float(plan["mass_kg"])
    torso = plan["torso"]
    legs = plan["legs"]
    head = plan.get("head")
    leg_muscle_fraction = float(plan.get("muscle", {}).get("leg_muscle_fraction", 0.25))

    # ---- density so that the summed segment masses equal the target mass ----------
    vol_weighted = _capsule_volume(torso["length"], torso["radius"]) * torso.get("density_factor", 1.0)
    for leg in legs:
        for s in leg["segments"]:
            vol_weighted += 2 * _capsule_volume(s["length"], s["radius"]) * s.get("density_factor", 1.05)
    for chain_key in ("tail", "neck"):
        if plan.get(chain_key):
            for s in plan[chain_key]["segments"]:
                vol_weighted += _capsule_volume(s["length"], s["radius"]) * s.get("density_factor", 1.0)
    if head:
        vol_weighted += _capsule_volume(head["length"], head["radius"]) * head.get("density_factor", 0.9)
    base_density = mass / vol_weighted

    def leg_height(leg: dict) -> float:
        return sum(s["length"] * math.cos(math.radians(s["angle_deg"])) for s in leg["segments"]) + leg["segments"][-1]["radius"]

    hip_height = max(leg_height(l) for l in legs)
    torso_attach_z = -torso["radius"] * 0.3
    stand = hip_height - torso_attach_z

    muscles: list[MuscleSpec] = []
    actuators: list[str] = []
    feet: list[str] = []
    excludes: list[str] = []
    damping = max(0.02, 0.002 * mass ** 0.9)
    armature = 0.0005 * mass ** 0.8

    def add_joint_muscles(joint_name: str, seg: dict, j: dict, muscle_mass: float) -> None:
        # F0 = sigma * PCSA, PCSA = volume / fibre length (fibres ~40% of the segment).
        fibre = max(0.02, 0.4 * seg["length"])
        f0_total = SPECIFIC_TENSION * (muscle_mass / MUSCLE_DENSITY) / fibre
        arm = max(0.005, j["moment_arm_k"] * seg["length"])
        ext = j.get("extensor_fraction", 0.5)
        pair = ((+1, f0_total * ext, "ext"), (-1, f0_total * (1.0 - ext), "flx"))
        for sign, f0, tag in pair:
            muscles.append(MuscleSpec(joint_name, sign, f0, arm))
            if actuation == "muscle":
                actuators.append(f'<muscle name="{joint_name}_{tag}" joint="{joint_name}" gear="{sign * arm:.5f}" '
                                 f'force="{f0:.2f}" timeconst="0.01 0.04"/>')
        if actuation == "motor":
            tau = max(f0 for _, f0, _ in pair) * arm
            actuators.append(f'<motor name="{joint_name}_m" joint="{joint_name}" gear="1" ctrlrange="{-tau:.3f} {tau:.3f}"/>')

    def chain(prefix: str, segs: list[dict], seg_joints: list[list[dict]], start: tuple, up: bool,
              muscle_mass: float, is_limb: bool, tip_geom: str = "") -> list[str]:
        total_share = sum(j["muscle_share"] for js in seg_joints for j in js)
        lines: list[str] = []
        pos = start
        for k, (seg, joints) in enumerate(zip(segs, seg_joints)):
            ind = "  " * (k + 1)
            name = f"{prefix}_{seg['name']}"
            vec = _seg_vec(seg["length"], seg["angle_deg"], up)
            lines.append(f'{ind}<body name="{name}" pos="{_fmt(pos)}">')
            for j in joints:
                jn = f"{prefix}_{j['name']}"
                lo, hi = j["range_deg"]
                lines.append(f'{ind}  <joint name="{jn}" type="hinge" axis="{_fmt(j["axis"])}" range="{lo} {hi}" '
                             f'damping="{damping:.4f}" armature="{armature:.5f}"/>')
                add_joint_muscles(jn, seg, j, muscle_mass * j["muscle_share"] / total_share)
            dens = base_density * seg.get("density_factor", 1.05 if is_limb else 1.0)
            lines.append(f'{ind}  <geom name="{name}_g" type="capsule" fromto="0 0 0 {_fmt(vec)}" '
                         f'size="{seg["radius"]:.5f}" density="{dens:.2f}"/>')
            if k == len(segs) - 1:
                if is_limb:
                    lines.append(f'{ind}  <site name="{name}_foot" pos="{_fmt(vec)}" size="{seg["radius"]:.4f}"/>')
                    feet.append(name)
                if tip_geom:
                    lines.append(f"{ind}  {tip_geom.format(tip=_fmt(vec))}")
            pos = vec
        for k in reversed(range(len(segs))):
            lines.append(f'{"  " * (k + 1)}</body>')
        return lines

    tl, tr = torso["length"], torso["radius"]
    body: list[str] = [
        f'<body name="torso" pos="0 0 {stand:.4f}">',
        '  <freejoint name="root"/>',
        f'  <geom name="torso_g" type="capsule" fromto="{-tl / 2:.4f} 0 0 {tl / 2:.4f} 0 0" size="{tr:.4f}" '
        f'density="{base_density * torso.get("density_factor", 1.0):.2f}"/>',
        '  <site name="imu" pos="0 0 0" size="0.01"/>',
    ]
    for leg in legs:
        # leg_muscle_fraction is the total over all legs; split by the pair's share.
        per_leg = mass * leg_muscle_fraction * leg.get("muscle_mass_share", 1.0 / len(legs)) / 2.0
        for side, sy in (("L", 1.0), ("R", -1.0)):
            prefix = f"{leg['name']}{side}"
            body += chain(prefix, leg["segments"], leg["joints"], (leg["attach_x"], sy * leg["lateral"], torso_attach_z),
                          False, per_leg, True)
            excludes.append(f'<exclude body1="torso" body2="{prefix}_{leg["segments"][0]["name"]}"/>')
    for chain_key in ("tail", "neck"):
        ch = plan.get(chain_key)
        if not ch:
            continue
        tip = ""
        if chain_key == "neck" and head:
            hv = _seg_vec(head["length"], head.get("angle_deg", 100.0), True)
            tip = (f'<geom name="head_g" type="capsule" fromto="{{tip}} {{tip_end}}" size="{head["radius"]:.4f}" '
                   f'density="{base_density * head.get("density_factor", 0.9):.2f}"/>')
            last = _seg_vec(ch["segments"][-1]["length"], ch["segments"][-1]["angle_deg"], True)
            tip = tip.replace("{tip_end}", _fmt(tuple(a + b for a, b in zip(last, hv))))
        x0 = -tl / 2 if chain_key == "tail" else tl / 2
        body += chain(chain_key, ch["segments"], ch["joints"], (x0, 0.0, 0.0), True,
                      mass * float(ch.get("muscle_fraction", 0.04)), False, tip)
        excludes.append(f'<exclude body1="torso" body2="{chain_key}_{ch["segments"][0]["name"]}"/>')
    body.append("</body>")

    nl = "\n"
    xml = f"""<mujoco model="{plan['name']}">
  <compiler angle="degree" autolimits="true"/>
  <option timestep="{plan.get('timestep', 0.0025)}" integrator="implicitfast" iterations="30" ls_iterations="10"/>
  <default>
    <geom friction="1.0 0.02 0.002" condim="3" solref="0.008 1" solimp="0.95 0.99 0.001" rgba="0.62 0.52 0.40 1"/>
    <muscle ctrllimited="true" ctrlrange="0 1"/>
    <motor ctrllimited="true"/>
  </default>
  <asset>
    <hfield name="terrain" nrow="{hfield_n}" ncol="{hfield_n}" size="{hfield_size}"/>
    <texture name="grid" type="2d" builtin="checker" rgb1=".35 .32 .28" rgb2=".42 .38 .33" width="256" height="256"/>
    <material name="ground" texture="grid" texrepeat="16 16"/>
  </asset>
  <worldbody>
    <light name="sun" directional="true" pos="0 0 10" dir="-0.4 0.3 -1"/>
    <geom name="ground" type="hfield" hfield="terrain" material="ground"/>
{nl.join('    ' + line for line in body)}
  </worldbody>
  <contact>
{nl.join('    ' + e for e in excludes)}
  </contact>
  <actuator>
{nl.join('    ' + a for a in actuators)}
  </actuator>
  <sensor>
    <framequat name="torso_quat" objtype="site" objname="imu"/>
    <velocimeter name="torso_vel" site="imu"/>
    <gyro name="torso_gyro" site="imu"/>
  </sensor>
</mujoco>
"""
    return BuiltBody(xml=xml, standing_height=stand, total_mass=mass, muscles=muscles, feet=feet, hip_height=hip_height)


def load_plan(path: str | Path) -> dict:
    return json.loads(Path(path).read_text())


if __name__ == "__main__":
    import sys

    import mujoco

    plan = load_plan(sys.argv[1])
    b = build(plan)
    m = mujoco.MjModel.from_xml_string(b.xml)
    print(f"{plan['name']}: nq={m.nq} nv={m.nv} nu={m.nu} mass={sum(m.body_mass):.2f} kg "
          f"(target {b.total_mass}) standing={b.standing_height:.3f} m feet={b.feet}")
    for i in range(m.nu):
        print(f"  {mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_ACTUATOR, i):22s} F0={m.actuator_gainprm[i, 2]:9.1f} N "
              f"arm={m.actuator_gear[i, 0]:+.4f} m  tau_max={abs(m.actuator_gainprm[i, 2] * m.actuator_gear[i, 0]):7.2f} N*m")
