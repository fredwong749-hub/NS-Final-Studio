"""出图作业的提示词一律经系统编译器（PROMPT 2026-10-31，knowledge K-REN-103）。

问题：series10 的首帧作业由 SERIES / IMGGEN 自己拼提示词，绕开了 ns_agent.compiler——视频身份触发词 lnwan01 混进了 16 条
图像提示词（tools/prompt_v2/audit_framing.py），景别取舍（K-REN-101）、触发词 / LoRA 规则、材质条目、纠正器条目、风格后缀都
没有自动生效。本模块是流水线（tools/pipeline/*）与 IMGGEN 共用的唯一出图提示词入口：

  frame_prompt(ep, shot, globals, refs, project) → (提示词, CompiledShot)
      = 参考图角色说明（“图N是<角色>的脸部参考（只取脸和发型）。”，按 refs 顺序；只加参考说明）
      + ns_agent.compiler.compile_shot(...).image_prompt（触发词剥离 / 只保留可用的出图 LoRA 触发词、角色锁、造型注入、
        景别取舍 framing、材质 / 纠正器条目、镜头锐度句、剧本统一后缀）
  rebuild_first_frame_jobs(run_dir) → 重写 assets/first_frame_jobs.json 的 prompt / graph（其余字段：seed、out、refs、
      on_screen、priority、status 原样保留；提示词变了的作业记 prompt_changed，原图标 needs_rerender）

P4 剧本分镜没有全局头，触发词表、角色锁、统一后缀取当前已导入剧本的 globals（data/import/script_v2.json，系统登记的
触发词表），并用它把每镜 img / motion 开头的触发词识别出来（与导入器同一规则：句首、逗号分隔、在触发词表里）。
LoRA：可用集合 = 6 道都装了的出图 LoRA（2026-10-31 21:55 查过 /object_info：lin_wan_qi_v1 六道都有；wardrobe / jewellery
系列没核对 → 不算可用，编译器按规则剥掉其触发词）；编译器选中的 image_loras 原样挂进作业图（LoraLoaderModelOnly）。
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/agent", "packages/schema", "services/render_router", "tools/prompt_v2"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

from ns_agent import compiler as C  # noqa: E402
from ns_agent.bible import load_bible  # noqa: E402
from ns_agent.importer.script_md import import_script  # noqa: E402

FACE_CID = {"林晚": "lin_wan", "顾沉": "gu_chen", "陈宇": "chen_yu", "阿岚": "ch_a_lan"}   # 在画角色 → 身份脸 cid；脸本身一律 asset_refs.face_of（K-OPS-E29）


def core_faces(project: str | None = None) -> dict:
    """在画角色名 → 当前身份脸（asset_refs.face_of；project 缺省 = config/pipeline/runs.json primary）。替代旧的写死表 CORE_FACES / EXTRA_FACES"""
    from ns_agent import asset_refs as AR
    if not project:
        project = json.loads((ROOT / "config/pipeline/runs.json").read_text(encoding="utf-8")).get("primary")
    return {n: f for n, cid in FACE_CID.items() if (f := AR.face_of(project, cid))}
SHEET_REFS = {"顾沉": "images/refs/gu_chen_sheet2.png", "陈宇": "images/refs/chen_yu_sheet2.png"}   # 相对 run 目录
AVAILABLE_IMAGE_LORAS: set[str] = set()   # 11-01：lin_wan_qi_v1 已禁用（I8 / 项目方“A. 去掉”）；出图 LoRA 由预设 frame_v9 给（krea2 0.5）
FACE_NAME = {"lin_wan": "林晚", "gu_chen": "顾沉", "chen_yu": "陈宇", "ch_a_lan": "阿岚"}


def production_globals():
    from ns_render import pipeline as P
    return P.load_script().globals


def _split_triggers(text: str, table: set[str]) -> tuple[list[str], str]:
    toks = [t.strip() for t in (text or "").split("，")]
    trig = []
    for t in toks:
        if t in table or t.startswith("pose_"):
            trig.append(t)
        else:
            break
    return trig, text


def retrigger(shot, g):
    """P4 没有全局头 → 导入器认不出触发词；按系统触发词表把句首触发词标出来（编译器据此剥离 / 保留）"""
    table = {t.trigger for t in g.lora_triggers}
    it, _ = _split_triggers(shot.img_prompt, table)
    mt, _ = _split_triggers(shot.motion_prompt, table)
    return shot.model_copy(update={"img_triggers": it or list(shot.img_triggers),
                                   "motion_triggers": mt or list(shot.motion_triggers)})


def merged_globals(series_globals, prod_globals):
    """触发词表 / 统一后缀 / 角色锁以系统登记为准；P4 自带的（有的话）补在后面"""
    g = prod_globals.model_copy(deep=True)
    names = {c.name for c in g.character_locks}
    extra = [c for c in (series_globals.character_locks or []) if c.name not in names]
    if extra:
        g = g.model_copy(update={"character_locks": [*g.character_locks, *extra]})
    return g


def role_lines(refs: list[str]) -> str:
    out = []
    for i, r in enumerate(refs, 1):
        cid = next((k for k in FACE_NAME if f"/{k}/" in r.replace("\\", "/") or f"/{k}_" in r.replace("\\", "/")), None)
        if cid and "_sheet2" in r:
            out.append(f"图{i}是{FACE_NAME[cid]}的设定图（只取脸、发型和体型，不取服装）。")
        elif cid:
            out.append(f"图{i}是{FACE_NAME[cid]}的脸部参考（只取脸和发型）。")
    return "".join(out)


def asset_mode(project: str | None) -> bool:
    """项目在 config/recipes/asset_refs.json 里登记了造型 / 资产 → 走资产参考锁定（REFLOCK，契约 I2–I5、I9）"""
    from ns_agent import asset_refs as AR
    return bool(project and AR.project_cfg(project))


def frame_prompt_full(ep, shot, g, refs: list[str], project: str | None, bible=None, available=None,
                      model: str = "qwen_image_2.1", assets: bool | None = None):
    """→ (提示词, CompiledShot, ShotRefs | None, SlotPlan | None)。实现在 ns_agent.frame_job.compile_frame（K-REN-134：
    全系统唯一出图路径，画布重出 / 尾帧 / 编辑整图重出 / IMGGEN / ASSETMASTER 同一函数）。
    assets=False = 旧做法（只挂脸，对照实验“无资产参考”组用），refs 原样。"""
    from ns_agent import frame_job as FJ
    av = AVAILABLE_IMAGE_LORAS if available is None else set(available)
    return FJ.compile_frame(ep, retrigger(shot, g), g, project, bible=bible, available=av, assets=assets, model=model,
                            legacy_refs=refs, role_lines=role_lines)


def frame_prompt(ep, shot, g, refs: list[str], project: str | None, bible=None, available=None, **kw):
    p, c, _sr, _plan = frame_prompt_full(ep, shot, g, refs, project, bible, available, **kw)
    return p, c


def cast_of(shot) -> list[dict]:
    return [{"name": c.name, "presence": c.presence, "x": getattr(c, "x", None), "depth": getattr(c, "depth", None)}
            for c in (getattr(shot, "cast", None) or [])]


def contract_request(j: dict) -> dict:
    """首帧作业 → 生成契约 preflight 请求（ns_agent.gen_contract.preflight）"""
    gp = next((x["inputs"]["prompt"] for x in (j.get("graph") or {}).values()
               if x.get("class_type") in ("TextEncodeQwenImage21", "TextEncodeQwenImageEditPlus")), j.get("prompt"))
    return {"kind": "image", "model": j.get("model") or "qwen_image_2.1", "project": j.get("framing_project"),
            "shot_id": j.get("shot"), "cast": j.get("cast"), "prompt": gp, "refs": list(j.get("refs") or []),
            "asset_refs": j.get("asset_refs"), "loras": j.get("loras") or [], "compiled_by": j.get("compiled_by")}


def with_loras(graph: dict, loras) -> dict:
    """编译器选中的出图 LoRA 挂到 UNET 后（模型侧），CFGGuider / BasicScheduler 改接最后一个 LoRA"""
    model = ["1", 0]
    for k, (f, w) in enumerate(loras or []):
        nid = f"30{k}"
        graph[nid] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": model, "lora_name": f, "strength_model": float(w)}}
        model = [nid, 0]
    graph["6"]["inputs"]["model"] = model
    graph["9"]["inputs"]["model"] = model
    return graph


IMPORT_JSON = ROOT / "data" / "import" / "script_v2.json"
ALLOW_P4_ENV = "NS_ALLOW_P4_SOURCE"


class LegacySourceError(RuntimeError):
    """K-OPS-Q24：生产出图只认导入稿 data/import/script_v2.json；runs/epNN/P4_epNN.md 是写作中间稿，不能再当出图来源"""


def import_json(run: str | None = None) -> Path:
    """多剧并行（docs/AUTOPILOT.md §0.1）：primary 仍是 data/import/script_v2.json；新 run 是 data/import/runs/<run>/script_v2.json"""
    if run is None:
        return IMPORT_JSON
    sys.path.insert(0, str(ROOT / "tools/autopilot"))
    import runs as RN
    return RN.import_path(run, ROOT)


def import_sha(run: str | None = None) -> str:
    import hashlib
    return hashlib.sha256(import_json(run).read_bytes()).hexdigest()


def load_import(run: str | None = None):
    """现行导入稿（与 build_jobs.load_specs(source="import")、ns_render.pipeline.load_script 同一口径）；run 给定且不是 primary 时读那部剧的导入稿"""
    p = import_json(run)
    if p == IMPORT_JSON:
        from ns_render import pipeline as P
        return P.load_script()
    from ns_schema.script import ScriptImport
    return ScriptImport.model_validate_json(p.read_text(encoding="utf-8"))


def import_episode(n: int, si=None):
    si = si or load_import()
    return si, next(e for e in si.episodes if e.number == n)


def load_episode(md: Path):
    """⤴ 旧来源（写作运行目录的 P4 稿）。11-01 起生产代码禁用：导入后镜数 80 → 93，P4 稿还是 10-31 的旧稿。
    只有写作 / 调研工具显式设环境变量 NS_ALLOW_P4_SOURCE=1 才能读（CLEANUP 隔离清单见 docs/rsi/p4_legacy_readers.md）"""
    if os.environ.get(ALLOW_P4_ENV) != "1":
        raise LegacySourceError(f"{md} 是写作中间稿，生产出图只认 data/import/script_v2.json（image_jobs.import_episode）；"
                                f"写作 / 调研工具确需读取请设 {ALLOW_P4_ENV}=1")
    si = import_script(md)
    return si, si.episodes[0]


def rebuild_first_frame_jobs(run_dir: Path, project: str | None = None, write: bool = True, out: Path | None = None,
                             run: str | None = None) -> dict:
    import plan_c_preview as PC
    run_dir = Path(run_dir)
    project = project or run_dir.name
    jp = run_dir / "assets" / "first_frame_jobs.json"
    data = json.loads(jp.read_text(encoding="utf-8")) if jp.exists() else {"jobs": []}     # 新 run 第一次：从空作业表开始
    bible = load_bible()
    # K-OPS-Q24（RSI 11-01，总调度授权）：作业集合 = 导入稿的镜头集合；提示词唯一来源 = 该 run 的导入稿
    si = load_import(run)
    sha = import_sha(run)
    g = si.globals
    sync = sync_job_set(data, si, run_dir)
    changed = []
    by_ep = {e.number: e for e in si.episodes}
    for j in data["jobs"]:
        if str(j.get("status", "")).startswith("stale:"):
            continue
        n = int(j["ep"])
        ep = by_ep[n]
        shot = next(s for s in ep.shots if s.id == j["shot"])
        j["prompt_source"] = {"file": import_json(run).relative_to(ROOT).as_posix(), "sha256": sha}
        refs = list(j.get("refs") or [])
        on = list(j.get("on_screen") or [])
        from ns_agent import asset_refs as AR
        for name in on:                                   # 在画的已定妆角色都挂身份脸（K-OPS-E29：唯一入口 asset_refs.face_of，按在画顺序补在后面）
            cid = FACE_CID.get(name)
            f = AR.face_of(project, cid) if cid else None
            if not f or not (ROOT / f).exists():
                continue
            if f not in refs:
                refs.append(f)
            st = str(j.get("status") or "")
            if st.startswith("blocked:") and name in st:   # 缺的身份参考补上了 → 解除阻塞
                j["status"] = "ready"
                j["unblocked_by"] = f"image_jobs.py 补入 {name} 脸部参考 {f}"
        for name in on:
            rel = SHEET_REFS.get(name)
            if rel:
                full = os.path.normpath(str((run_dir / rel).relative_to(ROOT))).replace("\\", "/")
                if full not in refs and (run_dir / rel).exists():
                    refs.append(full)
        prompt, c, sr, plan = frame_prompt_full(ep, shot, g, refs, project, bible)
        if plan is not None:                              # 资产参考锁定（REFLOCK）：参考图 = 槽位规划，旧的只挂脸 refs 作废
            from ns_agent import asset_refs as AR
            j["refs_before_reflock"] = j.get("refs_before_reflock") or refs
            refs = plan.files
            j["asset_refs"] = AR.record(sr, plan)
        j["refs"] = refs
        j["cast"] = cast_of(shot)
        from ns_agent import framing as FR
        size = FR.size_of(shot.img_prompt)
        j["framing_subject"] = FR.closeup_subject(shot.img_prompt, size)
        old = j.get("prompt")
        if plan is not None:
            # K-REN-134：资产项目的作业图一律由唯一出图路径构建（ns_render.unified_frame.build_graph，frame_v9）——
            # 存在这里只给只读消费者（story_runs / bakeoff / calibrate_q / server_deploy）看；真正出图入口都现场重建
            from ns_render import unified_frame as UF
            graph, _eff, prompt = UF.build_graph({"prompt": prompt, "refs": refs}, int(j["seed"]),
                                                 lambda p: "@upload:" + Path(p).resolve().relative_to(ROOT.resolve()).as_posix(),
                                                 f"imggen_s10/{j['shot']}")
            loras = [["krea2_film_texture_qwen21.safetensors", 0.5]]
            j["workflow"] = {"tool": "ns_render.unified_frame.build_graph", "preset": UF.preset_id()}
            j["built_by"] = "unified_frame"
        else:
            graph = with_loras(PC.graph(prompt, ["@upload:" + r for r in j.get("refs") or []], int(j["seed"]),
                                        f"imggen_s10/{j['shot']}"), c.image_loras)
            loras = [[f, float(w)] for f, w in c.image_loras]
        j.update(prompt=prompt, graph=graph, loras=loras, compiled_by="tools/pipeline/image_jobs.py → ns_agent.compiler.compile_shot",
                 compiler_inputs_sha=c.inputs_sha, framing_project=project, model="qwen_image_2.1")
        # 生成契约 preflight（I1–I10）：不过 → 作业标 blocked:contract，submit_jobs / IMGGEN 拒交
        from ns_agent.gen_contract import preflight as PF
        pf = PF.check(contract_request(j))
        j["preflight"] = {"ok": pf.ok, "blocking": [i.id for i in pf.blocking], "reasons": pf.reasons()}
        st = str(j.get("status") or "")
        if not pf.ok:
            j["status"] = "blocked:contract " + ",".join(i.id for i in pf.blocking)
        elif st.startswith("blocked:contract"):
            j["status"] = "ready"
        if old != prompt:
            j["prompt_changed"] = True
            j["prompt_before"] = old
            if Path(ROOT / j["out"]).exists():
                j["needs_rerender"] = True
            changed.append(j["shot"])
    data.update(rule="K-REN-103：出图提示词一律经 ns_agent.compiler（含 K-REN-101 景别取舍、触发词 / LoRA 规则）；"
                     "K-OPS-Q24：作业集合与提示词来源 = data/import/script_v2.json",
                rebuilt_at=time.strftime("%Y-%m-%d %H:%M:%S"), rebuilt_by="tools/pipeline/image_jobs.py",
                source={"file": "data/import/script_v2.json", "sha256": sha,
                        "shots": sum(len(e.shots) for e in si.episodes)}, sync=sync)
    if write:
        (Path(out) if out else jp).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"jobs": len(data["jobs"]), "changed": changed, "data": None if write else data, "sync": sync,
            "blocked_contract": [j["shot"] for j in data["jobs"] if str(j.get("status", "")).startswith("blocked:contract")],
            "needs_rerender": [j["shot"] for j in data["jobs"] if j.get("needs_rerender")]}



def _new_job(ep, shot, run_dir: Path, project: str, intimate: dict) -> dict:
    """导入稿里新增的镜：按现有约定建首帧作业骨架（seed = 20261100 + 集×100 + 镜号；out 同目录规则），提示词 / 图由 rebuild 填"""
    from ns_agent import framing as FR
    n, i = ep.number, shot.index
    seed = 20261100 + n * 100 + i
    rel_run = run_dir.resolve().relative_to(ROOT.resolve()).as_posix()
    return {"ep": n, "shot": shot.id, "id": shot.id, "size": FR.size_of(shot.img_prompt or ""),
            "on_screen": [c.name for c in (shot.cast or []) if c.presence == "在画"], "intimate_ep": bool(intimate.get(n, False)),
            "p4_blocking": 0, "status": "ready", "seed": seed, "local_only": True, "priority": f"F{n:02d}",
            "out": f"{rel_run}/images/frames/ep{n:02d}/{shot.id}_s{seed}.png", "refs": [], "framing_project": project,
            "created_by": "image_jobs.sync_job_set（导入稿新增镜，K-OPS-Q24）"}


def sync_job_set(data: dict, si, run_dir: Path) -> dict:
    """作业集合跟着导入稿的镜头集合增删：新增镜建作业；导入稿里没有的镜标 stale:removed_from_import（不删作业、不删文件）；
    已有作业的 size / on_screen 按导入稿刷新。→ {added, removed, kept}"""
    from ns_agent import framing as FR
    want = {s.id: (e, s) for e in si.episodes for s in e.shots}
    have = {j["shot"]: j for j in data.get("jobs") or []}
    intimate = {j["ep"]: j.get("intimate_ep") for j in have.values() if "intimate_ep" in j}
    project = next((j.get("framing_project") for j in have.values() if j.get("framing_project")), run_dir.name)
    added, removed = [], []
    for sid, (e, s) in want.items():
        if sid not in have:
            data["jobs"].append(_new_job(e, s, run_dir, project, intimate))
            added.append(sid)
        else:
            j = have[sid]
            j["size"] = FR.size_of(s.img_prompt or "")
            j["on_screen"] = [c.name for c in (s.cast or []) if c.presence == "在画"]
            if str(j.get("status", "")).startswith("stale:"):
                j["status"] = "ready"
    for sid, j in have.items():
        if sid not in want and not str(j.get("status", "")).startswith("stale:"):
            j["status"] = "stale:removed_from_import"
            j["stale_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            removed.append(sid)
    order = {sid: k for k, sid in enumerate(want)}
    data["jobs"].sort(key=lambda j: (j["shot"] not in order, order.get(j["shot"], 0)))
    return {"added": added, "removed": removed, "kept": len(want) - len(added)}


def _primary_run() -> str:
    """K-OPS-W17：默认 run 从 config/pipeline/runs.json 读（笔记本侧，缺文件回退 DEFAULT_PRIMARY）"""
    sys.path.insert(0, str(ROOT / "tools/autopilot"))
    import runs as RUNS
    return RUNS.primary_run()


def jobs_vs_import(run_dir: Path | None = None, run: str | None = None) -> dict:
    """G21 / K-OPS-Q24 检查：作业的镜头集合 = 导入稿镜头集合；每条现行作业的 prompt_source.sha256 = 现行 script_v2.json。
    → {ok, missing, extra, stale_sha, import_sha, shots}"""
    run_dir = Path(run_dir or ROOT / "data/pipeline/runs" / _primary_run())
    data = json.loads((run_dir / "assets" / "first_frame_jobs.json").read_text(encoding="utf-8"))
    si, sha = load_import(run), import_sha(run)
    want = {s.id for e in si.episodes for s in e.shots}
    live = {j["shot"]: j for j in data.get("jobs") or [] if not str(j.get("status", "")).startswith("stale:")}
    missing = sorted(want - set(live))
    extra = sorted(set(live) - want)
    stale_sha = sorted(sid for sid, j in live.items() if sid in want and (j.get("prompt_source") or {}).get("sha256") != sha)
    return {"ok": not (missing or extra or stale_sha), "missing": missing, "extra": extra, "stale_sha": stale_sha,
            "import_sha": sha, "shots": len(want)}

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    run = Path(args[0]) if args else ROOT / "data/pipeline/runs" / _primary_run()
    if "--check" in sys.argv:
        r = jobs_vs_import(run if run.is_absolute() else ROOT / run)
        print(json.dumps(r, ensure_ascii=False, indent=1))
        sys.exit(0 if r["ok"] else 1)
    r = rebuild_first_frame_jobs(run if run.is_absolute() else ROOT / run, write="--dry-run" not in sys.argv)
    r.pop("data", None)
    print(json.dumps(r, ensure_ascii=False, indent=1))
