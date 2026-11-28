"""PPO trainer for the Primeva locomotion gym (CPU, multiprocess).

    python ppo.py --plan bodyplans/dromaeosaur.json --actuation muscle \
        --terrains flat,../../out/gym/site_343680,../../out/gym/site_505344 \
        --minutes 60 --out ../../out/gym/runs/dromaeosaur_muscle

Design choices (standard, well-tested PPO; Schulman 2017, "37 implementation
details" Huang et al. 2022): GAE(0.95), clip 0.2, value clipping off,
observation normalisation (running mean/var), advantage normalisation,
bootstrap on time-limit truncation, orthogonal init, tanh-free Gaussian
policy with state-independent log-std, Adam with linear LR decay.
Speed curriculum: the commanded-speed range grows as the policy tracks it.
"""

from __future__ import annotations

import argparse
import multiprocessing as mp
import os
import sys
import time
from pathlib import Path

# One BLAS/OpenMP thread per process. With more, idle OpenMP threads spin-wait
# after each update and starve the simulation workers (measured: 10x slowdown).
for _var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import numpy as np
import torch
import torch.nn as nn

sys.path.insert(0, str(Path(__file__).resolve().parent))


# ----------------------------------------------------------------------------- vec env
def _worker(remote, plan, terrains, actuation, seed, n_envs):
    import numpy as _np
    from env import LocomotionEnv

    envs = [LocomotionEnv(plan, None if terrains[i % len(terrains)] == "flat" else terrains[i % len(terrains)],
                          actuation=actuation, seed=seed * 1000 + i) for i in range(n_envs)]
    obs = [e.reset() for e in envs]
    ep_ret = _np.zeros(n_envs)
    ep_len = _np.zeros(n_envs, dtype=int)
    while True:
        cmd, payload = remote.recv()
        if cmd == "obs":
            remote.send(_np.stack(obs))
        elif cmd == "step":
            out_obs, rews, terms, truncs, final_obs, stats = [], [], [], [], [], []
            for i, e in enumerate(envs):
                o, r, te, tr, info = e.step(payload[i])
                ep_ret[i] += r
                ep_len[i] += 1
                fo = o
                if te or tr:
                    stats.append((ep_ret[i], ep_len[i], info["v_fwd"], info["cmd"], bool(te)))
                    ep_ret[i] = 0.0
                    ep_len[i] = 0
                    o = e.reset()
                obs[i] = o
                out_obs.append(o); rews.append(r); terms.append(te); truncs.append(tr); final_obs.append(fo)
            remote.send((_np.stack(out_obs), _np.array(rews), _np.array(terms), _np.array(truncs), _np.stack(final_obs), stats))
        elif cmd == "curriculum":
            for e in envs:
                e.speed_curriculum = payload
            remote.send(True)
        elif cmd == "close":
            remote.close()
            break


class VecEnv:
    def __init__(self, plan, terrains, actuation, workers, envs_per_worker, seed):
        ctx = mp.get_context("fork")
        self.remotes, self.procs = [], []
        for w in range(workers):
            a, b = ctx.Pipe()
            p = ctx.Process(target=_worker, args=(b, plan, terrains[w::workers] or terrains, actuation, seed + w, envs_per_worker),
                            daemon=True)
            p.start()
            self.remotes.append(a)
            self.procs.append(p)
        self.n = workers * envs_per_worker
        self.per = envs_per_worker

    def obs(self):
        for r in self.remotes:
            r.send(("obs", None))
        return np.concatenate([r.recv() for r in self.remotes])

    def step(self, actions):
        for k, r in enumerate(self.remotes):
            r.send(("step", actions[k * self.per:(k + 1) * self.per]))
        res = [r.recv() for r in self.remotes]
        o = np.concatenate([x[0] for x in res]); rew = np.concatenate([x[1] for x in res])
        te = np.concatenate([x[2] for x in res]); tr = np.concatenate([x[3] for x in res])
        fo = np.concatenate([x[4] for x in res]); stats = [s for x in res for s in x[5]]
        return o, rew, te, tr, fo, stats

    def set_curriculum(self, c):
        for r in self.remotes:
            r.send(("curriculum", c))
        for r in self.remotes:
            r.recv()

    def close(self):
        for r in self.remotes:
            r.send(("close", None))
        for p in self.procs:
            p.join(timeout=5)


