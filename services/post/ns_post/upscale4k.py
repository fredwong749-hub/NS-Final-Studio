"""Optional 4K step (fredw-92/Q1; research D5–D7): run gpu3's SeedVR2 stage `scripts/upscale_4k.py shot` on a local
clip and fetch the result back as `<clip>_4k.mp4`, where ns_post.assemble.find_source picks it up (path_4k) and the
4K delivery encode (D6: CRF 17, maxrate 60M / bufsize 120M, level 5.1) uses it.

Only when asked (`tools/assemble_episode.py --upscale-4k print|run`); never by default. `upscale_4k.py` itself takes the
gpu3 GPU lock / lend rules (docs/upscale_4k.md §3), so `run` may wait for a free card. The `shot` command delivers the
SeedVR2 intermediate (LAB colour correction, no regrade); grain stays a finish-only step (D7).
"""
from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

HOST = "gpu33"
NS_STUDIO = "/root/claude-kimi-ns-studio-v1/ns-studio"
REMOTE_DIR = f"{NS_STUDIO}/data/run/laptop_4k"
GPUS = "3"


def remote_name(clip: Path, ep: int, idx: int) -> str:
    return f"ep{ep:02d}_S{idx}_{Path(clip).stem}"


def local_4k(clip: Path) -> Path:
    clip = Path(clip)
    return clip.with_name(clip.stem + "_4k" + clip.suffix)


def commands(clip: Path, ep: int, idx: int, *, host: str = HOST, gpus: str = GPUS) -> list[list[str]]:
    """argv lists: mkdir on gpu3 → upload the clip → upscale_4k.py shot → fetch <name>.4k.mp4 as <clip>_4k.mp4"""
    name = remote_name(clip, ep, idx)
    rdir = f"{REMOTE_DIR}/ep{ep:02d}"
    rclip = f"{rdir}/{name}.mp4"
    run = (f"cd {shlex.quote(NS_STUDIO)} && .venv/bin/python scripts/upscale_4k.py shot {shlex.quote(rclip)} "
           f"--out {shlex.quote(rdir)} --gpu {shlex.quote(gpus)}")
    return [["ssh", host, f"mkdir -p {shlex.quote(rdir)}"],
            ["scp", "-q", str(clip), f"{host}:{rclip}"],
            ["ssh", host, run],
            ["scp", "-q", f"{host}:{rdir}/{name}.4k.mp4", str(local_4k(clip))]]


def upscale(clip: Path, ep: int, idx: int, *, execute: bool = False, runner=subprocess.run, log=print) -> Path | None:
    """execute=False: only print the commands. True: run them in order (stops at the first failure)."""
    cmds = commands(clip, ep, idx)
    for c in cmds:
        log(" ".join(shlex.quote(x) for x in c))
        if execute:
            r = runner(c)
            if getattr(r, "returncode", 0):
                log(f"S{idx}: 4K step failed ({c[0]} exit {r.returncode})")
                return None
    return local_4k(clip) if execute else None
