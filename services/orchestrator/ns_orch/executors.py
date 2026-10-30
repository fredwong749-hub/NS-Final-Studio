"""
笔记本步骤的执行器。

RealExecutor：子进程跑现有工具（与 render_batch / assemble_episode 同一套代码），环境变量 NS_PROJECT_ROOT
指向项目目录。成人镜头与普通镜头一起出（2026-10-30 取消过滤器）；笔记本从不出视频（规则 7）。
DryRunExecutor：只记录“将要执行的命令”，不碰 GPU、不出图——测试与演示用。
"""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.request

from ns_api.project_ctx import REPO, ProjectContext, read_json, write_json

COMFY_URL = "http://127.0.0.1:8188"


class Waiting(Exception):
    """外部条件未满足（如 ComfyUI 没开）：步骤进入等待，不计失败次数"""


class StepFailed(Exception):
    pass


# ------------------------------------------------------------------ 观察（只读文件，判断步骤是否已满足）

def shot_ids(ctx: ProjectContext, ep: int) -> list[tuple[str, bool]]:
    """[(shot_id, adult)]，来自项目导入结果"""
    data = read_json(ctx.script_json, {})
    for e in data.get("episodes", []):
        if e["number"] == ep:
            return [(f"ep{ep:02d}-S{s['index']}", bool(s.get("adult"))) for s in e["shots"]]
    return []


def _active(ctx_dir, shot_id: str, stage: str) -> bool:
    ep, s = shot_id.split("-")
    d = ctx_dir / ep / s
    takes = read_json(d / "takes.json", None)
    if takes is not None:
        return takes.get("active", {}).get(stage) is not None
    return (d / {"image": "frame.png", "last": "last.png", "video": "video.mp4"}[stage]).exists()


def frame_progress(ctx: ProjectContext, ep: int, stage: str) -> dict:
    """非成人镜头看笔记本 data/renders；成人镜头看 gpu3 镜像（两边都算到“首帧/尾帧”灯里）"""
    shots = shot_ids(ctx, ep)
    laptop = [sid for sid, adult in shots if not adult]
    adult = [sid for sid, a in shots if a]
    done_l = sum(_active(ctx.renders, sid, stage) for sid in laptop)
    done_a = sum(any(_active(d, sid, stage) for d in ctx.renders_gpu3_dirs) for sid in adult)
    return {"laptop_done": done_l, "laptop_total": len(laptop), "gpu3_done": done_a, "gpu3_total": len(adult),
            "done": done_l + done_a, "total": len(shots)}


def episode_final(ctx: ProjectContext, ep: int):
    p = ctx.episodes_out / f"ep{ep:02d}.mp4"
    return p if p.exists() else None


