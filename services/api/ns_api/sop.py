"""
SOP 阶段 S1–S5 与关口 G1–G5（docs/SOP_production.md「★ 阶段闸门与资源优先级」、docs/SOP_parameters.md）。

只读：读当前剧的 state_timeline.json、scenes.json（V1 = data/ 下，其它剧 = data/import/runs/<run>/；tools/build_state_timeline.py 生成）、data/looks/schedule.json、
gpu3 镜像（renders_gpu3/epXX/qa.json、continuity_sheet.jpg、epXX_final.mp4）、项目方关口记录 data/sop/owner_gates.json
（只由 tools/sop_owner.py 写）。**这里从不接受、确认或锁定任何关口**；项目方的关口只给出要跑的命令。

每镜的阶段 = 第一个出口闸门没过的阶段（上游没过就不进下游）。阻塞项：
    {code, stage, text, actor: owner|gpu3|laptop, cli?}
时间线字段只增不删：不认识的字段忽略，缺的字段按“未知/未通过”处理。
"""
import json
from pathlib import Path

STAGES = (("S1", "剧本"), ("S2", "资产"), ("S3", "画面"), ("S4", "视频"), ("S5", "成片"))
STAGE_IDS = tuple(s for s, _ in STAGES)
STAGE_LABEL = dict(STAGES)
GATES = (("G1", "风格定稿", "S1"), ("G2", "人物定妆", "S2"), ("G3", "剧本加强确认", "S1"),
         ("G4", "样片锁定", "S3"), ("G5", "成片验收", "S5"))
ACTOR_LABEL = {"owner": "项目方", "gpu3": "gpu3", "laptop": "笔记本"}
# ★2 GPU 优先级（高 → 低）；GPU 2 永不使用
GPU_PRIORITY = (("S1", "剧本 LLM（v3 改写）"), ("S2", "资产与 LoRA 训练"), ("S3", "首尾帧"), ("S4", "视频"),
                ("S5", "4K / 重型后期"))

OWNER_GATES = Path("data") / "sop" / "owner_gates.json"
QUOTE = "<项目方原话>"
CLI_S1_ACCEPT = f'uv run python tools/s1_gate.py --accept "{QUOTE}"'
CLI_S1_ERRORS = "uv run python tools/s1_gate.py --validator-errors <校验器错误数>"
CLI_TIMELINE = "uv run python tools/build_state_timeline.py"


def char_name(char: str) -> str:
    """角色 id → 中文名（lin_wan → 林晚）；不认识的原样"""
    try:
        from ns_schema.looks import CHARACTERS
        return CHARACTERS.get(char, char)
    except Exception:  # noqa: BLE001
        return char


def cli_look(eps: str, char: str) -> str:
    return f'uv run python -m ns_agent.looks confirm {eps} {char} "{QUOTE}"'


def cli_plate(scene_id: str) -> str:
    return f'uv run python tools/sop_owner.py plate {scene_id} "{QUOTE}"'


def cli_g4(ep: int) -> str:
    return f'uv run python tools/sop_owner.py g4 --episode {ep} "{QUOTE}"'


def cli_g5(ep: int) -> str:
    return f'uv run python tools/sop_owner.py g5 {ep} "{QUOTE}"'


