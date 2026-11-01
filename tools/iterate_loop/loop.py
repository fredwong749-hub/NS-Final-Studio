"""自动迭代 Loop（ARCH 2026-10-31）：长期运行的 Python 驱动，不依赖 Claude 在线。

每一版（vN）：
  Shot Spec（剧本 → spec_import）→ 渲染前闸门（缺字段 / 溢出 → 交写作方）→ 选配方 + 编译（RenderPlan，带哈希）
  → 按道分配提交到 :8800（gpu33:0/1/3、gpu36:0/1；>260 帧只派 gpu36:2）→ 等待（作业丢失按 seed+提示词找回）
  → 后处理（去抖 / 肤色限幅）→ review.py 打分 → 对照配方验收阈值 → rules.yaml 规则表决定下一步
  → 未达标镜自动重出（每镜每版最多 3 次，之后“待项目方”）→ 全部落定后合成 epNN_iter_vN → 整集审片
  → 写 docs/ep02_iter/vN_review.md + vN_director_queue.md → 有效的参数调整写回配方（config/recipes/learned.yaml，
    状态升级时追加 LEARNED_SPECS「D」）。
所有动作写 events.jsonl；状态每步原子落盘，随时 Ctrl-C / pause，run 继续即恢复。

用法（项目根目录，.venv）：
  .venv/Scripts/python.exe tools/iterate_loop/loop.py start --episode 2 --dry-run [--scenario s.json]   # 不提交真实任务
  .venv/Scripts/python.exe tools/iterate_loop/loop.py start --episode 2 --run-id ep02_live              # 真跑（总调度决定）
  .venv/Scripts/python.exe tools/iterate_loop/loop.py run --run-id ep02_live         # 恢复
  .venv/Scripts/python.exe tools/iterate_loop/loop.py pause|resume|status --run-id ep02_live
  .venv/Scripts/python.exe tools/iterate_loop/loop.py next-version --run-id ep02_live  # 开下一版（重新加载写回的配方）
"""
from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (HERE, ROOT / "services" / "recipes"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import postproc  # noqa: E402
import reviewer as RV  # noqa: E402
import rules as RU  # noqa: E402
import submitter as SB  # noqa: E402
import writeback as WB  # noqa: E402
from ns_recipes import compiler as C  # noqa: E402
from ns_recipes import registry as R  # noqa: E402
from ns_recipes import selector as SEL  # noqa: E402
from ns_recipes import spec_import as SI  # noqa: E402
from ns_schema.shot_spec import ShotSpec, check_sequence, missing_fields  # noqa: E402
from store import Store, now  # noqa: E402

TERMINAL = {"passed", "owner", "needs_writer", "needs_keyframe", "needs_api", "blocked", "failed"}
RENDER_ACTIONS = {"reseed", "override", "recipe"}


class Loop:
    def __init__(self, store: Store, *, specs: list[ShotSpec], registry: R.Registry, submitter, reviewer, post,
                 rules: dict, assembler=None, learned_path: Path | None = None, docs_dir: Path | None = None,
                 log=print):
        self.store, self.specs = store, {s.id: s for s in specs}
        self.reg, self.sub, self.rev, self.post = registry, submitter, reviewer, post
        self.rules, self.assembler = rules, assembler
        self.learned_path = learned_path or WB.LEARNED
        self.docs_dir = docs_dir or WB.DOC_DIR
        self.log = log
        self.lanes = SB.LaneAllocator()
        self.max_renders = int(rules["settings"]["max_renders_per_shot"])
        self.state = store.load()

    @property
    def dry(self) -> bool:
        return bool(getattr(self.sub, "dry", False))

    # ------------------------------------------------------------------ 初始化 / 版本
    def init(self, episode: int, shots: list[str] | None = None) -> dict:
        if self.state:
            return self.state
        ids = [s for s in self.specs if not shots or s in shots]
        self.state = {"schema": "nsfs.iterate_state/1", "run_id": self.store.run_id, "episode": episode,
                      "dry_run": self.dry, "version": 1, "status": "running", "created_at": now(),
                      "registry_hash": self.reg.source_hash,
                      "versions": {"1": {"started": now(), "effects": [], "writeback": []}},
                      "shots": {sid: self._fresh_shot() for sid in ids}}
        self.store.save(self.state)
        self.store.event("init", episode=episode, shots=ids, dry_run=self.dry, registry=self.reg.source_hash)
        seq = [self.specs[s] for s in ids]
        seq_issues = [m.model_dump() for m in check_sequence(seq)]
        if seq_issues:
            self.store.event("sequence_check", issues=seq_issues)
        return self.state

    @staticmethod
    def _fresh_shot() -> dict:
        return {"status": "pending", "renders": 0, "overrides": {}, "recipe": None, "recipe_override": None,
                "tried_recipes": [], "rule_steps": {}, "actions": [], "lost": 0, "errors": 0}

    def next_version(self) -> dict:
        st = self.state
        v = st["version"] + 1
        st["version"] = v
        st["status"] = "running"
        st["registry_hash"] = self.reg.source_hash
        st["versions"][str(v)] = {"started": now(), "effects": [], "writeback": []}
        for sid, sh in st["shots"].items():
            if sh["status"] == "passed":
                carry = {k: sh.get(k) for k in ("plan_hash", "file", "post_file", "local_path", "take", "metrics",
                                                "sheet", "recipe", "overrides", "recipe_override", "renders")}
                st["shots"][sid] = {**self._fresh_shot(), "carry": carry}
            elif sh["status"] in ("needs_api", "blocked"):
                st["shots"][sid] = self._fresh_shot()   # 接入点 / 资料可能已经补上
            elif sh["status"] in ("owner", "needs_writer", "needs_keyframe", "failed"):
                st["shots"][sid] = {**self._fresh_shot(), "status": sh["status"], "note": sh.get("note"),
                                    "carried_from": v - 1}
        self.store.save(st)
        self.store.event("next_version", version=v, registry=self.reg.source_hash)
        return st

    # ------------------------------------------------------------------ 编译
    def _compile(self, sid: str, sh: dict) -> dict:
        spec = self.specs[sid]
        sel = SEL.select(spec, self.reg)
        rid = sh.get("recipe_override") or sel.recipe_id
        plan = C.compile_shot(spec, self.reg, attempt=sh["renders"] + 1, recipe_id=rid,
                              overrides=sh["overrides"], selection=sel)
        if plan.get("plan_hash"):
            self.store.save_plan(plan)
        return plan

    def _set(self, sid: str, sh: dict, status: str, note: str | None = None, **kw):
        old = sh["status"]
        sh["status"] = status
        if note:
            sh["note"] = note
        sh.update(kw)
        self.store.event("shot", shot=sid, frm=old, to=status, note=note, **{k: v for k, v in kw.items()
                                                                             if k in ("plan_hash", "job_id", "lane")})

    # ------------------------------------------------------------------ tick
    def tick(self) -> bool:
        st = self.state
        if self.store.paused():
            return False
        if st["status"] != "running":
            return False
        moved = self._apply_verdicts()
        ll = getattr(self.sub, "lane_load", None)
        self._ext = ll() if callable(ll) and any(sh["status"] == "queued" for sh in st["shots"].values()) else None
        busy = {}
        for sh in st["shots"].values():
            if sh["status"] == "running" and sh.get("lane") is not None:
                busy[str(sh["lane"])] = busy.get(str(sh["lane"]), 0) + 1
        for sid in list(st["shots"]):
            sh = st["shots"][sid]
            try:
                moved |= self._step(sid, sh, busy)
            except Exception as e:  # noqa: BLE001  单镜失败隔离：记录，不影响其他镜
                sh["errors"] = sh.get("errors", 0) + 1
                self.store.event("error", shot=sid, error=f"{type(e).__name__}: {e}")
                if sh["errors"] >= 3:
                    self._set(sid, sh, "failed", f"连续出错：{e}")
                moved = True
            self.store.save(st)
        if all(sh["status"] in TERMINAL for sh in st["shots"].values()):
            self._finish_version()
            moved = True
        self.store.save(st)
        return moved

    def _step(self, sid: str, sh: dict, busy: dict) -> bool:
        s = sh["status"]
        if s == "pending":
            return self._do_pending(sid, sh)
        if s == "queued":
            return self._do_submit(sid, sh, busy)
        if s == "running":
            return self._do_poll(sid, sh, busy)
        if s == "rendered":
            return self._do_review(sid, sh)
        return False

    def _do_pending(self, sid, sh) -> bool:
        spec = self.specs[sid]
        issues = missing_fields(spec)
        pre = RU.pre_render(self.rules, issues)
        if pre:
            self._set(sid, sh, "needs_writer" if pre.get("owner") == "writer" else "failed",
                      f"{pre['rule']}：{pre.get('note')}（{', '.join(pre['codes'])}）")
            sh["spec_issues"] = [i.model_dump() for i in issues if i.severity in ("block", "asset")]
            return True
        carry = sh.get("carry") or {}
        if carry.get("plan_hash") and carry.get("file"):
            trial = {**self._fresh_shot(), "overrides": carry.get("overrides") or {},
                     "recipe_override": carry.get("recipe_override"), "renders": max(0, (carry.get("renders") or 1) - 1)}
            if self._compile(sid, trial)["plan_hash"] == carry["plan_hash"]:
                sh.update({k: v for k, v in carry.items() if k != "renders"})
                sh.pop("carry", None)
                self._set(sid, sh, "passed", "沿用上一版（配方与计划哈希未变）")
                return True
            self.store.event("carry_changed", shot=sid, note="配方或写回参数变了，重出")
            sh.pop("carry", None)
        plan = self._compile(sid, sh)
        sh["recipe"] = plan["recipe"]["id"]
        if plan["status"] == "needs_writer":
            self._set(sid, sh, "needs_writer", plan.get("reason"))
            return True
        if plan["status"] == "lint_error":
            errs = [i for i in plan["lint"] if i["level"] == "error"]
            self._set(sid, sh, "needs_writer", "；".join(f"{i['code']} {i['message']}" for i in errs))
            return True
        sh["plan_hash"] = plan["plan_hash"]
        sh["plan_long"] = plan["lane"]["long"]
        self._set(sid, sh, "queued", plan_hash=plan["plan_hash"])
        return True

    def _plan(self, sh) -> dict:
        return json.loads((self.store.dir / "plans" / f"{sh['plan_hash'][:16]}.json").read_text(encoding="utf-8"))

    def _do_submit(self, sid, sh, busy) -> bool:
        plan = self._plan(sh)
        ext = getattr(self, "_ext", None)
        lane = self.lanes.pick(plan["lane"]["long"], busy, ext, plan["lane"].get("only"))
        if lane is None:
            cands = self.lanes.long if plan["lane"]["long"] else self.lanes.normal
            only = plan["lane"].get("only")
            if only:
                cands = [g for g in cands if str(g) in {str(x) for x in only}]
            if not cands:   # V2：本 run 的道里没有能跑这个计划的（例：方案 A 只有 gpu33，长镜头 >260 帧）
                self._set(sid, sh, "owner", "本 run 可用道里没有能跑这个计划的道（长镜头 / 权重不在），交其他方案或项目方")
                return True
            return False
        res = self.sub.submit(plan, lane)
        stt = res["state"]
        if stt == "needs_api":
            self._set(sid, sh, "needs_api", f"API 表达不了：{res['unsupported']}（待接入点）")
        elif stt == "blocked":
            self._set(sid, sh, "blocked", f"API 409：{res.get('detail')}", missing=res.get("missing"))
        elif stt == "error":
            sh["errors"] = sh.get("errors", 0) + 1
            self.store.event("submit_error", shot=sid, detail=res)
            if sh["errors"] >= 3:
                self._set(sid, sh, "failed", f"提交失败：{res.get('detail')}")
        else:
            sh["renders"] += 1
            busy[str(lane)] = busy.get(str(lane), 0) + 1
            if ext is not None:
                ext[str(lane)] = ext.get(str(lane), 0) + 1
            self._set(sid, sh, "running", job_id=res["job_id"], lane=lane, submitted_at=now())
        return True

    def _do_poll(self, sid, sh, busy) -> bool:
        plan = self._plan(sh)
        res = self.sub.poll(sh["job_id"], plan)
        stt = res["state"]
        if stt == "done":
            self.store.save_result(sid, sh["renders"], self.state["version"],
                                   {"job": res, "plan_hash": sh["plan_hash"], "lane": sh["lane"], "at": now()})
            busy[str(sh["lane"])] = max(0, busy.get(str(sh["lane"]), 1) - 1)
            self._set(sid, sh, "rendered", take=res.get("take"), file=res.get("file"),
                      local_path=res.get("local_path"), recovered=res.get("recovered", False))
            return True
        if stt == "lost":
            sh["lost"] += 1
            sh["renders"] = max(0, sh["renders"] - 1)       # 丢失不计出片次数
            if sh["lost"] > int(self.rules["settings"]["max_lost_resubmits"]):
                self._set(sid, sh, "failed", "API 作业多次丢失")
            else:
                self._set(sid, sh, "queued", "API 作业丢失（可能重启），重交")
            return True
        if stt in ("failed", "cancelled"):
            self.store.event("render_failed", shot=sid, error=res.get("error"))
            self._react(sid, sh, [{"metric": "render_failed", "value": res.get("error"), "threshold": None}],
                        {"_acceptance_failed": True})
            return True
        return False

    # ------------------------------------------------------------------ 审片 + 规则
    def _do_review(self, sid, sh) -> bool:
        plan = self._plan(sh)
        src = Path(sh.get("local_path") or (ROOT / "data" / (sh.get("file") or "")))
        tag = f"v{self.state['version']}a{sh['renders']}_{sh['plan_hash'][:8]}"
        out, steps = self.post.apply(sid, tag, src, plan["post"])
        sh["post_file"], sh["post_steps"] = str(out), steps
        name = f"{self.store.run_id}_v{self.state['version']}_{sid}_a{sh['renders']}_{sh['plan_hash'][:6]}"
        metrics = self.rev.clips(name, {sid: str(out)})[sid]
        sh["sheet"], sh["flags"] = metrics.pop("_sheet", None), metrics.pop("_flags", [])
        sh["metrics"] = metrics
        fails = RV.failures(metrics, plan["acceptance"])
        sh["last_failures"] = fails
        self._settle_effect(sid, sh, metrics, fails)
        self.store.save_result(sid, sh["renders"], self.state["version"],
                               {"plan_hash": sh["plan_hash"], "post_only_of": sh.get("post_only_of"), "source_file": sh.get("file"),
                                "post": steps, "metrics": metrics, "failures": fails,
                                "review": name, "at": now()})
        self.store.event("reviewed", shot=sid, failures=fails, post=steps)
        if not fails:
            self._set(sid, sh, "passed")
            return True
        self._react(sid, sh, fails, {**metrics, "_acceptance_failed": True})
        return True

    def _settle_effect(self, sid, sh, metrics, fails):
        pe = sh.pop("pending_effect", None)
        if not pe:
            return
        rule = next((r for r in self.rules["rules"] if r["id"] == pe["rule"]), None)
        still = RU.cond(rule["when"], {**metrics, "_acceptance_failed": bool(fails)}) if rule and rule.get("when") else bool(fails)
        ef = {**pe, "ok": not still, "after": {k: metrics.get(k) for k in pe.get("before", {})},
              "run": self.store.run_id, "version": self.state["version"], "shot": sid}
        self.state["versions"][str(self.state["version"])]["effects"].append(ef)
        self.store.event("effect", **{k: ef[k] for k in ("rule", "ok", "shot")}, effect_kind=ef["kind"], action=pe.get("action"))   # V2：kind 与 event(kind) 撞名 → TypeError

    def _react(self, sid, sh, fails, metrics):
        plan = self._plan(sh)
        matched = RU.matching(self.rules, metrics) or [r for r in self.rules["rules"] if r["id"] == "R-DEFAULT"]
        rule = matched[0]
        start = sh["rule_steps"].get(rule["id"], 0)
        for i, step in RU.ladder_step(rule, start)[: len(rule["ladder"])]:
            if i < start:
                continue
            ok, why = self._apply_step(sid, sh, plan, rule, step, metrics)
            sh["rule_steps"][rule["id"]] = i + 1
            if ok:
                sh["actions"].append({"rule": rule["id"], "action": step["action"], "step": i, "attempt": sh["renders"],
                                      "note": step.get("note"), "set": step.get("set"), "to": step.get("to")})
                self.store.event("action", shot=sid, rule=rule["id"], action=step["action"], step=i, why=why)
                return
            self.store.event("step_skipped", shot=sid, rule=rule["id"], action=step["action"], step=i, why=why)
        self._set(sid, sh, "owner", f"{rule['id']} 阶梯用尽（{rule.get('note')}）")

    def _render_budget(self, sh) -> bool:
        return sh["renders"] < self.max_renders

    def _effect(self, rule, step, plan, metrics, kind, path=None, value=None):
        keys = [k for k in ("still_frac", "frozen_tail_s", "J4", "J4_z", "cheek_a_drift", "cheek_red_max",
                            "red_blob_max", "sface_ref_min", "sface_self_min", "dark_run_s", "lipsync_corr") if k in metrics]
        return {"rule": rule["id"], "action": step["action"], "kind": kind, "recipe": plan["recipe"]["id"],
                "path": path, "value": value, "before": {k: metrics[k] for k in keys},
                "plans": [plan["plan_hash"][:16]]}

    def _try_compile(self, sid, sh_trial) -> dict:
        return self._compile(sid, sh_trial)

    def _apply_step(self, sid, sh, plan, rule, step, metrics) -> tuple[bool, str]:
        act = step["action"]
        sets = self.rules["settings"]
        if act in ("fail", "owner", "keyframe"):
            status = {"fail": "needs_writer" if step.get("owner") == "writer" else "failed", "owner": "owner",
                      "keyframe": "needs_keyframe"}[act]
            self._set(sid, sh, status, f"{rule['id']}：{step.get('note') or rule.get('note')}")
            return True, act
        if act == "post":
            changes = {p: v for p, v in (step.get("set") or {}).items()
                       if R.get_path({"post": plan["post"]}, p) != v}
            if not changes:
                return False, "后处理已开"
            trial = copy.deepcopy(sh)
            trial["overrides"].update(changes)
            trial["renders"] = max(0, sh["renders"] - 1)       # 同一次出片，编译 attempt 不变
            new = self._try_compile(sid, trial)
            sh["overrides"].update(changes)
            sh["pending_effect"] = self._effect(rule, step, plan, metrics, "param", *next(iter(changes.items())))
            sh["post_only_of"] = sh.get("post_only_of") or plan["plan_hash"]   # V2：只改后处理，视频源不变（同一次出片）
            sh["plan_hash"] = new["plan_hash"]
            self._set(sid, sh, "rendered", f"{rule['id']}：后处理 {changes}", plan_hash=new["plan_hash"])
            return True, f"post {changes}"
        if not self._render_budget(sh):
            return False, f"已出 {sh['renders']} 次（上限 {self.max_renders}）"
        trial = copy.deepcopy(sh)
        kind, path, value = "ladder", None, None
        if act == "reseed":
            trial["overrides"]["seed.offset"] = int(trial["overrides"].get("seed.offset", 0)) + 1
        elif act == "override":
            cur = plan["params"]
            changes = {p: v for p, v in (step.get("set") or {}).items() if R.get_path(cur, p) != v}
            if not changes:
                return False, "参数已是目标值"
            trial["overrides"].update(changes)
            kind, (path, value) = "param", next(iter(changes.items()))
        elif act == "recipe":
            tried = set(sh["tried_recipes"]) | {plan["recipe"]["id"]}
            if step.get("to") == "fallback":
                cands = [x for x in plan["selection"]["fallback"] if x not in tried]
            else:
                cands = [step["to"]] if step["to"] not in tried else []
            cands = [x for x in cands if x in self.reg.raw and (sets.get("allow_license_pending")
                                                               or self.reg.raw[x].get("status") != "待许可登记")]
            if not sets.get("allow_experimental_fallback"):
                cands = [x for x in cands if self.reg.raw[x].get("status") in ("确认", "建议")]
            if not cands:
                return False, "没有可用的回退配方"
            trial["recipe_override"] = cands[0]
            trial["tried_recipes"] = sorted(tried | {cands[0]})
            trial["overrides"] = {k: v for k, v in trial["overrides"].items() if k.startswith("seed.")}
        new = self._try_compile(sid, trial)
        if new["status"] != "ready":
            return False, f"编译不过：{new['status']}"
        if sets.get("skip_api_incompatible") and not getattr(self.sub, "dry", False)                 and not getattr(self.sub, "graph_passthrough", False) and not new["api"]["compatible"]:
            return False, f"API 表达不了 {new['api']['unsupported']}"
        sh.update({k: trial[k] for k in ("overrides", "recipe_override", "tried_recipes")})
        sh["pending_effect"] = self._effect(rule, step, plan, metrics, kind, path, value)
        sh.pop("post_only_of", None)   # 新出片
        sh["plan_hash"] = new["plan_hash"]
        sh["recipe"] = new["recipe"]["id"]
        self._set(sid, sh, "queued", f"{rule['id']}：{act}", plan_hash=new["plan_hash"])
        return True, act

    # ------------------------------------------------------------------ 剪辑导演接口
    def _apply_verdicts(self) -> bool:
        vd = self.store.verdicts()
        used = self.state.setdefault("verdicts_used", {})
        moved = False
        for sid, v in vd.items():
            sh = self.state["shots"].get(sid)
            key = json.dumps(v, ensure_ascii=False, sort_keys=True)
            if not sh or used.get(sid) == key or sh["status"] != "passed" or v.get("verdict") != "fail":
                continue
            used[sid] = key
            self.store.event("director_verdict", shot=sid, verdict=v)
            if v.get("action") == "reseed" and self._render_budget(sh):
                sh["overrides"]["seed.offset"] = int(sh["overrides"].get("seed.offset", 0)) + 1
                sh["actions"].append({"rule": "R-DIRECTOR", "action": "reseed", "note": v.get("note")})
                self._set(sid, sh, "pending", f"剪辑导演：{v.get('issues')}")
            else:
                self._set(sid, sh, "owner", f"剪辑导演：{v.get('issues')} {v.get('note') or ''}")
            moved = True
        return moved

    # ------------------------------------------------------------------ 收版
    def _finish_version(self):
        st = self.state
        v = st["version"]
        vr = st["versions"][str(v)]
        passed = {sid: sh for sid, sh in st["shots"].items() if sh["status"] == "passed"}
        ep_review = None
        if passed and self.assembler is not None:
            res = self.assembler(st, passed, self.store.dir)
            vr["assembled"] = res.get("video") or res.get("command")
            vr["assemble"] = res
            for w in res.get("overflow_shots", []):
                st["shots"][w]["status"] = "needs_writer"
                st["shots"][w]["note"] = "合成时独白 / 对白溢出到后面镜头（R-OVERFLOW）"
            if res.get("video") and res.get("timeline"):
                try:
                    ep_review = self.rev.episode(f"{st['run_id']}_v{v}", res["video"], res["timeline"])
                except Exception as e:  # noqa: BLE001
                    self.store.event("episode_review_error", error=str(e))
        changed = WB.record(vr["effects"], self.rules, learned_path=self.learned_path,
                            dry_run=bool(st.get("dry_run")) and self.learned_path == WB.LEARNED)
        vr["writeback"] = changed
        vr["finished"] = now()
        # dry-run 的报告写在 run 目录里，不混进 docs/ep02_iter
        out_dir = self.store.dir if (st.get("dry_run") and self.docs_dir == WB.DOC_DIR) else self.docs_dir
        rv = WB.version_review(st, ep_review, out_dir / f"v{v}_review.md")
        dq = WB.director_queue(st, out_dir / f"v{v}_director_queue.md")
        vr["docs"] = [str(rv), str(dq)]
        st["status"] = "version_done"
        self.store.event("version_done", version=v, passed=len(passed), docs=vr["docs"],
                         writeback=[e["key"] for e in changed])
        self.log(f"[loop] v{v} 完成：{len(passed)}/{len(st['shots'])} 镜通过 → {rv}")

    # ------------------------------------------------------------------ 主循环
    def run(self, poll_s: float = 30.0, max_ticks: int | None = None, sleep=time.sleep) -> dict:
        n = 0
        while self.state["status"] == "running":
            if self.store.paused():
                self.log("[loop] 已暂停（删 PAUSE 或 loop.py resume 继续）")
                break
            moved = self.tick()
            n += 1
            if max_ticks is not None and n >= max_ticks:
                break
            if not moved and self.state["status"] == "running":
                sleep(poll_s)
        return self.state


# ---------------------------------------------------------------------- 合成
def make_assembler(dry: bool):
    def assemble(state: dict, passed: dict, run_dir: Path) -> dict:
        ep = state["episode"]
        v = state["version"]
        shots = []
        for sid, sh in sorted(passed.items(), key=lambda kv: int(kv[0].split("-S")[1])):
            f = Path(sh.get("post_file") or (ROOT / "data" / (sh.get("file") or "")))
            rel = str(f.relative_to(ROOT)).replace("\\", "/") if f.is_absolute() and f.is_relative_to(ROOT) else str(f)
            shots.append({"shot": sid, "index": int(sid.split("-S")[1]), "kind": "video", "file": rel,
                          "origin": "iterate_loop", "plan_hash": sh.get("plan_hash")})
        src = run_dir / f"v{v}_sources.timeline.json"
        src.write_text(json.dumps({"episode": ep, "shots": shots}, ensure_ascii=False, indent=1), encoding="utf-8")
        variant = f"iter_v{v}"
        cmd = [str(ROOT / ".venv" / "Scripts" / "python.exe"), str(ROOT / "tools" / "assemble_episode.py"), f"ep{ep:02d}",
               "--sources-from", str(src), "--variant", variant, "--dialogue-source", "h3",
               "--h3-music", "duck_under_bgm", "--no-skin-guard"]
        if dry:
            return {"dry_run": True, "command": " ".join(cmd), "sources": str(src)}
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(ROOT))
        if r.returncode != 0:
            return {"error": (r.stderr or r.stdout)[-800:], "command": " ".join(cmd)}
        vids = sorted((ROOT / "data" / "episodes").glob(f"ep{ep:02d}*_{variant}.mp4"), key=lambda p: p.stat().st_mtime)
        if not vids:
            return {"error": "合成后找不到输出文件", "command": " ".join(cmd)}
        video = vids[-1]
        tl = video.with_suffix(".timeline.json")
        over = []
        if tl.exists():
            tj = json.loads(tl.read_text(encoding="utf-8"))
            for w in tj.get("warnings", []):
                if "voiceover" in w and ("runs" in w or "overlaps" in w):
                    s = w.split(":")[0].strip()
                    over.append(f"ep{ep:02d}-{s}")
        return {"video": str(video), "timeline": str(tl), "overflow_shots": sorted(set(over) & set(passed)),
                "command": " ".join(cmd)}
    return assemble


