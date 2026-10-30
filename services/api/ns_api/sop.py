"""
SOP 阶段 S1–S5 与关口 G1–G5（docs/SOP_production.md「★ 阶段闸门与资源优先级」、docs/SOP_parameters.md）。

只读：读 data/state_timeline.json、data/scenes.json（tools/build_state_timeline.py 生成）、data/looks/schedule.json、
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
        self.timeline = _read(self.root / "data" / "state_timeline.json")
        self.scenes = _read(self.root / "data" / "scenes.json")
        self.schedule = _read(self.root / "data" / "looks" / "schedule.json", {}) or {}
        self.owner_gates = _read(self.root / OWNER_GATES, {}) or {}
        self.tl_shots = {s.get("shot_id"): s for s in (self.timeline or {}).get("shots") or [] if isinstance(s, dict)}
        self.scene_by_id = {s.get("scene_id"): s for s in (self.scenes or {}).get("scenes") or [] if isinstance(s, dict)}
        self._qa: dict[int, dict | None] = {}
        self.stale = timeline_stale(self.root, self.timeline, self.scenes)
        self.script = load_script(self.root)
        self.ep_versions = episode_versions(self.script)       # D-1：合并导入后各集剧本版本不同，S1 按集判
        self.source_drift = source_drift(self.root, self.timeline, self.script)

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


def timeline_stale(root: Path, timeline: dict | None, scenes: dict | None) -> list[str]:
    """状态表记的输入哈希（剧本 script_sha、source_hashes、底板 sha）与磁盘不一致 → 变了的输入名"""
    if timeline is None:
        return []
    try:
        from ns_agent.state_timeline import stale_inputs
        return stale_inputs(root, timeline, scenes)
    except Exception as e:  # noqa: BLE001 — 算不出就当过期（不能拿旧表放行）
        return [f"check_failed:{type(e).__name__}"]


def load_script(root: Path):
    """data/import/script_v2.json → ScriptImport；没有 / 读不了 → None（SOP 退回状态表的整份版本）"""
    p = root / "data" / "import" / "script_v2.json"
    try:
        if p.is_file():
            from ns_schema.script import ScriptImport
            return ScriptImport.model_validate_json(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pass
    return None


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
                "blockers": [_b("timeline_missing", "S1", "还没有 data/state_timeline.json（状态表）", "laptop", CLI_TIMELINE)]}
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
    out: dict[int, list[str]] = {}
    for k, e in ((inp.timeline or {}).get("episodes") or {}).items():
        if not isinstance(e, dict):
            continue
        n = int(k)
        ep_plans = plans.get(str(k)) or {}
        required = list(dict.fromkeys(present.get(n, []) + list(e.get("characters") or []) + list(ep_plans)))
        chars = [c for c in required if not _plan_confirmed(ep_plans.get(c))]
        chars += [c for c in e.get("unconfirmed_characters") or [] if c not in chars]
        if not e.get("look_confirmed") and not chars:
            chars = ["<角色>"]
        if chars:
            out[n] = chars
    return out


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
        return [_b("timeline_missing", "S2", "还没有状态表 data/state_timeline.json", "laptop", CLI_TIMELINE)]
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
            "s2_ready": (tl or {}).get("s2_ready"), "scene_id": (tl or {}).get("scene_id"),
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
        acts.append({"gate": "G3", "stage": "S1", "title": "采纳 v3 剧本加强（G3）",
                     "why": "S1 出口闸门：没有项目方采纳，全部镜头停在 S1",
                     "cli": CLI_S1_ACCEPT, "actionable": not upstream, "waiting_on": upstream})
    for char, eps in sorted(unconfirmed_looks(inp).items()):
        acts.append({"gate": "look", "stage": "S2", "title": f"确认造型：{char}（{len(eps)} 集）",
                     "why": "S2：本集造型没有项目方确认，镜头不进 S3。可只确认看过的集，例如先确认第 "
                            f"{eps[0]} 集", "episodes": eps, "character": char,
                     "cli": cli_look(str(eps[0]), char), "cli_all": cli_look(ep_ranges(eps), char),
                     "actionable": True, "waiting_on": []})
    for sc in (inp.scenes or {}).get("scenes") or []:
        if sc.get("plate_status") == "candidate":
            acts.append({"gate": "plate", "stage": "S2", "title": f"确认场景底板 {sc.get('scene_id')}（{sc.get('place') or ''}）",
                         "why": f"S3 只能用项目方确认的底板；用到它的镜头 {len(sc.get('shots') or [])} 个",
                         "plate": sc.get("plate"), "cli": cli_plate(sc["scene_id"]),
                         "actionable": not (inp.scenes or {}).get("provisional", True) and not inp.stale,
                         "waiting_on": (["scenes.json 仍是临时分组（S1 未过）"] if (inp.scenes or {}).get("provisional", True) else [])
                         + (["状态表过期，先重建"] if inp.stale else [])})
    g4 = next(g for g in gate_list if g["id"] == "G4")
    if g4["status"] != "passed":
        b = g4["blockers"][0]
        acts.append({"gate": "G4", "stage": "S3", "title": f"锁定第 {g4['sample_episode']} 集样片参数（G4）",
                     "why": "首集即 G4：锁定前其余各集不放量出视频", "cli": b.get("cli"),
                     "actionable": bool(b.get("actionable")),
                     "waiting_on": [] if b.get("actionable") else [g4["detail"]]})
    for n, e in sorted(ep_states.items()):
        for b in e["episode_blockers"]:
            if b["code"] == "g5_pending":
                acts.append({"gate": "G5", "stage": "S5", "title": f"验收 ep{n:02d} 成片（G5）", "why": e["final"] or "",
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


def project_summary(slug: str, name: str, ev: dict, inp: Inputs) -> dict:
    shots = ev["shots"]
    tl = inp.timeline or {}
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