def _read(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else default
    except (OSError, ValueError):
        return default


def _b(code: str, stage: str, text: str, actor: str, cli: str | None = None, **extra) -> dict:
    d = {"code": code, "stage": stage, "text": text, "actor": actor, "actor_label": ACTOR_LABEL.get(actor, actor)}
    if cli:
        d["cli"] = cli
    d.update(extra)
    return d


def ep_ranges(nums) -> str:
    """[1,2,3,5] → '1-3,5'（ns_agent.looks.parse_episode_list 认的格式）"""
    nums = sorted(set(int(n) for n in nums))
    out, i = [], 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        out.append(str(nums[i]) if i == j else f"{nums[i]}-{nums[j]}")
        i = j + 1
    return ",".join(out)


def _ver_num(v: str | None) -> int:
    try:
        return int(str(v or "").lower().lstrip("v").split(".")[0])
    except ValueError:
        return 0


# ---------------------------------------------------------------- 输入

class Inputs:
    """一次计算用到的文件（都可缺）"""

    def __init__(self, root: Path, gpu3_root: Path, orchestrator_dir: Path | None = None):
        self.root, self.gpu3_root = Path(root), Path(gpu3_root)
        self.orch = orchestrator_dir or self.root / "data" / "orchestrator"
        # V2CUT-O 11-03（L-126）：状态表 / 场景表按当前剧取（V2 = data/import/runs/<run>/），不读 V1 的 data/ 全局文件；
        # 当前剧的文件不存在 → timeline=None → 阻塞项 timeline_missing（报错，不回退）
        self.timeline_file, self.scenes_file = state_files(self.root)
        self.timeline = _read(self.timeline_file) if self.timeline_file else None
        self.scenes = _read(self.scenes_file) if self.scenes_file else None
        self.schedule = _read(self.root / "data" / "looks" / "schedule.json", {}) or {}
        self.owner_gates = _read(self.root / OWNER_GATES, {}) or {}
        self.tl_shots = {s.get("shot_id"): s for s in (self.timeline or {}).get("shots") or [] if isinstance(s, dict)}
        self.scene_by_id = {s.get("scene_id"): s for s in (self.scenes or {}).get("scenes") or [] if isinstance(s, dict)}
        self._qa: dict[int, dict | None] = {}
        self.stale = timeline_stale(self.root, self.timeline, self.scenes)
        self.timeline_foreign = timeline_foreign(self.stale)   # 状态表属于别的剧本：它的 scene_id / 底板不显示
        self.script = load_script(self.root)
        self.script_scenes = script_scene_ids(self.script)     # 本镜场景 id 的第一来源 = 当前剧剧本
        self.ep_versions = episode_versions(self.script)       # D-1：合并导入后各集剧本版本不同，S1 按集判
        self.source_drift = source_drift(self.root, self.timeline, self.script)
        self._asset_state: dict[tuple[str, int], dict] = {}
        self._look_states: dict[int, dict] | None = None

    def look_asset_state(self, char: str, name: str, ep: int) -> dict:
        """「确认造型」入口的前置：人物的身份脸 / 清单名 / 本集排期（tools/master/episode_ready.character_gaps，
        与开工前检查同一份代码）。不是资产包剧（V1 / 临时根）→ ready。→ {ready, wait: 给项目方看的一句话 | None, gaps}"""
        key = (char, ep)
        if key not in self._asset_state:
            self._asset_state[key] = look_asset_state(self.root, char, name, ep)
        return self._asset_state[key]

    def ep_dir(self, n: int) -> Path:
        return self.gpu3_root / f"ep{n:02d}"

    def qa(self, n: int) -> dict | None:
        if n not in self._qa:
            q = _read(self.ep_dir(n) / "qa.json")
            self._qa[n] = q if isinstance(q, dict) else None
        return self._qa[n]

    def final(self, n: int) -> str | None:
        for p in (self.ep_dir(n) / f"ep{n:02d}_final.mp4", self.root / "data" / "episodes" / f"ep{n:02d}.mp4"):
            if p.is_file():
                try:
                    return p.relative_to(self.root).as_posix()
                except ValueError:
                    return p.as_posix()
        return None

    def continuity_sheet(self, n: int) -> bool:
        return (self.ep_dir(n) / "continuity_sheet.jpg").is_file()


def state_files(root: Path) -> tuple[Path | None, Path | None]:
    """当前剧的 (状态表, 场景表) 路径（ns_agent.run_paths 唯一入口）；解析失败 → (None, None)，不回退 V1 的 data/ 全局文件"""
    try:
        from ns_agent import run_paths as _RPA
        return Path(_RPA.timeline_json(root)), Path(_RPA.scenes_json(root))
    except Exception:  # noqa: BLE001  # arch-ok: 解析不出当前剧 = 当作没有状态表（失败关闭）
        return None, None


def timeline_stale(root: Path, timeline: dict | None, scenes: dict | None) -> list[str]:
    """状态表记的输入哈希（剧本 script_sha、source_hashes、底板 sha）与磁盘不一致 → 变了的输入名"""
    if timeline is None:
        return []
    try:
        from ns_agent.state_timeline import stale_inputs
        return stale_inputs(root, timeline, scenes)
    except Exception as e:  # noqa: BLE001 — 算不出就当过期（不能拿旧表放行）
        return [f"check_failed:{type(e).__name__}"]


def script_file(root: Path) -> Path | None:
    """当前剧的导入稿（K-OPS-F24 / L-126：按 runs.json 取，V2 = data/import/runs/<run>/script_v2.json；
    没有 runs.json 的临时根 = data/import/script_v2.json）。解析到 V1 路径而当前剧不是 V1 → None（不回退）"""
    try:
        from ns_agent import run_paths as _RPA
        return Path(_RPA.script_json(root))
    except Exception:  # noqa: BLE001 — V1PathError 等：不回退 V1 文件
        return None


def load_script(root: Path):
    """当前剧导入稿 → ScriptImport；没有 / 读不了 → None（SOP 退回状态表的整份版本）。
    UIFIX-F 11-03：以前写死 data/import/script_v2.json（V1 的文件），V2 主剧时 SOP 拿的是 V1 剧本"""
    p = script_file(root)
    try:
        if p is not None and p.is_file():
            from ns_schema.script import ScriptImport
            return ScriptImport.model_validate_json(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pass
    return None


def script_scene_ids(script) -> dict[str, str | None]:
    """shot_id → 剧本 **场景** 的场景 id（旧剧本没写 = None）"""
    if script is None:
        return {}
    return {s.id: getattr(s, "scene_id", None) for e in script.episodes for s in e.shots}


def timeline_foreign(stale: list[str]) -> bool:
    """状态表是按另一份剧本生成的（script_sha 对不上，或者根本算不出）→ 它的 scene_id / 人物 / 底板都属于别的剧本，
    一律不拿来显示（UIFIX-F 11-03：V2 第 1 集分镜页出现 V1 的“办公室夜 / 深夜写字楼办公区角落”就是这么来的；L-126 完全切割）"""
    return any(x == "script" or x.startswith("check_failed:") for x in stale)


def shot_scene(inp: "Inputs", shot_id: str, tl: dict | None) -> tuple[str | None, str | None]:
    """本镜场景 id 的唯一取法：剧本 **场景**（当前剧）> 状态表（只有状态表属于当前剧本时）> None。→ (scene_id, 来源)"""
    # 只带部分字段的输入替身（测试 / 旧调用方）：没有剧本场景表 = 空；没有 timeline_foreign = 按“别的剧本”处理（失败关闭）
    sid = (getattr(inp, "script_scenes", None) or {}).get(shot_id)
    if sid:
        return sid, "script"
    if tl is not None and not getattr(inp, "timeline_foreign", True) and tl.get("scene_id"):
        return tl.get("scene_id"), "timeline"
    return None, None


def _episode_ready_module():
    """tools/master/episode_ready.py（开工前资产就绪检查）——只此一处加载，口径不复制"""
    import importlib.util
    p = Path(__file__).resolve().parents[3] / "tools" / "master" / "episode_ready.py"
    spec = importlib.util.spec_from_file_location("ns_tools_master_episode_ready", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _current_run(root: Path) -> str | None:
    """当前剧 run 名（资产包剧才有意义）；没有 runs.json / 旧剧（V1）→ None"""
    try:
        from ns_agent import run_paths as _RPA
        m = _RPA.runs_module(root)
        run = _RPA.current_run(root)
        if not run or m is None or m.is_legacy(run, root) or not m.asset_manifest(run, root):
            return None
        return run
    except Exception:  # noqa: BLE001
        return None


def asset_state_files(root: Path) -> list[Path]:
    """look_asset_state 读的文件（给 API 缓存签名用）：资产包清单 + 按集排期；不是资产包剧 → 空"""
    run = _current_run(root)
    if run is None:
        return []
    try:
        from ns_agent import run_paths as _RPA
        m = _RPA.runs_module(root)
        mp = m.asset_manifest(run, root)
    except Exception:  # noqa: BLE001
        mp = None
    return [p for p in (mp, root / "data" / "looks" / "hub_episode_looks.json") if p]


def look_asset_state(root: Path, char: str, name: str, ep: int) -> dict:
    """人物在本集的资产是否齐到可以确认造型（身份脸、清单 display_name、本集排期；
    UIFIX-F 11-03：口径 = tools/master/episode_ready.character_gaps，不另写）。
    不是资产包剧 → ready；算不出（模块缺 / 异常）→ 不就绪并写明原因（失败关闭，不装作就绪）"""
    run = _current_run(root)
    if run is None:
        return {"ready": True, "wait": None, "gaps": []}
    try:
        er = _episode_ready_module()
        cid = er.resolve_cid(run, char, name)
        gaps = er.character_gaps(run, cid, name, ep)
    except Exception as e:  # noqa: BLE001
        return {"ready": False, "wait": f"{name}的资产状态读不出来（{type(e).__name__}），先不确认造型", "gaps": []}
    if not gaps:
        return {"ready": True, "wait": None, "gaps": []}
    kinds = {g["kind"] for g in gaps}
    if "face" in kinds:
        wait = f"{name}的形象还在出候选，选定后再确认造型"
    elif "name" in kinds:
        wait = f"{name}还没登记进资产清单，登记后再确认造型"
    else:
        wait = f"{name}本集的造型排期还没做，排好后再确认造型"
    return {"ready": False, "wait": wait, "gaps": gaps}


def episode_versions(script) -> dict[int, str]:
    """集号 → 本集来源剧本版本（ns_agent.state_timeline.episode_version：源文件记的 version/episodes，后导入的优先）"""
    if script is None:
        return {}
    try:
        from ns_agent.state_timeline import episode_version
        return {e.number: episode_version(script, e.number) for e in script.episodes}
    except Exception:  # noqa: BLE001
        return {}


def source_drift(root: Path, timeline: dict | None, script=None) -> list[dict]:
    """QA4-01：剧本源文件导入后又改过 / 不见了 → [{path, imported_sha, current_sha}]。
    现算（ns_agent.state_timeline.source_drift，读 data/import/script_v2.json 的 sources）；算不出退回状态表记的
    source.changed_sources。只做提醒（warn），不拦镜头"""
    try:
        script = script if script is not None else load_script(root)
        if script is not None:
            from ns_agent.state_timeline import source_drift as _drift
            # 合并导入曾把同一源文件登记多次（旧条目是旧 sha）：同一路径只看最后（最新）一条，否则旧条目会误报
            last = {s.path.replace("\\", "/").lower(): s for s in script.sources}
            return _drift(root, script.model_copy(update={"sources": list(last.values())}))
    except Exception:  # noqa: BLE001 — 提醒算不出不影响 SOP 状态
        pass
    d = ((timeline or {}).get("source") or {}).get("changed_sources")
    return [x for x in d if isinstance(x, dict)] if isinstance(d, list) else []


SOURCE_DRIFT_TEXT = "剧本源文件导入后又改过，需重新导入"


def source_drift_warning(inp: "Inputs") -> dict | None:
    if not getattr(inp, "source_drift", None):
        return None
    paths = [str(x.get("path") or "") for x in inp.source_drift]
    gone = [str(x.get("path") or "") for x in inp.source_drift if x.get("current_sha") is None]
    text = SOURCE_DRIFT_TEXT + "：" + "、".join(paths) + (f"（其中找不到文件：{'、'.join(gone)}）" if gone else "")
    return {**_b("source_drift", "S1", text, "owner"), "level": "warn", "paths": paths,
            "changed_sources": list(inp.source_drift)}


def _stale_blocker(inp: "Inputs", stage: str) -> dict:
    names = "、".join(inp.stale[:6]) + ("…" if len(inp.stale) > 6 else "")
    return _b("timeline_stale", stage, f"状态表过期（{names} 已变）：重建前 S1/S2 一律按未通过处理", "laptop",
              CLI_TIMELINE, inputs=list(inp.stale))


def _sha(p: Path) -> str | None:
    try:
        from ns_agent.state_timeline import _sha_cached
        return _sha_cached(p)
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------- 项目级：S1 闸门、G1–G5

def s1_gate(inp: Inputs) -> dict:
    """provisional = !(剧本 ≥ v3 且 validator_errors == 0 且 g3_accepted)（docs/state_timeline.md §四）"""
    tl = inp.timeline
    if tl is None:
        return {"passed": False, "known": False, "script": None,
                "blockers": [_b("timeline_missing", "S1", "还没有本剧的状态表（state_timeline.json）", "laptop", CLI_TIMELINE)]}
    g = tl.get("s1_gate") or {}
    ver = (tl.get("source") or {}).get("script")
    errs, g3 = g.get("validator_errors"), bool(g.get("g3_accepted"))
    blockers = []
    vers = getattr(inp, "ep_versions", None) or {}
    low = sorted(n for n, v in vers.items() if _ver_num(v) < 3)
    if vers and low and len(low) < len(vers):   # D-1：混合版本 → 只有这些集 S1 不过
        blockers.append(_b("script_partial_v3", "S1", f"部分集仍是 v2 等旧版（ep{ep_ranges(low)}）：这些集 S1 不过，"
                           "v3 的集按本集判断", "gpu3", episodes=low))
    elif (vers and low) or (not vers and _ver_num(ver) < 3):
        blockers.append(_b("script_not_v3", "S1", f"剧本还是 {ver or '未知版本'}，S1 要求 v3 加强版（v3 改写在 gpu3 LLM 上跑）", "gpu3"))
    if errs is None:
        blockers.append(_b("validator_unrecorded", "S1", "校验器错误数没有记录（须为 0）", "laptop", CLI_S1_ERRORS))
    elif errs != 0:
        blockers.append(_b("validator_errors", "S1", f"校验器报 {errs} 个错误（须为 0，由剧本写入者修）", "gpu3"))
    if not g3:
        blockers.append(_b("g3_not_accepted", "S1", "G3 剧本加强未经项目方采纳（系统从不自动采纳）", "owner", CLI_S1_ACCEPT))
    prov = tl.get("provisional")
    passed = (not prov) if isinstance(prov, bool) else not blockers
    if inp.stale:             # 剧本/造型/底板变了但状态表没重建：表里的 S1 结论不可信
        return {"passed": False, "known": True, "stale": True, "script": ver, "validator_errors": errs,
                "g3_accepted": False, "g3_ref": None, "checked_at": g.get("checked_at"),
                "blockers": [_stale_blocker(inp, "S1")] + [b for b in blockers if b["code"] != "g3_not_accepted"]
                + [_b("g3_not_accepted", "S1", "G3 剧本加强未经项目方采纳（状态表过期，先重建再看）", "owner",
                      CLI_S1_ACCEPT)]}
    if passed:
        blockers = []
    elif not blockers:        # 时间线说临时，但看不出原因（新字段）→ 照实说
        blockers.append(_b("s1_provisional", "S1", "状态表标记 provisional（S1 闸门未过）", "laptop", "uv run python tools/s1_gate.py"))
    return {"passed": passed, "known": True, "script": ver, "validator_errors": errs, "g3_accepted": g3,
            "g3_ref": g.get("g3_ref") or None, "checked_at": g.get("checked_at"), "blockers": blockers}


EP_VERSION_CODES = ("script_not_v3", "script_partial_v3", "s1_provisional")


def episode_s1_blockers(inp: Inputs, s1: dict, ep: int) -> list[dict]:
    """D-1：本集的 S1 阻塞。剧本版本按本集来源判（episode_version）；校验器 / G3 / 状态表过期仍是项目级。
    不知道各集版本（没有 script_v2.json）→ 原样用项目级结论"""
    vers = getattr(inp, "ep_versions", None) or {}
    if ep not in vers:
        return [dict(b) for b in s1["blockers"]]
    out = [dict(b) for b in s1["blockers"] if b["code"] not in EP_VERSION_CODES]
    v = vers[ep]
    if _ver_num(v) < 3:
        out.insert(0, _b("script_not_v3", "S1", f"第 {ep} 集剧本还是 {v or '未知版本'}，S1 要求 v3 加强版"
                                                 "（v3 改写在 gpu3 LLM 上跑）", "gpu3", episode=ep))
    return out


def _owner_note(rec: dict) -> str:
    return str(rec.get("ref") or rec.get("note") or rec.get("owner_quote") or "").strip()


def g4_record(inp: Inputs) -> dict | None:
    rec = inp.owner_gates.get("g4")
    if isinstance(rec, dict):     # owner_gates 里有 g4 记录就以它为准（撤销了就是没锁，不再回退到看板记录）
        if rec.get("locked_at") and not rec.get("revoked_at") and _owner_note(rec):
            return {**rec, "source": OWNER_GATES.as_posix()}
        return None
    pl = _read(inp.orch / "PIPELINE_LOCKED.json")      # ns_orch 看板 G4 approve 写的记录（新项目）：须带项目方原话
    if isinstance(pl, dict) and pl.get("locked_at") and not pl.get("revoked_at") and _owner_note(pl):
        return {**pl, "ref": _owner_note(pl), "source": "data/orchestrator/PIPELINE_LOCKED.json"}
    return None


def g5_record(inp: Inputs, n: int) -> dict | None:
    rec = (inp.owner_gates.get("g5") or {}).get(str(n))
    if isinstance(rec, dict) and rec.get("decided_at") and _owner_note(rec):
        if rec.get("decision") == "publish":      # 发布绑定验收时的成片 sha：成片换了 → 验收作废
            final = inp.final(n)
            cur = _sha(inp.root / final) if final else None
            if not rec.get("final_sha256") or rec.get("final_sha256") != cur:
                return None
        return {**rec, "source": OWNER_GATES.as_posix()}
    st = _read(inp.orch / "state.json") or {}
    acc = (((st.get("episodes") or {}).get(str(n)) or {}).get("steps") or {}).get("accept") or {}
    if acc.get("status") == "done" and acc.get("decision", "publish") == "publish" and _owner_note(acc):
        return {"decision": "publish", "decided_at": acc.get("decided_at"), "by": acc.get("decided_by"),
                "ref": _owner_note(acc), "source": "data/orchestrator/state.json"}
    return None


def _present_characters(inp: Inputs) -> list[str]:
    seen: list[str] = []
    for s in inp.tl_shots.values():
        for c, v in (s.get("characters") or {}).items():
            if isinstance(v, dict) and v.get("present") and c not in seen:
                seen.append(c)
    return seen


def _plan_confirmed(p) -> bool:
    return isinstance(p, dict) and bool(p.get("owner_confirmed_at")) and bool(str(p.get("owner_confirmed_ref") or "").strip())


def episode_unconfirmed(inp: Inputs) -> dict[int, list[str]]:
    """集 → 造型未经项目方确认的角色。本集须确认的角色 = 本集状态表镜头里入镜的角色 + 有集计划的角色；
    没有计划 = 未确认；确认须有原话（内容哈希由状态表核，见 ns_agent.looks.Resolver.episode_confirmed）"""
    als = asset_look_states(inp)
    if als is not None:       # V2CUT-O：资产包剧按集确认记录（look_confirm.json，绑定造型快照）
        return {n: [p["display_name"] for p in st["people"]] or ["<角色>"] for n, st in als.items() if not st["confirmed"]}   # 给人看：人名不给 id
    plans = inp.schedule.get("episodes") or {}
    present: dict[int, list[str]] = {}
    for s in inp.tl_shots.values():
        try:
            ep = int(s.get("episode"))
        except (TypeError, ValueError):
            continue
        lst = present.setdefault(ep, [])
        lst += [c for c, v in (s.get("characters") or {}).items() if isinstance(v, dict) and v.get("present")
                and c not in lst]
    # DATAALIGN（K-UI-D01）：登记了资产的剧（series10），须确认的人物 = 剧本 **人物** 行在画 / 局部的人（与出图、
    # /api/looks/episodes/{n} 同口径）；旧口径（状态表关键词入镜 + 集计划）会多出 / 漏掉人（ep05：多顾沉、漏阿岚）
    ec = None
    try:
        if inp.root.resolve() == Path(__file__).resolve().parents[3].resolve():
            from ns_api.shot_cast import episode_cast_ids
            ec = episode_cast_ids()
    except Exception:  # noqa: BLE001
        ec = None
    out: dict[int, list[str]] = {}
    for k, e in ((inp.timeline or {}).get("episodes") or {}).items():
        if not isinstance(e, dict):
            continue
        n = int(k)
        ep_plans = plans.get(str(k)) or {}
        required = list(dict.fromkeys(present.get(n, []) + list(e.get("characters") or []) + list(ep_plans)))
        if ec is not None and n in ec:
            required = list(ec[n])
        chars = [c for c in required if not _plan_confirmed(ep_plans.get(c))]
        chars += [c for c in e.get("unconfirmed_characters") or [] if c not in chars
                  and (ec is None or n not in ec or c in required)]   # 状态表的旧口径人物不在剧本人物行里 → 不算
        if not e.get("look_confirmed") and not chars:
            chars = ["<角色>"]
        if chars:
            out[n] = chars
    return out


def asset_look_states(inp: Inputs) -> dict[int, dict] | None:
    """V2CUT-O 11-03：资产包剧（V2 等）的“确认造型”按集算（ns_api.look_confirm.episode_state，和通知中心同一份代码）：
    每集一条，带全部人物的 display_name / 本集造型 / 缩略图。不是资产包剧（V1 / 临时根）→ None（保持逐角色旧口径）"""
    root = getattr(inp, "root", None)
    if root is None or getattr(inp, "script", None) is None or _current_run(root) is None             or not (Path(root) / "config" / "pipeline" / "runs.json").is_file():   # 没有登记表的临时根：保持逐角色旧口径
        return None
    if getattr(inp, "_look_states", None) is None:
        try:
            from ns_api import look_confirm as LC
            run = _current_run(inp.root)
            inp._look_states = {e.number: LC.episode_state(inp.root, run, e.number) for e in inp.script.episodes}
        except Exception as e:  # noqa: BLE001  算不出 = 每集都不就绪，原因写明（失败关闭）
            inp._look_states = {x.number: {"episode": x.number, "people": [], "confirmed": False, "ready": False,
                                           "waits": [f"本集造型读不出来（{type(e).__name__}），先不确认"], "pick_id": None}
                                for x in inp.script.episodes}
    return inp._look_states


def unconfirmed_looks(inp: Inputs) -> dict[str, list[int]]:
    """角色 → 造型未经项目方确认的集（「待你决定」逐角色列出）"""
    out: dict[str, list[int]] = {}
    for n, chars in sorted(episode_unconfirmed(inp).items()):
        for c in chars:
            out.setdefault(c, []).append(n)
    return out


def gates(inp: Inputs, s1: dict, first_ep: int | None, ep_states: dict[int, dict]) -> list[dict]:
    out = []
    # G1 风格定稿：SOP 没有单独记录文件，只看视觉圣经在不在（不拦镜头）
    vb = inp.root / "config" / "visual_bible.toml"
    out.append({"id": "G1", "label": "风格定稿", "stage": "S1", "status": "info" if vb.is_file() else "blocked",
                "detail": "config/visual_bible.toml 存在（SOP 没有单独的 G1 记录；项目方画面风格见 SOP_parameters 固定约束）"
                if vb.is_file() else "没有 config/visual_bible.toml",
                "blockers": [] if vb.is_file() else [_b("g1_no_bible", "S1", "缺视觉圣经 config/visual_bible.toml", "laptop")]})
    # G2 人物定妆：入镜角色的写实母版
    chars = _present_characters(inp)
    missing = [c for c in chars if not (inp.root / "assets" / "characters" / c / "plates" / "master.png").is_file()]
    have = [c for c in chars if c not in missing]
    out.append({"id": "G2", "label": "人物定妆", "stage": "S2",
                "status": "passed" if chars and not missing else ("warn" if have else "blocked"),
                "detail": (f"已有母版：{'、'.join(have) or '无'}" + (f"；没有母版：{'、'.join(missing)}（时间线 S2 目前不按此拦镜头）" if missing else "")),
                "blockers": [_b(f"g2_master:{c}", "S2", f"{c} 没有身份母版 plates/master.png：先出 3 档写实候选，再由项目方选定",
                                "gpu3") for c in missing]})
    # G3 = S1 的采纳部分
    out.append({"id": "G3", "label": "剧本加强确认", "stage": "S1",
                "status": "passed" if s1.get("g3_accepted") else "blocked",
                "detail": f"已采纳：{s1.get('g3_ref')}" if s1.get("g3_accepted") else "项目方还没采纳 v3 加强版",
                "blockers": [b for b in s1["blockers"] if b["code"] in ("g3_not_accepted", "timeline_stale")]})
    # G4 样片锁定：首集 S4 全过后由项目方锁
    rec = g4_record(inp)
    first = ep_states.get(first_ep) if first_ep is not None else None
    if rec:
        g4 = {"status": "passed", "detail": f"{rec.get('locked_at')} 锁定（{rec.get('ref') or rec.get('locked_by') or ''}；{rec['source']}）",
              "blockers": []}
    else:
        ready = bool(first and first.get("s4_done"))
        g4 = {"status": "blocked" if ready else "pending",
              "detail": (f"第 {first_ep} 集视频已全部过 QA，等项目方看样片锁定" if ready else
                         f"等第 {first_ep} 集每镜视频过 QA（qa.json 每镜 pass）后，由项目方看样片锁定"),
              "blockers": [_b("g4_not_locked", "S3", f"G4：第 {first_ep} 集样片未锁定", "owner",
                              cli_g4(first_ep) if first_ep is not None else None, actionable=ready)]}
    out.append({"id": "G4", "label": "样片锁定", "stage": "S3", "sample_episode": first_ep, "record": rec, **g4})
    # G5 成片验收：每集
    done = sorted(n for n, e in ep_states.items() if (e.get("g5") or {}).get("decision") == "publish")
    waiting = sorted(n for n, e in ep_states.items() if e.get("final") and n not in done)   # 含返工的集
    out.append({"id": "G5", "label": "成片验收", "stage": "S5",
                "status": "passed" if ep_states and len(done) == len(ep_states) else ("blocked" if waiting else "pending"),
                "detail": f"已验收 {len(done)}/{len(ep_states)} 集" + (f"；待验收：ep{ep_ranges(waiting)}" if waiting else ""),
                "blockers": [_b("g5_pending", "S5", f"G5：ep{n:02d} 成片待项目方验收", "owner", cli_g5(n), episode=n)
                             for n in waiting]})
    return out


# ---------------------------------------------------------------- 每镜

S2_ACTORS = {"lora": "gpu3", "missing_ref": "laptop", "ref_unresolved": "laptop"}


def s2_blockers(inp: Inputs, tl: dict | None, ep: int) -> list[dict]:
    if inp.timeline is None:
        return [_b("timeline_missing", "S2", "还没有本剧的状态表（state_timeline.json）", "laptop", CLI_TIMELINE)]
    if inp.stale:
        return [_stale_blocker(inp, "S2")] + _s2_from_timeline(inp, tl, ep)
    return _s2_from_timeline(inp, tl, ep)


def _s2_from_timeline(inp: Inputs, tl: dict | None, ep: int) -> list[dict]:
    if tl is None:
        return [_b("timeline_no_shot", "S2", "状态表里没有这一镜（剧本改过？重建状态表）", "laptop", CLI_TIMELINE)]
    raw = tl.get("s2_blockers")
    if raw is None:                       # 旧格式：没有 s2 字段 → 按已有字段推
        raw = [f"lora:{l.get('trigger')}:{l.get('registry_status')}" for l in tl.get("required_loras") or []
               if l.get("kind", "image") == "image" and l.get("registry_status") != "accepted"]
        sc = inp.scene_by_id.get(tl.get("scene_id")) or {}
        if sc.get("plate_status") != "owner_confirmed":
            raw.append(f"plate:{tl.get('scene_id')}:{sc.get('plate_status') or 'missing'}")
        if not (((inp.timeline.get("episodes") or {}).get(str(ep)) or {}).get("look_confirmed")):
            raw.append(f"look_unconfirmed:ep{ep:02d}")
    out = []
    ep_unconf = episode_unconfirmed(inp).get(ep)
    raw = list(raw)
    if asset_look_states(inp) is not None:   # V2CUT-O：资产包剧“造型确认”只认 look_confirm 记录（状态表按旧造型库算的不作数）
        raw = [c for c in raw if not str(c).startswith("look_unconfirmed")]
    if ep_unconf and not any(str(c).startswith("look_unconfirmed") for c in raw):
        raw.append(f"look_unconfirmed:ep{ep:02d}")       # 状态表说已确认，但计划缺原话 / 缺角色
    for code in raw:
        code = str(code)
        kind, _, rest = code.partition(":")
        if kind == "s1_gate_not_passed":
            continue                       # S1 已单独列出（上游）
        if kind == "lora":
            trig, _, status = rest.rpartition(":")
            text = (f"LoRA {trig} 训练中/待验收（协调看过样图后登记 accepted）" if status == "training"
                    else f"LoRA {trig} 还没有（要训练并登记进 LORA_REGISTRY）")
            out.append(_b(code, "S2", text, "gpu3", trigger=trig))
        elif kind == "plate":
            scene, _, status = rest.rpartition(":")
            if status == "candidate":
                out.append(_b(code, "S2", f"场景底板 {scene} 待项目方确认", "owner", cli_plate(scene), scene_id=scene))
            else:
                out.append(_b(code, "S2", f"场景底板 {scene} 还没生成（S1 过了才能出：临时分组不得用于底板）", "gpu3",
                              scene_id=scene))
        elif kind == "look_unconfirmed":
            chars = ep_unconf or ["<角色>"]
            out.append(_b(code, "S2", f"第 {ep} 集造型未经项目方确认（{'、'.join(chars)}）", "owner",
                          " ; ".join(cli_look(str(ep), c) for c in chars)))
        elif kind == "missing_ref":
            out.append(_b(code, "S2", f"单品参考图文件不存在：{rest}", "laptop"))
        elif kind == "ref_unresolved":
            item, _, rid = rest.rpartition(":")
            out.append(_b(code, "S2", f"单品 {item} 的参考 {rid} 只有注册表 id、没有图片文件", "laptop"))
        else:
            out.append(_b(code, "S2", f"S2 未就绪：{code}", S2_ACTORS.get(kind, "laptop")))
    if not out and raw == [] and tl.get("s2_ready") is False:
        out.append(_b("s2_not_ready", "S2", "状态表标记 s2_ready=false（原因未列出）", "laptop", CLI_TIMELINE))
    return out


S1_ITEMS = ("img", "motion", "duration", "sound", "music_cue", "bgm")
S3_ITEMS = ("first", "last", "chain", "continuity")


def shot_status(inp: Inputs, *, shot_id: str, ep: int, index: int, s1: dict, readiness: dict | None,
                frames_owner: str, has_first: bool, has_last: bool, has_video: bool, gpu3_status: str | None,
                first_ep: int | None, g4_passed: bool, h3_failed: list[str] | None = None,
                h3_source: str | None = None) -> dict:
    items = {i["key"]: i for i in (readiness or {}).get("items") or []}
    stages: dict[str, list[dict]] = {k: [] for k in STAGE_IDS}
    # S1：项目闸门 + 本镜剧本要素（时长必须剧本写明）
    stages["S1"] += episode_s1_blockers(inp, s1, ep)
    for k in S1_ITEMS:
        it = items.get(k)
        if it and (not it["ok"] or (k == "duration" and it.get("source") != "script")):
            stages["S1"].append(_b(f"element:{k}", "S1", f"{it['label']}：{it['reason']}", "gpu3"))
    # S2
    tl = inp.tl_shots.get(shot_id)
    stages["S2"] = s2_blockers(inp, tl, ep)
    scene_id, scene_src = shot_scene(inp, shot_id, tl)   # 剧本 > 属于当前剧本的状态表 > 无（不拿别的剧本的场景）
    # S3：首尾帧同链、帧闸门、衔接；非首集还要 G4
    if readiness is not None:
        for k in S3_ITEMS:
            it = items.get(k)
            if it and not it["ok"]:
                stages["S3"].append(_b(f"frame:{k}", "S3", f"{it['label']}：{it['reason']}", frames_owner))
        for r in readiness.get("gpu3_blocked_reasons") or []:
            stages["S3"].append(_b("gpu3_blocked", "S3", f"gpu3 帧闸门：{r}", "gpu3"))
    else:
        if not has_first:
            stages["S3"].append(_b("frame:first", "S3", "没有首帧", frames_owner))
        if not has_last:
            stages["S3"].append(_b("frame:last", "S3", "没有尾帧", frames_owner))
        if str(gpu3_status or "").lower() == "blocked":
            stages["S3"].append(_b("gpu3_blocked", "S3", "gpu3 status.json status=blocked", "gpu3"))
    if first_ep is not None and ep != first_ep and not g4_passed:
        stages["S3"].append(_b("g4_not_locked", "S3", f"等 G4：第 {first_ep} 集样片锁定后才放量", "owner",
                               cli_g4(first_ep)))
    # S4：H3 提示词必须通过 §9A 机检（h3_failed = 未通过且无项目方原话豁免的 block 规则；None = 没检查）
    if h3_failed:
        src = {"gpu3": "gpu3 最终提示词", "script": "剧本 **H3提示词**", "laptop": "笔记本草稿（剧本缺 H3提示词）"}.get(
            h3_source or "", "提示词")
        stages["S4"].append(_b("h3_lint", "S4", f"H3 提示词未通过 §9A（{src}）：{'、'.join(h3_failed)}", "gpu3",
                               rule_ids=list(h3_failed)))
    # S4：视频 + qa.json 本镜 pass
    if not has_video:
        stages["S4"].append(_b("video_missing", "S4", "还没出视频（只出通过就绪闸门的镜头）", frames_owner))
    qa = inp.qa(ep)
    q = ((qa or {}).get("shots") or {}).get(f"S{index}") if qa else None
    if not isinstance(q, dict) or q.get("verdict") != "pass":
        why = ("本集没有 qa.json" if qa is None else "qa.json 里没有这一镜" if not isinstance(q, dict)
               else f"qa.json verdict={q.get('verdict')!r}")
        stages["S4"].append(_b("qa_not_pass", "S4", f"视频 QC 未通过：{why}", "gpu3"))
    # S4 提示（R-C4，总调度 2026-10-30）：视频 LoRA 未验收只提醒，不进 blockers、不改 passed
    s4_warn = [{"code": "video_lora_unaccepted", "stage": "S4", "trigger": l.get("trigger"), "rule_ids": ["R-C4"],
                "text": f"视频 LoRA {l.get('trigger')} 未验收：视频照常出，accepted 后更好"}
               for l in (tl or {}).get("required_loras") or []
               if l.get("kind") == "video" and l.get("registry_status") != "accepted"]
    stage = next((k for k in STAGE_IDS[:4] if stages[k]), None)
    ahead = []
    if stage in ("S1", "S2") and (has_first or has_last):
        ahead.append(f"已有首尾帧，但 {stage} 没过：按 SOP 这些帧不算数，上游过后按 inputs_sha 判断是否重出")
    if stage in ("S1", "S2", "S3") and has_video:
        ahead.append(f"已有视频，但 {stage} 没过：不得进成片")
    return {"id": shot_id, "episode": ep, "index": index, "stage": stage or "S5",
            "stage_label": STAGE_LABEL[stage or "S5"],
            "blockers": stages[stage] if stage else [],
            "stages": {k: {"passed": not v, "blockers": v, **({"warnings": s4_warn} if k == "S4" else {})}
                       for k, v in stages.items() if k != "S5"},
            "frames_owner": frames_owner, "ahead_of_gate": ahead,
            "s2_ready": (tl or {}).get("s2_ready"), "scene_id": scene_id, "scene_id_source": scene_src,
            "required_loras": (tl or {}).get("required_loras") or []}


# ---------------------------------------------------------------- 集 / 项目

def _min_stage(stages) -> str:
    order = {k: i for i, k in enumerate(STAGE_IDS + ("done",))}
    return min(stages, key=lambda s: order.get(s, 0), default="S1")


def episode_status(inp: Inputs, n: int, shots: list[dict], g4: dict | None) -> dict:
    """shots = shot_status() 结果；补本集级 S3（衔接表）、S5（成片、G5）"""
    s4_done = bool(shots) and all(s["stage"] == "S5" for s in shots)
    final = inp.final(n)
    g5 = g5_record(inp, n)
    ep_blockers: list[dict] = []
    if not inp.continuity_sheet(n):
        ep_blockers.append(_b("continuity_sheet_missing", "S3", "本集衔接表 continuity_sheet.jpg 还没生成", "gpu3"))
    s5: list[dict] = []
    if s4_done:
        if not final:
            s5.append(_b("final_missing", "S5", "声音、装配、4K 还没完成：没有 _final 成片", "gpu3"))
        elif not g5:
            s5.append(_b("g5_pending", "S5", f"G5：ep{n:02d} 成片待项目方验收", "owner", cli_g5(n), episode=n))
        elif g5.get("decision") == "rework":
            s5.append(_b("g5_rework", "S5", f"G5 返工：{g5.get('ref') or ''}", "gpu3"))
    elif final:
        ep_blockers.append(_b("final_before_qa", "S5", "已有 _final，但不是每镜都过了 S4：应为 _PREVIEW_未完成", "gpu3"))
    shot_stage = _min_stage([s["stage"] for s in shots]) if shots else "S1"
    stage = _min_stage([shot_stage] + [b["stage"] for b in ep_blockers])   # 本集级阻塞（衔接表等）也拦住本集
    if stage == "S5" and not s5 and not ep_blockers:
        stage = "done"
    counts = {k: sum(1 for s in shots if s["stage"] == k) for k in STAGE_IDS}
    # 本集阻塞汇总（同 code 合并，记镜数）
    agg: dict[tuple, dict] = {}
    for s in shots:
        for b in s["blockers"]:
            key = (b["stage"], b["code"])
            if key not in agg:
                agg[key] = {**b, "shots": []}
            agg[key]["shots"].append(s["id"])
    summary = sorted(agg.values(), key=lambda b: (STAGE_IDS.index(b["stage"]), -len(b["shots"])))
    return {"episode": n, "stage": stage, "stage_label": STAGE_LABEL.get(stage, "完成"),
            "counts": counts, "total": len(shots), "s4_done": s4_done, "final": final, "g5": g5,
            "episode_blockers": ep_blockers + s5, "blocker_summary": summary + s5,
            "g4_required": g4 is None}


def owner_actions(inp: Inputs, s1: dict, gate_list: list[dict], ep_states: dict[int, dict]) -> list[dict]:
    """「待你决定」：只列项目方本人要拍板的事，每条给命令。actionable=false = 上游还没到，先别做"""
    acts = []
    for w in s1.get("warnings") or []:
        if w.get("code") == "source_drift":     # QA4-01：重新导入只能由项目方在画布「剧本导入」里点
            acts.append({"gate": "source_drift", "stage": "S1", "level": "warn", "title": SOURCE_DRIFT_TEXT,
                         "why": w["text"] + "（提醒，不拦镜头；在画布「剧本导入」确认导入）", "paths": w["paths"],
                         "cli": None, "actionable": True, "waiting_on": []})
    if not s1.get("g3_accepted") and s1.get("known"):
        upstream = [b["text"] for b in s1["blockers"] if b["code"] in ("timeline_stale", "script_not_v3", "validator_errors",
                                                                         "validator_unrecorded")]
        acts.append({"gate": "G3", "stage": "S1", "title": "采纳 v3 剧本加强",
                     "why": "S1 出口闸门：没有项目方采纳，全部镜头停在 S1",
                     "cli": CLI_S1_ACCEPT, "actionable": not upstream, "waiting_on": upstream})
    als = asset_look_states(inp)
    for n, st in sorted((als or {}).items()):
        if st["confirmed"]:
            continue
        # V2CUT-O 11-03：资产包剧每集一条，全部人物 + 本集造型 + 缩略图；和通知中心（/api/owner/inbox 的 pick:look）同一份记录，
        # 哪边确认了两边同时消失。标题 / 文案只用人名，不出现角色 id
        names = "、".join(p["display_name"] for p in st["people"]) or "本集人物"
        wait = st["waits"][0] if st["waits"] else None
        acts.append({"gate": "look", "stage": "S2", "title": f"确认第 {n} 集造型：{names}",
                     "character_name": names, "character": None, "episode": n, "episodes": [n], "per_episode": True,
                     "people": st["people"], "pick_id": st["pick_id"],
                     "why": f"S2：第 {n} 集的造型没有项目方确认，镜头不进入第 3 阶段（出图）。一次确认本集全部人物", "cli": None,
                     "asset_ready": bool(st["ready"]), "asset_wait": wait,
                     "actionable": bool(st["ready"]), "waiting_on": [] if st["ready"] else list(st["waits"])})
    for char, eps in sorted(unconfirmed_looks(inp).items()) if als is None else []:
        name = char_name(char)
        # UIFIX-F 11-03：造型确认属于资产阶段——身份脸还没选定 / 清单没登记 / 本集没排期的人，入口不开（asset_ready=False，
        # 网页改成一句“X的形象还在出候选，选定后再确认造型”），口径 = tools/master/episode_ready
        st = inp.look_asset_state(char, name, eps[0])
        acts.append({"gate": "look", "stage": "S2", "title": f"确认造型：{name}（{len(eps)} 集）",
                     "character_name": name,
                     "why": "S2：本集造型没有项目方确认，镜头不进入第 3 阶段（出图）。可只确认看过的集，例如先确认第 "
                            f"{eps[0]} 集", "episodes": eps, "character": char,
                     "cli": cli_look(str(eps[0]), char), "cli_all": cli_look(ep_ranges(eps), char),
                     "asset_ready": bool(st["ready"]), "asset_wait": st["wait"],
                     "actionable": bool(st["ready"]), "waiting_on": [] if st["ready"] else [st["wait"]]})
    for sc in (inp.scenes or {}).get("scenes") or []:
        if inp.timeline_foreign:
            break                          # scenes.json 属于别的剧本（V1）：它的底板不列进“待你决定”
        if sc.get("plate_status") == "candidate":
            acts.append({"gate": "plate", "stage": "S2", "title": f"确认场景底板 {sc.get('scene_id')}（{sc.get('place') or ''}）",
                         "why": f"第 3 阶段（出图）只能用项目方确认的底板；用到它的镜头 {len(sc.get('shots') or [])} 个",
                         "plate": sc.get("plate"), "scene_id": sc["scene_id"], "cli": cli_plate(sc["scene_id"]),
                         "actionable": not (inp.scenes or {}).get("provisional", True) and not inp.stale,
                         "waiting_on": (["scenes.json 仍是临时分组（S1 未过）"] if (inp.scenes or {}).get("provisional", True) else [])
                         + (["状态表过期，先重建"] if inp.stale else [])})
    g4 = next(g for g in gate_list if g["id"] == "G4")
    if g4["status"] != "passed":
        b = g4["blockers"][0]
        acts.append({"gate": "G4", "stage": "S3", "title": f"锁定第 {g4['sample_episode']} 集样片的出图参数",
                     "episode": g4["sample_episode"],
                     "why": "第一集是样片：锁定它的出图参数之前，其余各集不放量出视频", "cli": b.get("cli"),
                     "actionable": bool(b.get("actionable")),
                     "waiting_on": [] if b.get("actionable") else [g4["detail"]]})
    for n, e in sorted(ep_states.items()):
        for b in e["episode_blockers"]:
            if b["code"] == "g5_pending":
                acts.append({"gate": "G5", "stage": "S5", "title": f"验收第 {n} 集成片", "why": e["final"] or "",
                             "episode": n,
                             "cli": b["cli"], "cli_rework": f'uv run python tools/sop_owner.py g5 {n} --rework "{QUOTE}"',
                             "actionable": True, "waiting_on": []})
    return acts


def gpu_priority(s1: dict, shots: list[dict], ep_states: dict[int, dict]) -> dict:
    """★2：高优先级有待办就不把卡给低优先级。这里只算“哪一级有 gpu3 待办”，分卡由调度器做"""
    work = {k: 0 for k, _ in GPU_PRIORITY}
    if any(b["code"] in ("script_not_v3", "script_partial_v3") for b in s1["blockers"]):
        work["S1"] = 1
    loras: dict[str, int] = {}
    plates: set[str] = set()
    for s in shots:
        for b in s["stages"]["S2"]["blockers"]:
            if b["actor"] == "gpu3" and b.get("trigger"):
                loras[b["trigger"]] = loras.get(b["trigger"], 0) + 1
            elif b["actor"] == "gpu3" and b.get("scene_id"):
                plates.add(b["scene_id"])
        if s["stage"] in ("S3", "S4") and any(b["actor"] == "gpu3" for b in s["blockers"]):
            work[s["stage"]] += 1
    work["S2"] = len(loras) + len(plates)
    work["S5"] = sum(1 for e in ep_states.values() if any(b["code"] == "final_missing" for b in e["episode_blockers"]))
    nxt = next((k for k, _ in GPU_PRIORITY if work[k]), None)
    return {"order": [{"stage": k, "label": lbl, "pending": work[k]} for k, lbl in GPU_PRIORITY],
            "next": nxt, "note": "GPU 2 永不使用；分卡只由调度器写（SOP ★2）",
            "lora_queue": [{"trigger": t, "shots": c} for t, c in sorted(loras.items(), key=lambda kv: -kv[1])],
            "plates_missing": sorted(plates)}


def evaluate(inp: Inputs, shot_rows: list[dict], *, project_owner: str) -> dict:
    """shot_rows：[{id, episode, index, readiness?, owner?, has_first, has_last, has_video, gpu3_status?}]（剧本顺序）"""
    s1 = s1_gate(inp)
    drift = source_drift_warning(inp)
    s1["warnings"] = [drift] if drift else []      # QA4-01：只提醒，不进 blockers、不改 passed
    eps = sorted({r["episode"] for r in shot_rows})
    first_ep = eps[0] if eps else None
    g4 = g4_record(inp)
    shots = [shot_status(inp, shot_id=r["id"], ep=r["episode"], index=r["index"], s1=s1,
                         readiness=r.get("readiness"), frames_owner=r.get("owner") or project_owner,
                         has_first=r.get("has_first", False), has_last=r.get("has_last", False),
                         has_video=r.get("has_video", False), gpu3_status=r.get("gpu3_status"),
                         first_ep=first_ep, g4_passed=g4 is not None,
                         h3_failed=r.get("h3_failed"), h3_source=r.get("h3_source")) for r in shot_rows]
    by_ep: dict[int, list[dict]] = {}
    for s in shots:
        by_ep.setdefault(s["episode"], []).append(s)
    ep_states = {n: episode_status(inp, n, by_ep.get(n, []), g4) for n in eps}
    gate_list = gates(inp, s1, first_ep, ep_states)
    stage = _min_stage([e["stage"] for e in ep_states.values()]) if ep_states else "S1"
    return {"s1": s1, "shots": shots, "episodes": ep_states, "gates": gate_list, "stage": stage,
            "owner_actions": owner_actions(inp, s1, gate_list, ep_states) + h3_override_actions(shot_rows),
            "gpu_priority": gpu_priority(s1, shots, ep_states)}


def h3_override_actions(shot_rows: list[dict]) -> list[dict]:
    """项目方改过的 H3 提示词，之后剧本 **H3提示词** 又更新了 → 请项目方在画布上重新确认（只列镜号）"""
    stale = [r for r in shot_rows if r.get("h3_override_stale")]
    if not stale:
        return []
    return [{"gate": "h3_override", "stage": "S4", "title": "剧本 H3 提示词已更新，请重新确认画布修改",
             "why": f"{len(stale)} 镜：{'、'.join(r['id'] for r in stale)}（在画布视频页「H3 提示词」面板重新保存或撤销）",
             "shots": [r["id"] for r in stale], "episodes": sorted({r["episode"] for r in stale}),
             "cli": None, "actionable": True, "waiting_on": []}]


def _sop_gate_module():
    """tools/master/sop_gate.py（唯一阶段模型，PRODMERGE-O 11-03 / PLAN_V2_MASTER v4 1-3）——只此一处加载"""
    import importlib.util
    p = Path(__file__).resolve().parents[3] / "tools" / "master" / "sop_gate.py"
    spec = importlib.util.spec_from_file_location("ns_tools_master_sop_gate", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sop_gate_view(root: Path) -> dict | None:
    """资产包剧（V2）：本页的阶段读 sop_gate.stage_view（九阶段），不再用本模块的 S1–S5 自判；V1 / 临时根 → None（旧口径）"""
    run = _current_run(root)
    if not run:
        return None
    try:
        return _sop_gate_module().stage_view(run, root)
    except Exception as e:  # noqa: BLE001  # arch-ok: 阶段模型读不出 = 页面显示原因，不回退成本模块自判
        return {"run": run, "error": f"{type(e).__name__}: {e}"[:200], "episodes": [], "stage": None, "legacy_stage": None}


def project_summary(slug: str, name: str, ev: dict, inp: Inputs) -> dict:
    shots = ev["shots"]
    tl = inp.timeline or {}
    out = _project_summary_v1(slug, name, ev, inp, shots, tl)
    sg = sop_gate_view(inp.root)
    if sg is None:
        return out
    st = sg.get("legacy_stage") or "S1"
    by_ep = {e["episode"]: e for e in sg.get("episodes") or []}
    out.update(stage=st, stage_label=STAGE_LABEL.get(st, "完成"), stage_source="sop_gate", sop_gate=sg, sop_stage=sg.get("stage"))
    for e in out["episodes"]:
        g = by_ep.get(e["episode"])
        if g:
            e.update(stage=g["legacy_stage"], stage_label=STAGE_LABEL.get(g["legacy_stage"], "完成"),
                     sop_stage=g["stage"], sop_why=g["why"], pending_owner=g["pending_owner"])
    return out


def _project_summary_v1(slug: str, name: str, ev: dict, inp: Inputs, shots: list, tl: dict) -> dict:
    return {
        "slug": slug, "name": name, "stage": ev["stage"], "stage_label": STAGE_LABEL.get(ev["stage"], "完成"),
        "stages": [{"id": k, "label": lbl, "shots_here": sum(1 for s in shots if s["stage"] == k),
                    "shots_past": sum(1 for s in shots if STAGE_IDS.index(s["stage"]) > i)}
                   for i, (k, lbl) in enumerate(STAGES)],
        "total_shots": len(shots),
        "s1": {k: v for k, v in ev["s1"].items()},
        "gates": ev["gates"],
        "episodes": [{"episode": n, "stage": e["stage"], "stage_label": e["stage_label"], "counts": e["counts"],
                      "total": e["total"], "top_blockers": [{k: b[k] for k in ("code", "stage", "text", "actor", "actor_label")}
                                                            | {"shots": len(b.get("shots") or [])}
                                                            for b in e["blocker_summary"][:3]]}
                     for n, e in sorted(ev["episodes"].items())],
        "owner_actions": ev["owner_actions"],
        "gpu_priority": ev["gpu_priority"],
        "timeline": {"present": inp.timeline is not None, "generated_at": tl.get("generated_at"),
                     "provisional": tl.get("provisional"), "bible_version": tl.get("bible_version")},
        "never_auto_accept": "系统从不替项目方接受任何关口：所有项目方关口只能由项目方本人跑上面的命令",
    }


# ---------------------------------------------------------------- W5 UIUX 11-03（L-146 / L-155）：顶部步骤条 + 总览进度矩阵的只读聚合
# GET /api/sop/stepbar?run=  → {run, title, episodes_total, steps:[{id,label,stages,done,doing,blocked,todo}],
#                               episodes:[{episode, stage, plain, cells:{step:{state, plain, owner, issues:[…]}}}],
#                               now:{focus, doing:[…], blocked:[…]}, issues_open, unplaced}
# 阶段判定只有一个来源：tools/master/sop_gate.py（经 ns_api.pipeline_status 折成六步，这里不另算）；
# 卡点只有一个来源：tools/master/report_issue.load() 的未关项（按集 + SOP 步骤号落到六步上；阻断项把“进行中”标成“卡住”）。
# 只读：不写任何文件。页面只显示 plain / owner（大白话），sop_gate 原文与卡点原文不上页面。
import importlib.util as _ilu  # noqa: E402
import re as _re  # noqa: E402
import time as _time  # noqa: E402

from fastapi import APIRouter as _APIRouter, HTTPException as _HTTPException  # noqa: E402

from ns_api import pipeline_status as _PSTAT  # noqa: E402

_REPORT_ISSUE_FILE = Path(__file__).resolve().parents[3] / "tools" / "master" / "report_issue.py"
_ri_mod = None
STEP_IDS = tuple(sid for sid, _l, _s in _PSTAT.STEPS)
STEP_STAGES = {sid: list(stages) for sid, _l, stages in _PSTAT.STEPS}           # 六步 ↔ sop_gate.STAGES（唯一来源）
_STAGE_TO_STEP = {st: sid for sid, _l, stages in _PSTAT.STEPS for st in stages}
# docs/master/PIPELINE_SOP_V2.md 的步骤号 → 六步（0–7 写作与导入 = ①剧本；8 资产就绪 = ②资产；9 金样首帧 = ④出图；10 尾帧→视频→成片 = ⑤视频）
_SOP_STEP_NO = {0: "script", 1: "script", 2: "script", 3: "script", 4: "script", 5: "script", 6: "script", 7: "script",
                8: "assets", 9: "frames", 10: "video"}
_STEP_WORDS = (("补丁", "script"), ("导入", "script"), ("delegate", "script"), ("P1", "script"), ("剧本", "script"),
               ("资产", "assets"), ("提示词", "board"), ("分镜", "board"), ("金样", "frames"), ("首帧", "frames"),
               ("尾帧", "frames"), ("出图", "frames"), ("视频", "video"), ("成片", "cut"), ("整集", "cut"))
# 每一步“在做的时候”默认是谁在做（只用于显示负责方；卡点有登记人时以登记人为准）
STEP_OWNER = {"script": "写手 + 系统检查", "assets": "系统 · 资产作业", "board": "系统 · 准备画面说明",
              "frames": "系统 · 出图", "video": "系统 · 出视频", "cut": "系统 · 拼整集"}
_ID_TOKEN = _re.compile(r"[A-Za-z0-9]*[_\-=/.:][A-Za-z0-9_\-=/.:]*[A-Za-z0-9]")
_stepbar_cache: dict[str, tuple[float, dict]] = {}
STEPBAR_TTL_S = 20.0


def _report_issue():
    """tools/master/report_issue.py 按文件路径加载一次（不改 sys.path，只调 load()）"""
    global _ri_mod
    if _ri_mod is None:
        spec = _ilu.spec_from_file_location("ns_tools_master_report_issue", _REPORT_ISSUE_FILE)
        if spec is None or spec.loader is None:
            raise FileNotFoundError(str(_REPORT_ISSUE_FILE))
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _ri_mod = mod
    return _ri_mod


def issue_step(step) -> str | None:
    """卡点的 step 字段（“8 资产就绪” / “6 补丁环” / “delegate” / “9”）→ 六步 id；认不出 → None"""
    s = str(step or "").strip()
    for st, sid in _STAGE_TO_STEP.items():
        if st in s:
            return sid
    m = _re.match(r"(\d+)", s)
    if m and int(m.group(1)) in _SOP_STEP_NO:
        return _SOP_STEP_NO[int(m.group(1))]
    for w, sid in _STEP_WORDS:
        if w in s:
            return sid
    return None


def owner_label(who: str | None) -> str:
    """登记人（agent 代号）→ 项目方看得懂的负责方"""
    w = str(who or "")
    u = w.upper()
    if not w:
        return "系统"
    if "项目方" in w or "OWNER" in u:
        return "你"
    if "MASTER" in u or "总调度" in w or "WATCHDOG" in u:
        return "总调度"
    if "WRITER" in u or "写手" in w or "SCRIPT" in u or "DELEGATE" in u:
        return "写手 / 总调度"
    if "ASSET" in u:
        return "系统 · 资产作业"
    if "GOLDEN" in u or "IMG" in u or "FRAME" in u:
        return "系统 · 出图"
    if "VID" in u:
        return "系统 · 出视频"
    return "工程师（" + w + "）"


def issue_plain(what: str | None, limit: int = 40) -> str:
    """卡点原文 → 一句短话：去掉文件名 / 作业 id / 代码编号（含 _ - = / . 的英文串），只留第一句"""
    t = _re.sub(r"【[^】]*】", "", str(what or ""))                    # 【登记人批注】不上页面
    t = _ID_TOKEN.sub("", t)
    t = _re.sub(r"\bep0*(\d+)\b", r"第\1集", t)
    t = _re.sub(r"\s*[/，,=]\s*(?=[，,/=）)】：:；;]|$)", "", t)              # 去掉 id 删掉后留下的孤立标点
    t = _re.sub(r"（[\s/，,=]*）|\([\s/，,=]*\)", "", t)
    t = _re.sub(r"\s+", " ", t).strip(" ：:；;，,/=")
    t = _re.sub(r"\s*（\s*", "（", t)
    for sep in ("：", "；", "。"):
        i = t.find(sep)
        if i >= 6:
            t = t[:i]
            break
    if t.count("（") > t.count("）"):                                   # 截断后括号没合上 → 去掉没合上的那段
        t = t[: t.rfind("（")]
    t = t.strip(" ，,") or "有一处卡住了，总调度在看"
    return t if len(t) <= limit else t[: limit - 1] + "…"


def open_issues(run: str, issues: list[dict] | None = None) -> list[dict]:
    """本剧未关的卡点（report_issue.load 折叠后的当前状态）"""
    rows = issues if issues is not None else _report_issue().load()
    return [i for i in rows if i.get("status") != "closed" and str(i.get("run") or "") == run]


def latest_first(rows: list[dict]) -> list[dict]:
    """A5 P1-2 / P2-4：同一卡点（同 id）只留最新一条，再按 阻断优先 + 时间降序（最新在前）排；
    同一句话（issue_plain 相同）的重复登记也只留最新一条（详情列表不再一样的话刷 5 遍）"""
    by_id: dict[str, dict] = {}
    anon: list[dict] = []
    for x in rows:
        k = str(x.get("id") or "")
        if not k:
            anon.append(x)
        elif k not in by_id or str(x.get("time") or "") >= str(by_id[k].get("time") or ""):
            by_id[k] = x
    out = sorted([*by_id.values(), *anon], key=lambda x: str(x.get("time") or ""), reverse=True)
    out = sorted(out, key=lambda x: not x.get("blocking"))               # 稳定排序：阻断在前，组内仍是最新在前
    seen: set[tuple[bool, str]] = set()
    uniq = []
    for x in out:
        k2 = (bool(x.get("blocking")), issue_plain(x.get("what"), 60))
        if k2 in seen:
            continue
        seen.add(k2)
        uniq.append(x)
    return uniq


def stepbar_view(pipe: dict, issues: list[dict]) -> dict:
    """纯函数（tests 用）：pipeline_status 的六步矩阵 + 本剧未关卡点 → 步骤条计数 + 每格（状态 / 一句话 / 负责方 / 卡点）+ 首页“现在”"""
    by_cell: dict[tuple[int, str], list[dict]] = {}
    unplaced = 0
    for i in issues:
        sid = issue_step(i.get("step"))
        try:
            ep = int(i.get("episode"))
        except (TypeError, ValueError):
            ep = 0
        if not sid or ep <= 0:
            unplaced += 1
            continue
        by_cell.setdefault((ep, sid), []).append(i)
    eps = []
    for e in pipe.get("episodes") or []:
        n = int(e["episode"])
        cells = {}
        for sid in STEP_IDS:
            c = dict((e.get("cells") or {}).get(sid) or {"state": "todo", "plain": "还没到这一步"})
            c.pop("why", None)                                   # sop_gate 原文只给开发者，不进这个接口
            its = latest_first(by_cell.get((n, sid)) or [])
            stale = 0
            if c["state"] == "done":                                    # 已完成的格子不再挂过时的“挡路”（那些单子总调度去关）
                stale = sum(1 for x in its if x.get("blocking"))
                its = [x for x in its if not x.get("blocking")]
            blocking = [x for x in its if x.get("blocking")]            # 已按时间降序：blocking[0] = 最新一条阻断
            if blocking and c["state"] in ("doing", "blocked"):         # 正在这一步 + 有阻断卡点 = 卡住
                c["state"] = "blocked"
                c["block"] = issue_plain(blocking[0].get("what"))        # 格子第二行：卡点一句话（sop_gate 的那句仍是第一行）
                c["owner"] = owner_label(blocking[0].get("who"))
            elif blocking and c["state"] == "todo":                     # 还没到这一步，但已知前面有坑：不标红，只提醒
                c["ahead"] = True
                c["block"] = "已知要先解决：" + issue_plain(blocking[0].get("what"), 30)
                c["owner"] = owner_label(blocking[0].get("who"))
            else:
                c["owner"] = "" if c["state"] in ("done", "todo") else STEP_OWNER[sid]
            c.setdefault("ahead", False)
            c.setdefault("block", "")
            c["issues"] = [{"id": x.get("id"), "text": issue_plain(x.get("what"), 60), "owner": owner_label(x.get("who")),
                            "blocking": bool(x.get("blocking")), "at": x.get("time")} for x in its[:5]]
            c["issues_more"] = max(0, len(its) - 5)
            c["stale"] = stale
            cells[sid] = c
        eps.append({"episode": n, "stage": e.get("stage"), "plain": e.get("plain") or "", "retro": e.get("retro"), "cells": cells})
    labels = {s["id"]: s["label"] for s in pipe.get("steps") or []}
    steps = []
    for sid in STEP_IDS:
        cnt = {k: sum(1 for e in eps if e["cells"][sid]["state"] == k) for k in ("done", "doing", "blocked", "todo")}
        steps.append({"id": sid, "label": labels.get(sid, sid), "stages": STEP_STAGES[sid], **cnt})
    # 首页“现在在哪”：最前面一集还没完成的（有动静的优先），它停在哪一步、一句话
    live = [e for e in eps if any(e["cells"][s]["state"] in ("doing", "blocked") for s in STEP_IDS)]
    focus = None
    if live:
        f = live[0]
        sid = next(s for s in STEP_IDS if f["cells"][s]["state"] in ("doing", "blocked"))
        focus = {"episode": f["episode"], "step": sid, "label": labels.get(sid, sid), "state": f["cells"][sid]["state"],
                 "plain": f["cells"][sid]["plain"], "block": f["cells"][sid]["block"], "owner": f["cells"][sid]["owner"]}
    doing = [{"episode": e["episode"], "step": s, "label": labels.get(s, s), "plain": e["cells"][s]["plain"], "owner": e["cells"][s]["owner"]}
             for e in eps for s in STEP_IDS if e["cells"][s]["state"] == "doing"]
    blocked = [{"episode": e["episode"], "step": s, "label": labels.get(s, s), "plain": e["cells"][s]["plain"], "block": e["cells"][s]["block"],
                "owner": e["cells"][s]["owner"],
                "n_issues": len(e["cells"][s]["issues"]) + e["cells"][s]["issues_more"]}
               for e in eps for s in STEP_IDS if e["cells"][s]["state"] == "blocked"]
    return {"run": pipe.get("run"), "title": pipe.get("title"), "episodes_total": pipe.get("episodes_total") or len(eps),
            "steps": steps, "episodes": eps, "now": {"focus": focus, "doing": doing[:8], "blocked": blocked[:8]},
            "issues_open": len(issues), "unplaced": unplaced}


def stepbar(run: str | None = None) -> dict:
    key = run or ""
    hit = _stepbar_cache.get(key)
    if hit and _time.time() - hit[0] < STEPBAR_TTL_S:
        return hit[1]
    pipe = _PSTAT.pipeline_status(run)                                 # 404 / 503 原样抛（sop_gate 读不到不猜）
    try:
        issues = open_issues(pipe["run"])
        issues_err = None
    except Exception as e:  # noqa: BLE001  卡点表读不到：矩阵照常给，页面写明“卡点读不到”
        issues, issues_err = [], f"卡点登记读不到：{type(e).__name__}"
    out = stepbar_view(pipe, issues)
    out["issues_error"] = issues_err
    _stepbar_cache[key] = (_time.time(), out)
    return out


router = _APIRouter(tags=["sop-stepbar"])


@router.get("/api/sop/stepbar")
def api_stepbar(run: str | None = None):
    try:
        return stepbar(run)
    except _HTTPException:
        raise


# 注册：app.py 已 include pipeline_status.router（第 208 行附近），本模块在那之前被 import（第 43 行）——
# 把只读聚合挂到同一个 router 上，不改 app.py（W5 的可改范围只有 sop.py）。以后合并时可改成 app.include_router(SOP.router)。
_PSTAT.router.include_router(router)