# ---------------------------------------------------------------------- CLI
def build(args, store: Store, state: dict | None) -> Loop:
    episode = args.episode or (state or {}).get("episode")
    dry = args.dry_run if state is None else bool(state.get("dry_run"))
    reg = R.load()
    if args.script:
        specs = SI.specs_from_markdown(Path(args.script), episode)
    else:
        from ns_render import pipeline as P
        specs = SI.specs_from_import(P.load_script(), episode)
    if dry:
        sub, rev, post = SB.DryRunSubmitter(), RV.ScriptedReviewer(RV.load_scenario(args.scenario)), postproc.DryPostRunner()
    else:
        gp = args.graph_passthrough or bool(RU.load()["settings"].get("api_graph_passthrough"))
        sub, rev, post = SB.ApiSubmitter(args.api, graph_passthrough=gp), RV.ReviewPy(), postproc.PostRunner(store.dir / "post")
    loop = Loop(store, specs=specs, registry=reg, submitter=sub, reviewer=rev, post=post, rules=RU.load(),
                assembler=make_assembler(dry))
    # V2（方案 A/B 并行）：--lanes / --long-lanes 限定本 run 能用的道，记进 state，run 恢复时沿用
    lanes = getattr(args, "lanes", None)
    long_lanes = getattr(args, "long_lanes", None)
    if loop.state:
        lanes = lanes if lanes is not None else loop.state.get("lanes")
        long_lanes = long_lanes if long_lanes is not None else loop.state.get("long_lanes")
    def _parse(v):
        return [int(x) if x.strip().isdigit() else x.strip() for x in v.split(",") if x.strip()]
    if lanes is not None:
        loop.lanes.normal = _parse(lanes)
    if long_lanes is not None:
        loop.lanes.long = _parse(long_lanes)
    if loop.state is not None and (lanes is not None or long_lanes is not None):
        loop.state["lanes"], loop.state["long_lanes"] = lanes, long_lanes
        store.save(loop.state)
    if dry and loop.state:   # dry-run 恢复：内存里的假作业没了 → 正在跑的退回待提交（不计次数）
        for sh in loop.state["shots"].values():
            if sh["status"] == "running":
                sh["status"] = "queued"
                sh["renders"] = max(0, sh["renders"] - 1)
    return loop


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("start", "run", "next-version", "pause", "resume", "status"))
    ap.add_argument("--run-id")
    ap.add_argument("--episode", type=int)
    ap.add_argument("--script", help="剧本 Markdown（默认用 API 当前导入的剧本 data/import/script_v2.json）")
    ap.add_argument("--shots", help="只跑这些镜，逗号分隔（ep02-S1,ep02-S2）")
    ap.add_argument("--dry-run", action="store_true", help="不提交真实任务（假提交 + 脚本审片）")
    ap.add_argument("--scenario", help="dry-run 审片指标脚本 JSON：{镜: [指标, …]}")
    ap.add_argument("--api", default=SB.API)
    ap.add_argument("--graph-passthrough", action="store_true",
                    help="API 已带 recipe_plan.graph 接入点（重启后）：Ref2VA / 两段式等按图原样提交")
    ap.add_argument("--poll", type=float, default=30.0)
    ap.add_argument("--max-ticks", type=int)
    ap.add_argument("--lanes", help="本 run 普通镜头可用的道，逗号分隔（例 0,1,3）；默认 6 道")
    ap.add_argument("--long-lanes", help="长镜头可用的道（例 gpu36:2；空串 = 没有）")
    a = ap.parse_args(argv)
    run_id = a.run_id or (f"ep{a.episode:02d}_{'dry' if a.dry_run else 'live'}_{time.strftime('%Y%m%d_%H%M%S')}"
                          if a.episode else None)
    if not run_id:
        ap.error("需要 --run-id（或 start 时给 --episode）")
    store = Store(run_id)
    if a.cmd == "pause":
        store.pause("loop.py pause")
        print("已暂停", run_id)
        return 0
    if a.cmd == "resume":
        store.resume()
        print("已恢复（再执行 loop.py run 继续）", run_id)
        return 0
    state = store.load()
    if a.cmd == "status":
        if not state:
            print("没有这个 run")
            return 1
        print(json.dumps({"run": run_id, "version": state["version"], "status": state["status"],
                          "paused": store.paused(),
                          "shots": {k: {"status": v["status"], "renders": v["renders"], "recipe": v.get("recipe"),
                                        "note": v.get("note")} for k, v in state["shots"].items()}},
                         ensure_ascii=False, indent=1))
        return 0
    if a.cmd == "start" and state:
        print("run 已存在，改用 run 继续", run_id)
    loop = build(a, store, state)
    if a.cmd == "start" and not state:
        loop.init(a.episode, [s.strip() for s in a.shots.split(",")] if a.shots else None)
    elif a.cmd == "next-version":
        loop.next_version()
    print(f"[loop] run={run_id} dry_run={loop.dry} dir={store.dir}")
    loop.run(poll_s=0.0 if loop.dry else a.poll, max_ticks=a.max_ticks)
    print(f"[loop] 状态：{loop.state['status']}（loop.py status --run-id {run_id}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
