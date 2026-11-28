"""Evaluate a trained locomotion policy and film it.

    MUJOCO_GL=osmesa python evaluate.py --run ../../out/gym/runs/dromaeosaur_motor \
        --terrain ../../out/gym/site_505344 --speeds 0.5,1.0,1.5,2.0 --gif out.gif

Metrics per commanded speed (deterministic policy = Gaussian mean):
  speed achieved, survival (fraction of episodes without falling), cost of
  transport proxy (mean actuator effort per metre), stride frequency and duty
  factor measured from foot contacts (compare with the biological targets in
  the body plan: stride ~ 0.4 sqrt(g / hip height), duty factor ~0.6 walking,
  < 0.5 running).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("MUJOCO_GL", "osmesa")
os.environ.setdefault("PYOPENGL_PLATFORM", "osmesa")
for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import mujoco
import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env import LocomotionEnv  # noqa: E402
from ppo import ActorCritic  # noqa: E402


def load_policy(run: Path, which: str):
    ck = torch.load(run / f"{which}.pt", map_location="cpu", weights_only=False)
    ac = ActorCritic(ck["obs_dim"], ck["act_dim"])
    ac.load_state_dict(ck["model"])
    ac.eval()
    mean, var = ck["norm_mean"], ck["norm_var"]
    norm = lambda o: np.clip((o - mean) / np.sqrt(var + 1e-8), -10, 10).astype(np.float32)  # noqa: E731
    return ac, norm, ck["args"]


def episode(env: LocomotionEnv, ac, norm, speed: float, seconds: float, renderer=None, frames=None, frame_every=5):
    obs = env.reset()
    env.set_command(speed, 0.0)
    obs = env._observe()
    contacts_log, effort, dist, fell = [], 0.0, 0.0, False
    x0 = env.data.qpos[0:2].copy()
    steps = int(seconds * env.CONTROL_HZ)
    cam = None
    if renderer is not None:
        cam = mujoco.MjvCamera()
        cam.type = mujoco.mjtCamera.mjCAMERA_TRACKING
        cam.trackbodyid = env.torso_id
        cam.distance = 3.2 * env.stand_h / 0.57
        cam.elevation = -18
        cam.azimuth = 120
    for t in range(steps):
        with torch.no_grad():
            a = ac.pi(torch.from_numpy(norm(obs))).numpy()
        obs, _r, term, _trunc, info = env.step(a)
        env.set_command(speed, 0.0)
        contacts_log.append(env._foot_contacts() > 0.05)
        effort += float(np.mean(np.abs(env.data.ctrl)))
        if renderer is not None and t % frame_every == 0:
            renderer.update_scene(env.data, camera=cam)
            frames.append(renderer.render().copy())
        if term:
            fell = True
            break
    dist = float(np.linalg.norm(env.data.qpos[0:2] - x0))
    dur = len(contacts_log) / env.CONTROL_HZ
    c = np.array(contacts_log, dtype=float)
    duty = float(c.mean()) if len(c) else 0.0
    # stride frequency: touchdowns of foot 0 per second
    td = int(np.sum((c[1:, 0] > 0.5) & (c[:-1, 0] < 0.5))) if len(c) > 1 else 0
    return {"speed": dist / max(dur, 1e-6), "survived": not fell, "seconds": dur, "duty": duty,
            "stride_hz": td / max(dur, 1e-6), "effort_per_m": effort / max(dist, 1e-3)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--run", required=True)
    p.add_argument("--which", default="best")
    p.add_argument("--terrain", default="flat")
    p.add_argument("--speeds", default="0.0,0.5,1.0,1.5,2.0")
    p.add_argument("--episodes", type=int, default=4)
    p.add_argument("--seconds", type=float, default=15.0)
    p.add_argument("--gif", default="")
    p.add_argument("--gif-speed", type=float, default=1.2)
    p.add_argument("--json", default="")
    args = p.parse_args()

    run = Path(args.run)
    ac, norm, targs = load_policy(run, args.which)
    terrain = None if args.terrain == "flat" else args.terrain
    env = LocomotionEnv(targs["plan"], terrain, actuation=targs["actuation"], seed=12345)
    results = {}
    print(f"run {run.name} ({targs['actuation']}), terrain {env.terrain.name}, stride target {env.stride_hz:.2f} Hz")
    print(f"{'cmd m/s':>8} {'speed':>7} {'survive':>8} {'time s':>7} {'duty':>6} {'stride':>7} {'effort/m':>9}")
    for sp in [float(v) for v in args.speeds.split(",")]:
        eps = [episode(env, ac, norm, sp, args.seconds) for _ in range(args.episodes)]
        agg = {k: float(np.mean([e[k] for e in eps])) for k in eps[0]}
        results[sp] = agg
        print(f"{sp:8.2f} {agg['speed']:7.2f} {100 * agg['survived']:7.0f}% {agg['seconds']:7.1f} {agg['duty']:6.2f} "
              f"{agg['stride_hz']:7.2f} {agg['effort_per_m']:9.3f}")
    if args.json:
        Path(args.json).write_text(json.dumps({"run": run.name, "terrain": env.terrain.name, "results": results}, indent=1))
    if args.gif:
        from PIL import Image
        renderer = mujoco.Renderer(env.model, 360, 480)
        frames: list = []
        episode(env, ac, norm, args.gif_speed, 8.0, renderer, frames, frame_every=3)
        imgs = [Image.fromarray(f) for f in frames]
        imgs[0].save(args.gif, save_all=True, append_images=imgs[1:], duration=60, loop=0)
        strip_n = min(6, len(imgs))
        idx = np.linspace(0, len(imgs) - 1, strip_n).astype(int)
        strip = Image.new("RGB", (480 * strip_n // 2, 360 * 2))
        for k, i in enumerate(idx):
            strip.paste(imgs[i].resize((240, 180)).resize((480 // 2 * 1, 360 // 2 * 1)), ((k % 3) * 240, (k // 3) * 180))
        strip = strip.crop((0, 0, 720, 360))
        strip.save(args.gif.replace(".gif", "_strip.png"))
        print(f"wrote {args.gif} ({len(imgs)} frames) and strip")


if __name__ == "__main__":
    main()
