"""
编排状态机：每个项目一个 data/orchestrator/state.json（原子写），里面是项目级步骤、关口和每集步骤。

每次 tick() 都从文件读状态、看外部事实（文件 / gpu3 状态）、推进能推进的步骤、写回——所以：
- 幂等：重复 tick 不会重复执行已完成的步骤；步骤开始前先检查产物是否已存在（存在即记完成）。
- 可续跑：进程重启后，状态里“运行中”但不属于本进程的步骤回到“待执行”。
- 关口：G2 人物定妆、G3 剧本加强确认、GPU3 交接授权、G4 样片锁定、G5 成片验收（每集）；
  卡片打开后，关口之后的步骤一律不跑，直到项目方在「待办」里点。
- 失败：同一步骤失败 3 次进入异常队列（blocked），不影响其他集。

每集步骤：剧本 → 画面说明 → 首帧(非成人) → 尾帧(非成人) → 交 gpu3 → 视频 → QA → 声音 → 4K → 成片装配 → G5 验收
笔记本只跑：导入、画面说明、非成人首/尾帧、成片装配。成人首尾帧 + 全部视频/QA/声音/4K 在 gpu3。
"""
from __future__ import annotations

import os
import shutil
import threading
import uuid

from ns_api.project_ctx import ProjectContext, now, read_json, write_json
from ns_orch.executors import (BaseExecutor, StepFailed, Waiting, episode_final, find_v3, frame_progress,
                               shot_ids)
from ns_orch.gpu3 import SimulatedGpu3, normalize

EP_STEPS = ("script", "frame_spec", "first", "last", "handoff", "video", "qa", "audio", "upscale", "assemble", "accept")
STEP_LABEL = {"script": "剧本", "frame_spec": "画面说明", "first": "首帧", "last": "尾帧", "handoff": "交 gpu3",
              "video": "视频", "qa": "QA", "audio": "声音", "upscale": "4K", "assemble": "成片装配",
              "accept": "成片验收", "import": "剧本导入"}
LAPTOP_STEPS = ("frame_spec", "first", "last", "assemble")
GPU3_FIELD = {"video": "videos", "qa": "qa", "audio": "audio", "upscale": "upscale_4k"}
LIGHTS = (("剧本", "script"), ("首帧", "first"), ("尾帧", "last"), ("视频", "video"), ("QA", "qa"),
          ("声音", "audio"), ("4K", "upscale"), ("成片", "assemble"))
GATES = {"G2": "人物定妆", "G3": "剧本加强确认", "GPU3": "交 gpu3 出成人首尾帧与视频", "G4": "样片锁定",
         "G5": "成片验收"}
MAX_ATTEMPTS = 3
WAIT_RETRY_S = 60
# 粗估耗时（秒）：笔记本首帧多候选多轮 ≈5 分钟/镜，尾帧 ≈3 分钟/镜；gpu3 视频 28 分钟/镜（SOP 资源表），两卡并行
EST = {"frame_spec": 30, "first": 300, "last": 180, "assemble": 480, "video": 1680, "qa": 300, "audio": 1200,
       "upscale": 600}
GPU3_CARDS = 2

_locks: dict[str, threading.RLock] = {}
_live: set[str] = set()            # 本进程里正在跑的步骤令牌
_laptop = threading.Lock()         # 笔记本一次只跑一个大任务（跨项目）


def _lock(slug: str) -> threading.RLock:
    return _locks.setdefault(slug, threading.RLock())