# ----------------------------------------------------------------------------- model
class RunningNorm:
    def __init__(self, dim):
        self.mean = np.zeros(dim)
        self.var = np.ones(dim)
        self.count = 1e-4

    def update(self, x):
        bm, bv, bc = x.mean(0), x.var(0), x.shape[0]
        delta = bm - self.mean
        tot = self.count + bc
        self.mean = self.mean + delta * bc / tot
        self.var = (self.var * self.count + bv * bc + delta ** 2 * self.count * bc / tot) / tot
        self.count = tot

    def __call__(self, x):
        return np.clip((x - self.mean) / np.sqrt(self.var + 1e-8), -10, 10).astype(np.float32)


def mlp(i, o, hidden=(256, 256), out_gain=1.0):
    layers, d = [], i
    for h in hidden:
        lin = nn.Linear(d, h)
        nn.init.orthogonal_(lin.weight, np.sqrt(2)); nn.init.zeros_(lin.bias)
        layers += [lin, nn.ELU()]
        d = h
    last = nn.Linear(d, o)
    nn.init.orthogonal_(last.weight, out_gain); nn.init.zeros_(last.bias)
    return nn.Sequential(*layers, last)


class ActorCritic(nn.Module):
    def __init__(self, obs_dim, act_dim, init_log_std=-0.7):
        super().__init__()
        self.pi = mlp(obs_dim, act_dim, out_gain=0.01)
        self.v = mlp(obs_dim, 1, out_gain=1.0)
        self.log_std = nn.Parameter(torch.full((act_dim,), init_log_std))

    def dist(self, obs):
        return torch.distributions.Normal(self.pi(obs), self.log_std.exp())