def comfy_status(url: str = COMFY_URL, timeout: float = 1.5) -> dict:
    """笔记本 ComfyUI 队列 + 显存"""
    out: dict = {"url": url, "reachable": False}
    try:
        with urllib.request.urlopen(url + "/queue", timeout=timeout) as r:
            q = json.loads(r.read().decode())
        out.update(reachable=True, running=len(q.get("queue_running", [])), pending=len(q.get("queue_pending", [])))
        with urllib.request.urlopen(url + "/system_stats", timeout=timeout) as r:
            stats = json.loads(r.read().decode())
        dev = (stats.get("devices") or [{}])[0]
        if dev.get("vram_total"):
            out.update(gpu=dev.get("name"), vram_total_mb=dev["vram_total"] // 2**20,
                       vram_used_mb=(dev["vram_total"] - dev.get("vram_free", 0)) // 2**20)
    except (urllib.error.URLError, OSError, ValueError) as e:
        out["error"] = str(e)[:120]
    return out


# ------------------------------------------------------------------ 执行器

class BaseExecutor:
    name = "base"

    def __init__(self):
        self.calls: list[tuple] = []

    def import_script(self, ctx: ProjectContext, use_v3: bool = False) -> dict:
        """导入是纯解析（不出图），dry-run 也真跑：后面的步骤要用到集/镜列表"""
        from ns_api import wizard
        self.calls.append(("import", ctx.slug, use_v3))
        if use_v3:
            v3 = find_v3(ctx)
            if not v3:
                raise StepFailed("没有找到 v3 剧本（script/*v3*.md）")
            s = ctx.settings()
            s.setdefault("script_files", {})["script"] = ctx.rel(v3)
            ctx.save_settings(s)
        rep = wizard.validate_script(ctx)
        if not rep["ok"]:
            raise StepFailed("；".join(rep["fatal"]))
        return {"episodes": rep["episodes"], "shots": rep["shots"], "warnings": len(rep["warnings"])}

    def frame_spec(self, ctx: ProjectContext, ep: int) -> dict:
        raise NotImplementedError

    def render_frames(self, ctx: ProjectContext, ep: int, stage: str) -> dict:
        raise NotImplementedError

    def assemble(self, ctx: ProjectContext, ep: int) -> dict:
        raise NotImplementedError


def find_v3(ctx: ProjectContext):
    return next((p for p in sorted((ctx.root / "script").glob("*v3*.md")) if "changes" not in p.name), None)


class DryRunExecutor(BaseExecutor):
    """不出图、不跑子进程：记下命令即算完成（测试 / 演示）"""
    name = "dry_run"

    def frame_spec(self, ctx, ep):
        self.calls.append(("frame_spec", ctx.slug, ep))
        return {"dry_run": True, "cmd": f"python -m ns_orch.laptop_steps frame_spec {ep}"}

    def render_frames(self, ctx, ep, stage):
        assert stage in ("image", "last"), "笔记本只出图片"
        self.calls.append(("render", ctx.slug, ep, stage))
        n = len([s for s, a in shot_ids(ctx, ep) if not a])
        return {"dry_run": True, "shots": n,
                "cmd": f"python tools/render_batch.py --stage {stage} --shots ep{ep:02d}  (NS_PROJECT_ROOT={ctx.root})"}

    def assemble(self, ctx, ep):
        self.calls.append(("assemble", ctx.slug, ep))
        return {"dry_run": True, "cmd": f"python tools/assemble_episode.py ep{ep:02d}"}


class RealExecutor(BaseExecutor):
    name = "real"

    def __init__(self, comfy_url: str = COMFY_URL, timeout_s: int = 6 * 3600):
        super().__init__()
        self.comfy_url = comfy_url
        self.timeout_s = timeout_s

    def _run(self, ctx: ProjectContext, args: list[str], log_name: str) -> dict:
        log = ctx.orchestrator_dir / "logs" / f"{log_name}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("ab") as fh:
            p = subprocess.run([sys.executable, *args], cwd=REPO, env=ctx.env(), stdout=fh, stderr=subprocess.STDOUT,
                               timeout=self.timeout_s)
        if p.returncode != 0:
            tail = log.read_text(encoding="utf-8", errors="replace")[-400:]
            raise StepFailed(f"退出码 {p.returncode}：{tail}")
        return {"log": ctx.rel(log) if log.is_relative_to(ctx.root) else str(log)}

    def frame_spec(self, ctx, ep):
        self.calls.append(("frame_spec", ctx.slug, ep))
        return self._run(ctx, ["-m", "ns_orch.laptop_steps", "frame_spec", str(ep)], f"ep{ep:02d}_frame_spec")

    def render_frames(self, ctx, ep, stage):
        if stage not in ("image", "last"):
            raise StepFailed("笔记本只出首帧/尾帧（规则 7）")
        if ctx.is_default:
            raise StepFailed("《为他而骚》由现有流程生产，编排器不在默认项目上出图")
        st = comfy_status(self.comfy_url)
        if not st["reachable"]:
            raise Waiting(f"本机 ComfyUI 未开（{self.comfy_url}）")
        # T44：与画布渲染队列共用一把 ComfyUI 锁；画布占用时本步骤等待（下一轮再试，不计失败）
        from ns_orch import comfy_lock as CL
        try:
            fh = CL.acquire("orchestrator", f"{ctx.slug} ep{ep:02d} {stage}", timeout=0)
        except CL.Busy as e:
            raise Waiting(str(e))
        try:
            self.calls.append(("render", ctx.slug, ep, stage))
            # 2026-10-30 取消过滤器：成人镜头也由 render_batch 一起出
            return self._run(ctx, ["tools/render_batch.py", "--stage", stage, "--shots", f"ep{ep:02d}",
                                   "--comfy", self.comfy_url], f"ep{ep:02d}_{stage}")
        finally:
            CL.release(fh)

    def assemble(self, ctx, ep):
        self.calls.append(("assemble", ctx.slug, ep))
        return self._run(ctx, ["tools/assemble_episode.py", f"ep{ep:02d}", "--script", str(ctx.script_json),
                               "--out", str(ctx.episodes_out)], f"ep{ep:02d}_assemble")


def write_frame_specs(ctx: ProjectContext, ep: int) -> dict:
    """画面说明（ns_agent.frame_spec 确定性规则版）→ data/frame_specs/epXX.json（含校验问题）。
    在 NS_PROJECT_ROOT 子进程里调用，成人判定读本项目的 adult_overrides.json。"""
    from ns_agent import frame_spec as FS
    from ns_schema.script import ScriptImport
    script = ScriptImport.model_validate_json(ctx.script_json.read_text(encoding="utf-8"))
    ep_obj = next(e for e in script.episodes if e.number == ep)
    out = []
    tl = FS.load_timeline_index()   # T08：复用时间线的 framing / faces_visible / props / 换装（没有则现算）
    for s in ep_obj.shots:
        spec = FS.build_spec(ep_obj, s, script.globals, timeline_shot=tl.get(s.id))
        out.append({"shot": s.id, "spec": spec.model_dump(), "problems": FS.validate(spec)})
    write_json(ctx.data_dir / "frame_specs" / f"ep{ep:02d}.json", out)
    return {"shots": len(out), "problems": sum(len(x["problems"]) for x in out)}