def _ts(s: str | None) -> float:
    import time
    if not s:
        return 0.0
    try:
        return time.mktime(time.strptime(s, "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return 0.0


class Engine:
    def __init__(self, ctx: ProjectContext, executor: BaseExecutor, bridge=None, *, sync: bool = True):
        self.ctx = ctx
        self.executor = executor
        self.bridge = bridge
        self.sync = sync
        self._mode = None

    # ------------------------------------------------------------------ 状态文件
    @property
    def path(self):
        return self.ctx.orchestrator_dir / "state.json"

    def load(self) -> dict:
        st = read_json(self.path, None) or {"version": 1, "slug": self.ctx.slug, "running": False, "mode": None,
                                            "project": {}, "gates": {}, "episodes": {}, "log": []}
        for g in ("G2", "G3", "GPU3", "G4"):
            st["gates"].setdefault(g, {"status": "pending"})
        # 续跑：别的进程留下的“运行中”回到待执行
        for steps in [st["project"]] + [e["steps"] for e in st["episodes"].values()]:
            for name, rec in steps.items():
                if rec.get("status") == "running" and rec.get("token") and rec["token"] not in _live:
                    rec.update(status="pending", detail="进程重启后恢复，重新排队")
        return st

    def save(self, st: dict) -> None:
        st["updated_at"] = now()
        st["log"] = st["log"][-200:]
        write_json(self.path, st)

    def _log(self, st: dict, msg: str) -> None:
        st["log"].append({"at": now(), "msg": msg})

    def _bridge(self, st: dict):
        return SimulatedGpu3(st) if st.get("mode") == "dry_run" else self.bridge

    # ------------------------------------------------------------------ 控制
    def start(self, mode: str, by: str = "项目方") -> dict:
        if self.ctx.is_default:
            raise ValueError("《为他而骚》由现有流程生产，看板只读；编排器只用于新建的剧")
        if self.ctx.settings().get("status") != "ready":
            raise ValueError("项目还没在向导里完成创建")
        with _lock(self.ctx.slug):
            st = self.load()
            if st.get("mode") and st["mode"] != mode and st["episodes"]:
                raise ValueError(f"本项目已用 {st['mode']} 模式开始过；换模式请先重置")
            st.update(running=True, mode=mode, started_at=st.get("started_at") or now(), started_by=by)
            self._log(st, f"开始生产（{'演练' if mode == 'dry_run' else '正式'}，{by}）")
            self.save(st)
        return self.tick()

    def pause(self, by: str = "项目方") -> dict:
        with _lock(self.ctx.slug):
            st = self.load()
            st["running"] = False
            self._log(st, f"暂停（{by}）")
            self.save(st)
            return st

    def reset(self) -> None:
        with _lock(self.ctx.slug):
            if self.path.exists():
                self.path.unlink()

    # ------------------------------------------------------------------ tick
    def tick(self) -> dict:
        job = None
        with _lock(self.ctx.slug):
            st = self.load()
            bridge = self._bridge(st)
            if st["running"] and isinstance(bridge, SimulatedGpu3):
                bridge.advance()
            gpu = self._gpu_view(bridge)
            st["gpu3_view"] = {str(k): v for k, v in gpu.items()}
            if st["running"]:
                self._project(st)
                self._episodes(st, gpu, bridge)
                job = self._claim_laptop(st)
            self.save(st)
        if job:
            if self.sync:
                self._run(job)
                return self.load()
            threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return st

    def _gpu_view(self, bridge) -> dict[int, dict]:
        if bridge is None:
            return {}
        try:
            return bridge.episodes(self.ctx)
        except Exception:                       # 桥异常不影响笔记本侧推进
            return {}

    # ------------------------------------------------------------------ 项目级
    def _project(self, st: dict) -> None:
        imp = st["project"].setdefault("import", {"status": "pending", "attempts": 0})
        if imp["status"] not in ("done", "blocked"):
            try:
                imp.update(status="done", result=self.executor.import_script(self.ctx), at=now(), error=None)
                self._log(st, "剧本导入完成")
            except (StepFailed, Exception) as e:
                self._fail(st, imp, "import", None, e)
        if imp["status"] != "done":
            return
        g = st["gates"]
        if g["G2"]["status"] == "pending":
            g["G2"].update(status="open", opened_at=now())
            self._log(st, "G2 人物定妆：待项目方选定母版")
        if g["G2"]["status"] == "open":
            g["G2"]["detail"] = {"characters": self._candidates()}
        if g["G3"]["status"] in ("pending", "open"):
            v3 = find_v3(self.ctx)
            if g["G3"]["status"] == "pending":
                g["G3"].update(status="open", opened_at=now())
            g["G3"]["detail"] = {"v3": self.ctx.rel(v3) if v3 else None,
                                 "changes": self.ctx.rel(v3.with_name(v3.stem + "_changes.md"))
                                 if v3 and v3.with_name(v3.stem + "_changes.md").exists() else None}

    def _candidates(self) -> list[dict]:
        out = []
        for c in self.ctx.settings().get("characters", {}).values():
            base = self.ctx.assets_dir / "characters" / c["id"]
            files = list(c.get("references", []))
            for sub in ("candidates", "plates"):
                if (base / sub).is_dir():
                    files += [self.ctx.rel(p) for p in sorted((base / sub).iterdir())
                              if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
            out.append({"id": c["id"], "name": c["name"], "candidates": list(dict.fromkeys(files)),
                        "realism": c.get("realism", "mid"), "confirmed": bool(c.get("confirmed"))})
        return out

    # ------------------------------------------------------------------ 每集
    def episode_numbers(self) -> list[int]:
        data = read_json(self.ctx.script_json, {})
        return sorted(e["number"] for e in data.get("episodes", []))

    def _steps(self, st: dict, ep: int) -> dict:
        e = st["episodes"].setdefault(str(ep), {"steps": {}})
        for name in EP_STEPS:
            e["steps"].setdefault(name, {"status": "pending", "attempts": 0})
        return e["steps"]

    def _episodes(self, st: dict, gpu: dict[int, dict], bridge) -> None:
        g = st["gates"]
        eps = self.episode_numbers()
        if not eps:
            return
        first_ep = eps[0]
        gates_ok = g["G2"]["status"] == "approved" and g["G3"]["status"] == "approved"
        adult_on = bool(self.ctx.settings().get("adult_content", True))
        for ep in eps:
            s = self._steps(st, ep)
            if s["script"]["status"] != "done":
                if gates_ok:
                    s["script"].update(status="done", at=now(), detail=None)
                else:
                    waiting = [f"{k} {GATES[k]}" for k in ("G2", "G3") if g[k]["status"] != "approved"]
                    s["script"].update(status="waiting", detail="等 " + "、".join(waiting))
                    continue
            # 笔记本步骤：产物已存在就直接记完成（幂等）
            for name, stage in (("first", "image"), ("last", "last")):
                if s[name]["status"] not in ("done", "running"):
                    fp = frame_progress(self.ctx, ep, stage)
                    if fp["laptop_total"] == 0:
                        s[name].update(status="done", detail="本集全部是成人镜头，由 gpu3 出", at=now())
                    elif fp["laptop_done"] >= fp["laptop_total"] and s["frame_spec"]["status"] == "done":
                        s[name].update(status="done", detail="已有当前版本", at=now())
            if s["assemble"]["status"] != "done" and episode_final(self.ctx, ep):
                s["assemble"].update(status="done", detail="成片已存在", at=now())
            # 交 gpu3
            h = s["handoff"]
            if h["status"] != "done" and s["last"]["status"] == "done":
                if g["GPU3"]["status"] == "pending":
                    g["GPU3"].update(status="open", opened_at=now())
                    self._log(st, "交 gpu3 授权：待项目方确认")
                if g["GPU3"]["status"] == "open":
                    g["GPU3"]["detail"] = self._handoff_detail(st, adult_on)
                if g["GPU3"]["status"] != "approved":
                    h.update(status="waiting", detail="等项目方授权交 gpu3")
                elif ep != first_ep and g["G4"]["status"] != "approved":
                    h.update(status="waiting", detail="等 G4 样片锁定（先只出第一集样片）")
                elif bridge is None:
                    h.update(status="waiting", detail="gpu3 桥未配置")
                else:
                    r = bridge.series(self.ctx, "start", [ep], adult_content=adult_on,
                                      requested_by=g["GPU3"].get("decided_by") or "项目方")
                    h.update(status="done", at=now(), detail=f"已交 gpu3（{r.get('via')}）")
                    self._log(st, f"ep{ep:02d} 已交 gpu3（{r.get('via')}）")
            # gpu3 侧进度（只读）
            rec = gpu.get(ep, {})
            for name, field in GPU3_FIELD.items():
                if s["handoff"]["status"] != "done" or s[name]["status"] == "done":
                    continue
                n = normalize(rec.get(field))
                status = n["status"] if n["status"] in ("done", "running", "failed", "waiting") else "pending"
                s[name].update(status=status, progress=[n["done"], n["total"]],
                               detail=("gpu3：" + "；".join(map(str, rec.get("errors") or []))[:200])
                               if status == "failed" else None)
                if status == "done":
                    s[name]["at"] = now()
            # G4：第一集视频出来后锁样片
            if ep == first_ep and s["video"]["status"] == "done" and g["G4"]["status"] == "pending":
                g["G4"].update(status="open", opened_at=now(), detail={"episode": ep})
                self._log(st, f"G4 样片锁定：ep{ep:02d} 视频已出，待项目方确认")
            # G5：成片装配完成后验收
            a = s["accept"]
            if s["assemble"]["status"] == "done" and a["status"] in ("pending",):
                a.update(status="gate", opened_at=now())
                self._log(st, f"G5 成片验收：ep{ep:02d} 待项目方验收")

    def _handoff_detail(self, st: dict, adult_on: bool) -> dict:
        data = read_json(self.ctx.script_json, {})
        adult = sum(bool(s.get("adult")) for e in data.get("episodes", []) for s in e["shots"])
        ready = [int(k) for k, e in st["episodes"].items() if e["steps"]["last"]["status"] == "done"]
        return {"adult_content": adult_on, "adult_shots": adult, "episodes_ready": sorted(ready),
                "note": "批准后由 gpu3 按自己的配置出首尾帧与全部视频；未锁样片（G4）前只交第一集。"
                        "2026-10-30 起成人镜头不再被跳过。"}

    def _eligible(self, s: dict, name: str) -> bool:
        prev = {"frame_spec": "script", "first": "frame_spec", "last": "first", "assemble": "video"}[name]
        if s[prev]["status"] != "done":
            return False
        if name == "assemble" and s["qa"]["status"] not in ("done",):
            return False
        rec = s[name]
        if rec["status"] in ("done", "running", "blocked"):
            return False
        if rec["status"] == "waiting" and _ts(rec.get("retry_at")) > _ts(now()):
            return False
        return True

    def _claim_laptop(self, st: dict):
        if any(r.get("status") == "running" for e in st["episodes"].values() for r in e["steps"].values()):
            return None
        for ep in self.episode_numbers():
            s = st["episodes"].get(str(ep), {}).get("steps")
            if not s:
                continue
            for name in LAPTOP_STEPS:
                if self._eligible(s, name):
                    token = uuid.uuid4().hex[:10]
                    _live.add(token)
                    s[name].update(status="running", token=token, started_at=now(), detail=None)
                    self._log(st, f"ep{ep:02d} {STEP_LABEL[name]} 开始（笔记本）")
                    return {"ep": ep, "step": name, "token": token}
        return None

    def _run(self, job: dict) -> None:
        ep, name, token = job["ep"], job["step"], job["token"]
        err = result = waiting = None
        with _laptop:
            try:
                if name == "frame_spec":
                    result = self.executor.frame_spec(self.ctx, ep)
                elif name == "first":
                    result = self.executor.render_frames(self.ctx, ep, "image")
                elif name == "last":
                    result = self.executor.render_frames(self.ctx, ep, "last")
                elif name == "assemble":
                    result = self.executor.assemble(self.ctx, ep)
            except Waiting as e:
                waiting = e
            except Exception as e:
                err = e
        _live.discard(token)
        with _lock(self.ctx.slug):
            st = self.load()
            rec = st["episodes"][str(ep)]["steps"][name]
            if waiting:
                import time
                rec.update(status="waiting", detail=str(waiting),
                           retry_at=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() + WAIT_RETRY_S)))
            elif err:
                self._fail(st, rec, name, ep, err)
            else:
                rec.update(status="done", at=now(), result=result, error=None, detail=None)
                self._log(st, f"ep{ep:02d} {STEP_LABEL[name]} 完成")
            rec.pop("token", None)
            self.save(st)

    def _fail(self, st, rec: dict, name: str, ep: int | None, e: Exception) -> None:
        rec["attempts"] = rec.get("attempts", 0) + 1
        rec["error"] = str(e)[:500]
        rec["status"] = "blocked" if rec["attempts"] >= MAX_ATTEMPTS else "failed"
        where = f"ep{ep:02d} " if ep else ""
        self._log(st, f"{where}{STEP_LABEL.get(name, name)} 失败（第 {rec['attempts']} 次）：{rec['error'][:120]}")

    # ------------------------------------------------------------------ 项目方操作
    def decide(self, card_id: str, decision: str, payload: dict | None = None, by: str = "项目方") -> dict:
        payload = payload or {}
        with _lock(self.ctx.slug):
            st = self.load()
            if card_id.startswith("G5:"):
                ep = int(card_id.split("ep")[-1])
                a = st["episodes"].get(str(ep), {}).get("steps", {}).get("accept")
                if not a or a["status"] != "gate":
                    raise ValueError("这张验收卡不在待办状态")
                if decision not in ("publish", "rework"):
                    raise ValueError("G5 只能是 publish（发布）或 rework（返工）")
                a.update(status="done" if decision == "publish" else "rework", decided_by=by, decided_at=now(),
                         decision=decision, note=payload.get("note", ""))
                self._log(st, f"G5 ep{ep:02d}：{'发布' if decision == 'publish' else '返工'}（{by}）")
                self.save(st)
                return st
            gate = st["gates"].get(card_id)
            if not gate or gate["status"] != "open":
                raise ValueError(f"关口 {card_id} 不在待办状态")
            rec = {"decided_by": by, "decided_at": now(), "decision": decision, "note": payload.get("note", "")}
            if card_id == "G2":
                if decision != "approve":
                    raise ValueError("G2 只能 approve（为每个角色选定母版）")
                choices = payload.get("choices") or {}
                cands = {c["id"]: c for c in self._candidates()}
                missing = [c["name"] for cid, c in cands.items() if not choices.get(cid)]
                if missing:
                    raise ValueError("还没选母版：" + "、".join(missing))
                s = self.ctx.settings()
                for cid, rel in choices.items():
                    if cid not in cands or rel not in cands[cid]["candidates"]:
                        raise ValueError(f"{cid} 的母版不在候选里：{rel}")
                    src = self.ctx.resolve_inside(rel)
                    dst = self.ctx.assets_dir / "characters" / cid / "plates" / ("master" + src.suffix.lower())
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    if src.resolve() != dst.resolve():
                        shutil.copyfile(src, dst)
                    s["characters"][cid].update(master=self.ctx.rel(dst), master_from=rel, master_by=by,
                                                master_at=now())
                self.ctx.save_settings(s)
                gate.update(status="approved", choices=choices, **rec)
            elif card_id == "G3":
                if decision == "approve":
                    if not find_v3(self.ctx):
                        raise ValueError("gpu3 还没交回 v3 剧本；可以选“跳过加强，用原剧本”")
                    self.executor.import_script(self.ctx, use_v3=True)
                    gate.update(status="approved", use_v3=True, **rec)
                elif decision == "skip":
                    gate.update(status="approved", use_v3=False, **rec)
                elif decision == "reject":
                    gate.update(last_rejected=rec)          # 退回 gpu3 重写，卡片保持打开
                else:
                    raise ValueError("G3 只能 approve / skip / reject")
            elif card_id == "GPU3":
                if decision != "approve":
                    raise ValueError("交 gpu3 只能 approve（不批准就保持待办）")
                gate.update(status="approved", **rec)
            elif card_id == "G4":
                if decision == "approve":
                    write_json(self.ctx.orchestrator_dir / "PIPELINE_LOCKED.json",
                               {"locked_by": by, "locked_at": now(), "sample_episode": (gate.get("detail") or {}).get("episode"),
                                "note": payload.get("note", "")})   # SOP 只认带项目方原话的锁定（ns_api.sop.g4_record）
                    gate.update(status="approved", **rec)
                elif decision == "rework":
                    gate.update(last_rework=rec)
                else:
                    raise ValueError("G4 只能 approve / rework")
            self._log(st, f"{card_id} {GATES.get(card_id, '')}：{decision}（{by}）")
            self.save(st)
        return self.tick()

    def retry(self, ep: int | None, step: str) -> dict:
        with _lock(self.ctx.slug):
            st = self.load()
            rec = st["project"].get(step) if ep is None else st["episodes"].get(str(ep), {}).get("steps", {}).get(step)
            if not rec:
                raise ValueError("没有这个步骤")
            rec.update(status="pending", attempts=0, error=None, detail="项目方重试")
            self._log(st, f"{'ep%02d ' % ep if ep else ''}{STEP_LABEL.get(step, step)} 重试")
            self.save(st)
        return self.tick()

    # ------------------------------------------------------------------ 看板 / 待办
    def cards(self, st: dict | None = None) -> list[dict]:
        st = st or self.load()
        out = []
        actions = {"G2": [("approve", "确认母版", True)],
                   "G3": [("approve", "采纳加强版", True), ("skip", "跳过加强，用原剧本", False), ("reject", "退回 gpu3 重写", False)],
                   "GPU3": [("approve", "授权交 gpu3", True)],
                   "G4": [("approve", "锁定样片参数", True), ("rework", "样片返工", False)]}
        for gid in ("G2", "G3", "GPU3", "G4"):
            g = st["gates"].get(gid, {})
            if g.get("status") == "open":
                out.append({"id": gid, "project": self.ctx.slug, "project_name": self.ctx.name, "gate": gid,
                            "title": GATES[gid], "opened_at": g.get("opened_at"), "detail": g.get("detail") or {},
                            "last_rejected": g.get("last_rejected") or g.get("last_rework"),
                            "actions": [{"key": k, "label": lbl, "primary": p} for k, lbl, p in actions[gid]]})
        for ep, e in sorted(st["episodes"].items(), key=lambda kv: int(kv[0])):
            a = e["steps"].get("accept", {})
            if a.get("status") == "gate":
                final = episode_final(self.ctx, int(ep))
                out.append({"id": f"G5:ep{int(ep):02d}", "project": self.ctx.slug, "project_name": self.ctx.name,
                            "gate": "G5", "title": f"{GATES['G5']} ep{int(ep):02d}", "opened_at": a.get("opened_at"),
                            "detail": {"episode": int(ep), "final": self.ctx.rel(final) if final else None},
                            "actions": [{"key": "publish", "label": "发布", "primary": True},
                                        {"key": "rework", "label": "返工", "primary": False}]})
        return out

    def board(self) -> dict:
        st = self.load() if self.path.exists() else None
        self._mode = (st or {}).get("mode")
        gpu = {int(k): v for k, v in (st or {}).get("gpu3_view", {}).items()} if st else {}
        if not st and self.bridge is not None:
            gpu = self._gpu_view(self.bridge)
        data = read_json(self.ctx.script_json, {})
        rows, exceptions = [], []
        eta_laptop = eta_gpu3 = 0
        for e in data.get("episodes", []):
            n = e["number"]
            steps = (st or {}).get("episodes", {}).get(str(n), {}).get("steps") if st else None
            rec = gpu.get(n, {})
            lights = self._lights(n, steps, rec)
            el, eg = self._eta(n, steps, rec, len(e["shots"]))
            eta_laptop += el
            eta_gpu3 += eg
            current = next((STEP_LABEL[k] for k in EP_STEPS if steps and steps[k]["status"] not in ("done",)), None)
            rows.append({"number": n, "title": e["title"], "shots": len(e["shots"]),
                         "adult_shots": sum(bool(s.get("adult")) for s in e["shots"]), "lights": lights,
                         "current": current, "eta_s": el + eg,
                         "accept": (steps or {}).get("accept", {}).get("status")})
            for k, r in (steps or {}).items():
                if r.get("status") in ("blocked", "failed", "rework") or (r.get("status") == "waiting" and r.get("retry_at")):
                    exceptions.append({"episode": n, "step": k, "label": STEP_LABEL[k], "status": r["status"],
                                       "attempts": r.get("attempts", 0), "error": r.get("error") or r.get("detail"),
                                       "source": "gpu3" if k in GPU3_FIELD else "laptop",
                                       "retryable": k in LAPTOP_STEPS and r["status"] in ("blocked", "failed", "waiting")})
            for err in rec.get("errors") or []:
                exceptions.append({"episode": n, "step": "gpu3", "label": "gpu3", "status": "failed", "attempts": None,
                                   "error": str(err)[:300], "source": "gpu3", "retryable": False})
        if st:
            imp = st["project"].get("import", {})
            if imp.get("status") in ("blocked", "failed"):
                exceptions.insert(0, {"episode": None, "step": "import", "label": "剧本导入", "status": imp["status"],
                                      "attempts": imp.get("attempts"), "error": imp.get("error"), "source": "laptop",
                                      "retryable": True})
        gates = [{"id": k, "title": GATES[k], **{x: v for x, v in g.items() if x != "detail"}}
                 for k, g in (st or {}).get("gates", {}).items()]
        return {"project": {"slug": self.ctx.slug, "name": self.ctx.name, "is_default": self.ctx.is_default,
                            "status": self.ctx.settings().get("status") if not self.ctx.is_default else "legacy",
                            "running": bool(st and st["running"]), "mode": (st or {}).get("mode"),
                            "started_at": (st or {}).get("started_at"), "updated_at": (st or {}).get("updated_at"),
                            "can_start": not self.ctx.is_default and self.ctx.settings().get("status") == "ready"},
                "gates": gates, "episodes": rows, "exceptions": exceptions,
                "cards": self.cards(st) if st else [],
                "eta": {"laptop_s": eta_laptop, "gpu3_s": eta_gpu3, "total_s": max(eta_laptop, eta_gpu3),
                        "note": "粗估：首帧≈5 分钟/镜、尾帧≈3 分钟/镜（笔记本串行）；视频≈28 分钟/镜，gpu3 两卡并行"},
                "log": list(reversed((st or {}).get("log", [])[-30:]))}

    def _lights(self, n: int, steps: dict | None, rec: dict) -> dict:
        out = {}
        for label, key in LIGHTS:
            if key in ("first", "last"):
                fp = frame_progress(self.ctx, n, "image" if key == "first" else "last")
                status = (steps or {}).get(key, {}).get("status", "pending") if steps else "pending"
                g = normalize(rec.get("frames")) if rec else None
                if status == "done" and self._mode == "dry_run":
                    fp["laptop_done"] = fp["laptop_total"]           # 演练不真出图：按步骤状态计
                if g and g["status"] == "done":
                    fp["gpu3_done"] = fp["gpu3_total"]               # gpu3 报告本集成人帧已齐
                fp["done"] = fp["laptop_done"] + fp["gpu3_done"]
                if fp["total"] and fp["done"] >= fp["total"]:
                    status = "done"
                elif status == "done" and fp["gpu3_total"]:
                    status = "waiting"                       # 笔记本部分完成，成人镜头等 gpu3
                elif not steps and fp["done"]:
                    status = "running"
                detail = f"笔记本 {fp['laptop_done']}/{fp['laptop_total']} · gpu3 {fp['gpu3_done']}/{fp['gpu3_total']}"
                if g and g["status"] == "failed":
                    status = "failed"
                out[label] = {"status": status, "done": fp["done"], "total": fp["total"], "detail": detail}
            elif key == "script":
                if steps:
                    r = steps["script"]
                    out[label] = {"status": r["status"], "detail": r.get("detail")}
                else:
                    out[label] = {"status": "done" if self.ctx.script_json.is_file() else "pending"}
            elif key in GPU3_FIELD:
                if steps and steps["handoff"]["status"] != "done":
                    out[label] = {"status": "pending", "detail": steps["handoff"].get("detail")}
                    if steps[key]["status"] == "done":
                        out[label] = {"status": "done"}
                elif steps:
                    r = steps[key]
                    out[label] = {"status": r["status"], "done": (r.get("progress") or [None, None])[0],
                                  "total": (r.get("progress") or [None, None])[1], "detail": r.get("detail")}
                else:
                    g = normalize(rec.get(GPU3_FIELD[key]))
                    out[label] = {"status": g["status"], "done": g["done"], "total": g["total"]}
            else:  # assemble / 成片
                final = episode_final(self.ctx, n)
                if steps:
                    a, acc = steps["assemble"], steps["accept"]
                    status = a["status"]
                    if acc["status"] == "gate":
                        status = "gate"
                    elif acc["status"] == "rework":
                        status = "failed"
                    detail = {"gate": "待 G5 验收", "done": "已验收发布" if acc["status"] == "done" else None}.get(status)
                    out[label] = {"status": status, "detail": detail or a.get("detail")}
                else:
                    out[label] = {"status": "done" if final else "pending"}
        return out

    def _eta(self, n: int, steps: dict | None, rec: dict, shots: int) -> tuple[int, int]:
        if not steps:                                  # 未走编排的项目（为他而骚）：用 gpu3 桥算的 eta_s
            return 0, int(rec.get("eta_s") or 0)
        laptop_shots = len([1 for _, a in shot_ids(self.ctx, n) if not a])
        lap = 0
        for k in LAPTOP_STEPS:
            if steps[k]["status"] != "done":
                lap += EST[k] * (laptop_shots if k in ("first", "last") else 1)
        if rec.get("eta_s") is not None and steps["handoff"]["status"] == "done":
            return lap, int(rec["eta_s"])
        g = 0
        for k in GPU3_FIELD:
            if steps[k]["status"] != "done":
                g += EST[k] * (shots if k in ("video", "upscale") else 1) // (GPU3_CARDS if k in ("video", "upscale") else 1)
        return lap, g


def mode_executor(mode: str):
    from ns_orch.executors import DryRunExecutor, RealExecutor
    return DryRunExecutor() if mode == "dry_run" else RealExecutor(
        comfy_url=os.environ.get("NS_COMFY_URL", "http://127.0.0.1:8188"))