# ----------------------------------------------------------------------------- training
def train(args):
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    terrains = args.terrains.split(",")
    venv = VecEnv(args.plan, terrains, args.actuation, args.workers, args.envs_per_worker, args.seed)
    obs = venv.obs()
    obs_dim, N = obs.shape[1], venv.n
    from env import LocomotionEnv
    probe = LocomotionEnv(args.plan, None, actuation=args.actuation)
    act_dim = probe.act_dim
    del probe

    ac = ActorCritic(obs_dim, act_dim)
    opt = torch.optim.Adam(ac.parameters(), lr=args.lr, eps=1e-5)
    norm = RunningNorm(obs_dim)
    norm.update(obs)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    log = open(out / "log.csv", "w")
    log.write("iter,steps,seconds,mean_return,mean_len,fall_rate,speed_err,curriculum,log_std,fps\n")

    T = args.horizon
    gamma, lam = 0.99, 0.95
    curriculum = 0.35
    t0 = time.time()
    total_steps, it = 0, 0
    recent = []
    best = -1e9
    while time.time() - t0 < args.minutes * 60:
        it += 1
        b_obs = np.zeros((T, N, obs_dim), np.float32); b_act = np.zeros((T, N, act_dim), np.float32)
        b_logp = np.zeros((T, N), np.float32); b_rew = np.zeros((T, N), np.float32)
        b_done = np.zeros((T, N), np.float32); b_val = np.zeros((T + 1, N), np.float32)
        it_start = time.time()
        for t in range(T):
            o = norm(obs)
            with torch.no_grad():
                ot = torch.from_numpy(o)
                d = ac.dist(ot)
                a = d.sample()
                b_logp[t] = d.log_prob(a).sum(-1).numpy()
                b_val[t] = ac.v(ot).squeeze(-1).numpy()
            b_obs[t] = o
            b_act[t] = a.numpy()
            nobs, rew, te, tr, fobs, stats = venv.step(a.numpy())
            rew = rew.astype(np.float32)
            if tr.any():  # bootstrap value of the truncated state
                idx = np.where(tr & ~te)[0]
                if len(idx):
                    with torch.no_grad():
                        rew[idx] += gamma * ac.v(torch.from_numpy(norm(fobs[idx]))).squeeze(-1).numpy()
            b_rew[t] = rew
            b_done[t] = (te | tr).astype(np.float32)
            norm.update(nobs)
            obs = nobs
            recent += stats
        with torch.no_grad():
            b_val[T] = ac.v(torch.from_numpy(norm(obs))).squeeze(-1).numpy()
        adv = np.zeros((T, N), np.float32)
        last = np.zeros(N, np.float32)
        for t in reversed(range(T)):
            nonterm = 1.0 - b_done[t]
            delta = b_rew[t] + gamma * b_val[t + 1] * nonterm - b_val[t]
            last = delta + gamma * lam * nonterm * last
            adv[t] = last
        ret = adv + b_val[:T]

        fo = torch.from_numpy(b_obs.reshape(T * N, -1)); fa = torch.from_numpy(b_act.reshape(T * N, -1))
        fl = torch.from_numpy(b_logp.reshape(-1)); fadv = torch.from_numpy(adv.reshape(-1)); fret = torch.from_numpy(ret.reshape(-1))
        frac = 1.0 - (time.time() - t0) / (args.minutes * 60)
        for g in opt.param_groups:
            g["lr"] = args.lr * max(0.1, frac)
        bs = T * N
        mb = bs // args.minibatches
        for _ in range(args.epochs):
            perm = torch.randperm(bs)
            for k in range(args.minibatches):
                idx = perm[k * mb:(k + 1) * mb]
                d = ac.dist(fo[idx])
                logp = d.log_prob(fa[idx]).sum(-1)
                ratio = (logp - fl[idx]).exp()
                a_ = fadv[idx]
                a_ = (a_ - a_.mean()) / (a_.std() + 1e-8)
                pl = -torch.min(ratio * a_, ratio.clamp(1 - 0.2, 1 + 0.2) * a_).mean()
                vl = 0.5 * ((ac.v(fo[idx]).squeeze(-1) - fret[idx]) ** 2).mean()
                ent = d.entropy().sum(-1).mean()
                loss = pl + 0.5 * vl - args.ent * ent
                opt.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(ac.parameters(), 1.0)
                opt.step()
        total_steps += T * N
        fps = T * N / (time.time() - it_start)

        if len(recent) >= 20:
            rets = np.array([s[0] for s in recent]); lens = np.array([s[1] for s in recent])
            falls = np.mean([s[4] for s in recent]); serr = np.mean([abs(s[2] - s[3]) for s in recent])
            # curriculum: widen commanded speeds once tracking is good and falls are rare
            if serr < 0.25 and falls < 0.3 and curriculum < 1.0:
                curriculum = min(1.0, curriculum + 0.05)
                venv.set_curriculum(curriculum)
            line = (f"{it},{total_steps},{time.time() - t0:.0f},{rets.mean():.2f},{lens.mean():.0f},{falls:.3f},{serr:.3f},"
                    f"{curriculum:.2f},{ac.log_std.mean().item():.3f},{fps:.0f}")
            log.write(line + "\n"); log.flush()
            print(line, flush=True)
            score = lens.mean() * (1.0 - falls) - 100 * serr
            if score > best:
                best = score
                save(ac, norm, out / "best.pt", args, obs_dim, act_dim)
            recent = []
        if it % 20 == 0:
            save(ac, norm, out / "last.pt", args, obs_dim, act_dim)
    save(ac, norm, out / "last.pt", args, obs_dim, act_dim)
    venv.close()
    print(f"done: {total_steps} steps in {(time.time() - t0) / 60:.1f} min")


def save(ac, norm, path, args, obs_dim, act_dim):
    torch.save({"model": ac.state_dict(), "norm_mean": norm.mean, "norm_var": norm.var, "obs_dim": obs_dim,
                "act_dim": act_dim, "args": vars(args)}, path)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--plan", required=True)
    p.add_argument("--actuation", default="muscle", choices=["muscle", "motor"])
    p.add_argument("--terrains", default="flat")
    p.add_argument("--minutes", type=float, default=60)
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--envs-per-worker", type=int, default=12)
    p.add_argument("--horizon", type=int, default=64)
    p.add_argument("--epochs", type=int, default=5)
    p.add_argument("--minibatches", type=int, default=4)
    p.add_argument("--lr", type=float, default=3e-4)
    p.add_argument("--ent", type=float, default=0.0)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--out", required=True)
    train(p.parse_args())
