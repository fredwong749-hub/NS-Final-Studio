"""统一编排器：剧本导入之后（含写作）每集一个状态机（DISTILL 11-02，L-102 / ITERATION_PROTOCOL §G1，规则 K-OPS-X02）。

不另起生产入口：每一段的“执行者”都是已有工具——
  script      HOLLYWOOD 写作 + 三评审 + 事实核对（tools/script_rsi/hollywood_r5.py，外部写作 API）
  import      producer.py import-staged（PRODUCER 令牌通道，项目方 11-01 方案 A 授权）
  jobs        episode_pipeline.py prepare（重编 first_frame_jobs + full_redo + ready_episodes）
  assets      preflight 依赖 / *_hold.json（producer + tools/factory/deps.py）
  first/last  producer 常驻（服务器本机道 / 笔记本代派，NETFIX dispatch）
  image_gate  生成契约 Q1–Q8 + 本地看图闸门（config/vqa.json enforce）
  video       night 常驻：首帧过闸门即编 Pika 变体派单
  video_check score_clip（J4 / V6 / V7 / 身份）+ 视频看图
  assemble    night.finalize → ns_post.assemble（导演层 config/post/director.json）
  post        tools/director/finish.py（lip_redo → post_pass → film_score）
  film_score  tools/director/film_score.py → data/film_score/epNN.json
  delivery    K-EDT-817 选后期版 / 原版（code）+ 项目方看片确认（owner）
本模块只做三件事：① 从真实记录现推每集每段的状态（不另存副本）；② 标注每个判断点的 decider；③ 给出卡点和下一步命令。
状态 / 卡点写 data/autopilot/flow/status.json（UIRSI 界面直接读），覆盖率写 data/autopilot/coverage.json。

  run.py status --all                 全局进度 + 卡点（同时写 status.json）
  run.py flow --episode 4             这一集逐段状态
  run.py flow --episode 4 --dry-run   冷启动演练：假设这一集是一份新剧本，从剧本走到成片，不出图、不调付费 API，列出全部要人 / Claude 介入的断点
  run.py coverage                     无 Claude 覆盖率（data/autopilot/coverage.json）
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import policy as POL  # noqa: E402

PY = ".venv/Scripts/python.exe"
DECIDERS = ("code", "local_model", "api_model", "owner", "claude")
# L-109（项目方 11-02 03:3x）：测试期剧本写 / 评交 Claude agent（config/llm_providers.json writer_backend=claude_agent），上线切回 api。
# 这类判断点标 writer=True：测试期记 claude_testphase（单列，不进 claude 计数），上线配置记 api_model（总调度 11-02 口径）
TESTPHASE = "claude_testphase"


def writer_backend(root: Path = ROOT) -> str:
    """config/llm_providers.json writer_backend；文件缺失 = 未配置测试期后端 → api（上线默认）；文件坏了直接抛出（不静默当 api）"""
    p = root / "config/llm_providers.json"
    if not p.exists():
        return "api"
    return json.loads(p.read_text(encoding="utf-8")).get("writer_backend") or "api"


def now_of(p: dict, backend: str | None = None, root: Path = ROOT) -> str:
    """判断点的现行 decider：writer 点按 writer_backend 现算"""
    if p.get("writer"):
        return TESTPHASE if (backend or writer_backend(root)) == "claude_agent" else "api_model"
    return p["now"]

# ---------------------------------------------------------------------------------------------- 段 + 判断点
# 每个判断点：what / now（现在实际由谁判）/ target（目标）/ ref（执行它的代码 / 规则 / 策略 / 判断清单号）/ plan（now=claude 时必填）
STAGES: list[dict] = [
    {"id": "brief", "name": "故事提纲 P0", "exec": "#/script-create ① 新建剧本（POST /api/story-runs）或 run.py flow-start --brief", "auto": False,
     "points": [
         {"what": "填 P0 Brief（题材 / 人物 / 集数 / 时长）", "now": "owner", "target": "owner", "ref": "config/pipeline/examples/P0_brief.json",
          "who": "项目方（新建剧本本身就是项目方的动作）"},
         {"what": "Brief 格式校验（nsfs.brief/1）", "now": "code", "target": "code", "ref": "tools/pipeline/run_chain.py"},
     ]},
    {"id": "chain", "name": "写作链 P1–P4", "exec": "tools/pipeline/run_chain.py（services/api/ns_api/story_runs.py 后台线程）", "auto": True,
     "points": [
         {"what": "storyline → 单集大纲 → 剧本 → 分镜（逐段写 + 校验 + 返修 ≤2 轮）", "now": "api_model", "writer": True, "target": "api_model", "ref": "config/pipeline/chain.yaml"},
         {"what": "每段格式 / 字段校验", "now": "code", "target": "code", "ref": "tools/pipeline/run_chain.py"},
         {"what": "写作预算", "now": "code", "target": "code", "ref": "budget.writing_episode_cap_usd"},
     ]},
    {"id": "script", "name": "好莱坞返修 + 评分", "exec": "tools/script_rsi/autoflow.py run --run-dir <run> --episode N（HOLLYWOOD r8）", "auto": True,
     "points": [
         {"what": "写 / 返修剧本（逐行补丁 + 事实表）", "now": "api_model", "writer": True, "target": "api_model", "ref": "config/prompts/hollywood_writer.md"},
         {"what": "三评审按可核对清单打分", "now": "api_model", "writer": True, "target": "api_model", "ref": "config/prompts/hollywood_judge.md"},
         {"what": "事实核对（说话人顺序 F1 代码 + F2 独立核对）", "now": "code", "target": "code", "ref": "tools/script_rsi/hollywood_r5.py gate5"},
         {"what": "预算 / 1 轮不涨即停", "now": "code", "target": "code", "ref": "budget.writing_total_cap_usd / no_gain_stop_rounds（DJ-26）"},
         {"what": "评审噪声大时先修尺子", "now": "code", "target": "code", "ref": "tools/script_rsi/autoflow.py（score_r6 + policy.noise_stop，HOLLYWOOD r8；DJ-29）"},
         {"what": "选导入稿（达线或预算用完取最高分）", "now": "code", "target": "code", "ref": "policy.pick_import（DJ-27）"},
     ]},
    {"id": "import", "name": "剧本导入", "exec": "tools/autopilot/producer.py import-staged", "auto": False,
     "points": [
         {"what": "P4 校验 / writer lint 阻断 0", "now": "code", "target": "code", "ref": "tools/qa/writer_lints.py"},
         {"what": "执行导入（PRODUCER 令牌通道）", "now": "owner", "target": "code", "ref": "services/api/ns_api/script_inbox.py PRODUCER_BY（DJ-43）",
          "plan": "项目方 11-01 方案 A 已授权 PRODUCER 导入；Claude 会话被权限系统拦是 Claude 的限制，不是系统闸门——编排器无人值守时直接调 producer.py import-staged", "who": "DEBUG-RSI（producer.import_staged）+ UIRSI（页面“送去导入”改走 PRODUCER 通道）"},
         {"what": "新剧本作为新 run 加入（不替换正式剧；GPU 正式剧优先、新剧用空档）", "now": "code", "target": "code",
          "ref": "resources.multi_run / run_priority（DJ-54）；config/pipeline/runs.json"},
     ]},
    {"id": "jobs", "name": "作业编译", "exec": "tools/autopilot/episode_pipeline.py prepare", "auto": True,
     "points": [
         {"what": "发现新导入的集（导入事件 imports.jsonl + ep_hash 兜底）", "now": "code", "target": "code", "ref": "tools/autopilot/episode_pipeline.py；tools/autopilot/import_events.py（WORKFLOW 11-02）"},
         {"what": "重编 first_frame_jobs + jobs_vs_import 一致才派", "now": "code", "target": "code", "ref": "tools/autopilot/full_redo.py image_jobs_green（DJ-44）"},
     ]},
    {"id": "assets", "name": "资产就绪", "exec": "tools/factory/deps.py", "auto": True,
     "points": [
         {"what": "preflight 依赖闭包齐全", "now": "code", "target": "code", "ref": "tools/factory/deps.py（K-OPS-F02）"},
         {"what": "已有角色的新造型设定图首次挑选（第二季新造型，L-108）", "now": "claude", "target": "code",
          "ref": "tools/assetmaster/choose.py enforce_item_check + services/agent/ns_agent/sheet_intake.py（K-AST-260 / 264）",
          "plan": "choose.py 现在仍要求 data/assetmaster/sheet_item_checks.json 里有人工 / Q2 单品记录才 adopt；改为 sheet_intake（IN1 袖子镜像 / IN2 外层）+ 契约 Q2 自动判定直接写记录，Q1 对已定身份脸；全过取 Q1 最高（repair.py 同口径），by=POLICY 可撤销",
          "who": "IMGFIX（choose.py 单品记录自动化）"},
         {"what": "全新角色的身份脸 / 设定图首次挑选", "now": "claude", "target": "local_model",
          "ref": "tools/assetmaster/choose.py（新角色没有身份脸可比，Q1 无从判）",
          "plan": "候选 → ArcFace 跨栏 / 跨 seed 一致性排序（identity_rank）+ sheet_intake + asset_sheet_inspect（本地 VLM）+ VQA 无缺陷 → 取一致性最高的一张登记身份脸（脸部裁切规则 L-086）+ 设定图，by=POLICY、项目方可撤销",
          "who": "IMGFIX / ASSETMASTER"},
         {"what": "设定图入库完整性（袖子镜像 / 外层存在）", "now": "code", "target": "code", "ref": "services/agent/ns_agent/sheet_intake.py（K-AST-264，DJ-06）"},
         {"what": "资产修复候选自动选（契约 R1–R7）", "now": "code", "target": "code", "ref": "tools/asset_repair/repair.py（K-AST-265 待验，DJ-07）"},
         {"what": "资产修复期间暂缓相关镜（*_hold.json）", "now": "code", "target": "code", "ref": "tools/autopilot/producer.py asset_hold_objects（K-OPS-E04）"},
     ]},
    {"id": "first", "name": "首帧", "exec": "producer 常驻", "auto": True,
     "points": [
         {"what": "派单 / 道分配 / 积压闸", "now": "code", "target": "code", "ref": "resources.image_lanes / score_backlog（DJ-14 / DJ-16）"},
         {"what": "重试阶梯（换 seed → 换参考 → 尽力）", "now": "code", "target": "code", "ref": "retry.max_content_tries"},
         {"what": "系统暂停超时恢复（运维暂停到点恢复、显式暂停只告警）", "now": "code", "target": "code", "ref": "policy.pause_decision → producer 每拍（K-OPS-E08；DJ-15）"},
         {"what": "尽力版挡住下游时重置（规则 / 资产版本变 → 自动 reset）", "now": "code", "target": "code", "ref": "tools/autopilot/producer.py K-OPS-E11（gates.best_effort_policy；DJ-12）",
          "plan": "producer 每拍比对尽力版的规则 / 资产版本，变了自动 reset（不计次）", "who": "DEBUG-RSI（口径待总调度定）"},
         {"what": "服务器交还（preflight 0 挡 + refs sha 一致）", "now": "code", "target": "code", "ref": "policy.handback_ok（DJ-21–23）"},
         {"what": "服务器代码版本 ≥ min_code_sv（低于只报不派）", "now": "code", "target": "code",
          "ref": "policy.code_sv_problem ← tools/factory/decisions_guard.py（服务器每拍 F09 拒派）+ policy.deployed_sv / handback_ok（交还）；K-OPS-X08（DJ-24）"},
     ]},
    {"id": "last", "name": "尾帧", "exec": "producer 常驻", "auto": True,
     "points": [
         {"what": "首帧过契约后派尾帧", "now": "code", "target": "code", "ref": "tools/autopilot/producer.py derive"},
     ]},
    {"id": "image_gate", "name": "看图闸门", "exec": "契约 + 本地 VLM", "auto": True,
     "points": [
         {"what": "生成契约 Q1–Q8", "now": "code", "target": "code", "ref": "services/agent/ns_agent/gen_contract/postflight.py"},
         {"what": "本地看图 Q9（不看镜头 / 景别 / 发色 / 多人 …）", "now": "local_model", "target": "local_model", "ref": "config/prompts/vqa_inspect.md；gates.blocking_checks"},
         {"what": "背影后脑误判复核", "now": "local_model", "target": "local_model", "ref": "gates.back_view_stranger_recheck（DJ-08）"},
         {"what": "换版后首批复核（批量同错 → 停派，canary 暂停不自动恢复）", "now": "code", "target": "code", "ref": "services/agent/ns_agent/vqa/canary.py（DJ-03）"},
         {"what": "人指出的漏检入回归集（改口径前回归必须全过）", "now": "code", "target": "code", "ref": "tools/vqa/regression_check.py + data/vqa/regression/；iter_gate Q2（DJ-09）"},
         {"what": "给项目方看之前签 master_review", "now": "claude", "target": "code", "ref": "gates.only_show_passing（DJ-11）",
          "plan": "tools/vqa/autosign.py 已就位（门槛未过：一致率 0.796、漏放 8 → 维持人工签）；VQAGATE 用现行契约重打 8 张漏放后再判，过 ≥0.95 且漏放 0 才切换", "who": "VQAGATE / ITERAUDIT"},
     ]},
    {"id": "video", "name": "视频", "exec": "night 常驻（Pika）", "auto": True,
     "points": [
         {"what": "首帧过闸门即编 Pika 变体派单", "now": "code", "target": "code", "ref": "tools/series10_video/night.py；config/pipeline/video_policy.json pika_only"},
     ]},
    {"id": "video_check", "name": "视频检测", "exec": "score_clip + 视频看图", "auto": True,
     "points": [
         {"what": "顿挫 J4 / 多肢 V6 / 口型 V7 / 身份", "now": "code", "target": "code", "ref": "tools/series10_video/score_clip.py；gates.video_stutter_j4_gt"},
         {"what": "视频看图（跨帧身份 / 外套 / 形变 / 片头看镜头）", "now": "local_model", "target": "local_model", "ref": "config/vqa.json video_checks"},
     ]},
    {"id": "assemble", "name": "合成", "exec": "night.finalize → ns_post.assemble", "auto": True,
     "points": [
         {"what": "导演层（刀长 / J-cut / 配乐强度）", "now": "code", "target": "code", "ref": "config/post/director.json（K-EDT-813/814/816）"},
         {"what": "尽力镜不进合成；auto_force 只对过契约的镜", "now": "code", "target": "code", "ref": "gates.best_effort_policy（总调度 02:2x 定）"},
     ]},
    {"id": "post", "name": "后期", "exec": "tools/director/finish.py", "auto": True,
     "points": [
         {"what": "口型重出请求（K-EDT-805）→ vidgen 作废重出（不计次）", "now": "code", "target": "code", "ref": "tools/director/finish.py；data/director/redo_requests.json；tools/series10_video/vidgen.py check_lip_redo"},
         {"what": "调色 / 音效 / 响度", "now": "code", "target": "code", "ref": "tools/director/post_pass.py（K-EDT-801–803）"},
     ]},
    {"id": "film_score", "name": "成片评分", "exec": "tools/director/film_score.py", "auto": True,
     "points": [
         {"what": "成片分 /50（技术 + 观感，看图项可选本地 VLM）", "now": "code", "target": "code", "ref": "tools/director/film_score.py"},
     ]},
    {"id": "delivery", "name": "交付闸门", "exec": "run.py approve-delivery", "auto": False,
     "points": [
         {"what": "交后期版还是原版", "now": "code", "target": "code", "ref": "tools/director/finish.py delivery_gate（K-EDT-817）"},
         {"what": "预览交付棘轮（≥max(30, 历史最好−1)，口型重出 0，A1 无零分）", "now": "code", "target": "code", "ref": "policy.delivery_check（gates.delivery_gate）"},
         {"what": "项目方看预览确认交付", "now": "owner", "target": "owner", "ref": "gates.delivery_gate.owner_confirm", "who": "项目方（保留闸门）"},
     ]},
]
STAGE_IDS = [s["id"] for s in STAGES]
# 跨段运维判断（不属于某一集，但同样要覆盖）
OPS_POINTS = [
    {"what": "每轮 cut 系统版本 + deploy", "now": "code", "target": "code", "ref": "deploy.cut_every_iteration（DJ-34）"},
    {"what": "只推 tag 内文件；cut 失败不许 deploy", "now": "code", "target": "code", "ref": "deploy.push_tag_files_only / cut_failed_no_deploy（K-OPS-F06 / F07，DJ-35）"},
    {"what": "多个重启请求合并、按道排空", "now": "code", "target": "code", "ref": "tools/autopilot/restart_queue.py（K-OPS-W16，DJ-20）"},
    {"what": "决策 / 配置类数据随版本快照、回滚恢复", "now": "code", "target": "code", "ref": "tools/autopilot/state_snapshot.py（K-OPS-X06，DJ-53；cut 接入待 FACTORY）"},
    {"what": ":8800 空闲才重启（接重启队列，编排器每拍调）", "now": "code", "target": "code", "ref": "tools/uirsi/api_restart_guard.py tick ← flow.tick（DJ-36）"},
    {"what": "写作交稿即推进（writer_tasks done_marker → advance_cmd）", "now": "code", "target": "code", "ref": "flow.autoflow_tick ← run.py tick（HOLLYWOOD autoflow，总调度 11-02）"},
    {"what": "交稿 / 过导入闸门后自动打线 3 分（line3_dirty.json → line3_score.py）", "now": "code", "target": "code", "ref": "flow.line3_tick ← run.py tick（HOLLYWOOD，总调度 11-02）"},
    {"what": "连接 / 隧道恢复", "now": "code", "target": "code", "ref": "tools/netfix/tunnel_supervisor.py（DJ-18）"},
]


# ---------------------------------------------------------------------------------------------- 世界（真实记录）
def _wj(p: Path, obj, indent: int | None = 1) -> None:
    """原子写 JSON（tmp + os.replace；UIRSI / 看板会在任意时刻读 status.json 等文件）"""
    import os
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=indent), encoding="utf-8")
    os.replace(tmp, p)


def _jl(p: Path, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


class World:
    def __init__(self, root: Path = ROOT, run_id: str | None = None, write: bool = False):
        if run_id is None:                      # K-OPS-W17：默认主 run 从 config/pipeline/runs.json 读，不写死
            import runs as RUNS
            run_id = RUNS.primary_run(root)
        self.root, self.run_id, self.write = root, run_id, write
        self.data = root / "data"
        self.script = _jl(self.data / "import/script_v2.json", {}) or {}
        self.registry = _jl(self.data / "producer/registry.json", {}) or {}
        self.ctrl = _jl(self.data / "producer/control.json", {}) or {}
        self.ready = (_jl(self.data / "autopilot/ready_episodes.json", {}) or {}).get("episodes") or {}
        self.assets_ready = _jl(self.data / "autopilot/assets_ready.json", {}) or {}
        jobs = _jl(self.data / f"pipeline/runs/{run_id}/assets/first_frame_jobs.json", {}) or {}
        jl = jobs.get("jobs") if isinstance(jobs, dict) else jobs
        self.jobs = jl if isinstance(jl, list) else (list(jl.values()) if isinstance(jl, dict) else [])
        self.holds = set()
        for f in (self.data / "autopilot").glob("*_hold.json"):
            d = _jl(f, {}) or {}
            if d.get("active"):
                self.holds |= {o for it in d.get("shots") or [] for o in it.get("objects") or []}
        self.eps_dir = self.data / "episodes" / "series10"
        self.net = _jl(self.data / "netfix/net_status.json", {}) or {}
        self.night = {h: _jl(self.data / f"pipeline/runs/{run_id}/video/state_{h}.json", {}) or {} for h in ("gpu33", "gpu36")}
        self.night_state = _jl(self.data / f"pipeline/runs/{run_id}/video/night_state.json", {}) or {}   # night.finalize 交付记录

    def imported(self) -> dict[int, dict]:
        return {int(e.get("number")): e for e in self.script.get("episodes") or [] if e.get("number") is not None}

    def reg_ep(self, ep: int) -> dict:
        return next((e for e in self.registry.get("episodes") or [] if int(e.get("ep", -1)) == ep), {}) or {}

    def jobs_for(self, ep: int) -> int:
        pre = f"ep{ep:02d}-"
        return sum(1 for j in self.jobs if str(j.get("shot") or j.get("shot_id") or j.get("id") or "").startswith(pre)
                   or str(j.get("shot_id", "")).startswith(pre))

    def _repo_path(self, p: str | None) -> Path | None:
        """交付记录里的路径（可能是服务器 / 笔记本绝对路径）→ 本仓库内的同名文件；不在 = None"""
        if not p:
            return None
        q = str(p).replace("\\", "/")
        i = q.find("data/")
        cand = self.root / (q[i:] if i >= 0 else q)
        return cand if cand.is_file() else None

    def latest_cut(self, ep: int) -> Path | None:
        """本集“现行成片”= night.finalize 的交付记录（night_state.json eps[ep].final，status=assembled）；
        没有时退到 producer 登记表 assembly 对象记录的路径；都没有 = 未合成（失败关闭，不按 mtime 猜——SYSARCH 11-02）。
        交付记录指向后期版（*_post.mp4）时返回它对应的原合成版，后期版由 post 段判断。"""
        rec = (self.night_state.get("eps") or {}).get(str(ep)) or {}
        f = self._repo_path(rec.get("final")) if rec.get("status") == "assembled" else None
        if f is None:
            ao = (self.reg_ep(ep).get("objects") or {}).get("assembly") or {}
            f = self._repo_path(ao.get("reason")) if ao.get("status") == "passed" else None
        if f is not None and f.stem.endswith("_post"):
            raw = f.with_name(f.stem[: -len("_post")] + f.suffix)
            return raw if raw.is_file() else f
        return f

    def night_director(self, ep: int) -> dict | None:
        d = ((self.night_state.get("eps") or {}).get(str(ep)) or {}).get("director")
        if d:
            return d
        for st in self.night.values():
            d = ((st.get("eps") or {}).get(str(ep)) or (st.get("eps") or {}).get(f"ep{ep:02d}") or {}).get("director")
            if d:
                return d
        return None


# ---------------------------------------------------------------------------------------------- 逐段现推
def _st(status: str, done=None, total=None, detail: str = "", blocker: str | None = None, cmd: str | None = None,
        needs: str | None = None) -> dict:
    return {"status": status, "done": done, "total": total, "detail": detail, "blocker": blocker, "cmd": cmd, "needs": needs}


def _count(shots: list, kind: str, what: str = "") -> tuple[int, int, int, int]:
    """→ (有产物, 已通过, 进行中, 尽力 / 不合格)。已通过 = 状态 passed 且确有当前产物（has）"""
    has = passed = running = bad = 0
    for s in shots:
        o = (s.get("objects") or {}).get(kind) or {}
        h = bool((s.get("has") or {}).get(kind))
        has += h
        passed += o.get("status") == "passed" and h
        running += o.get("status") == "running"
        bad += o.get("status") in ("best_effort", "failed")
    return has, passed, running, bad


def _inconsistent(shots: list) -> list[str]:
    """登记表自相矛盾：状态 passed 但没有当前产物，或尾帧 passed 而首帧未过（尾帧依赖首帧）"""
    out = []
    for s in shots:
        ob, hs = s.get("objects") or {}, s.get("has") or {}
        for k in ("first", "last", "video"):
            if (ob.get(k) or {}).get("status") == "passed" and not hs.get(k):
                out.append(f"{s['shot']}:{k} passed 但无当前版")
        if (ob.get("last") or {}).get("status") == "passed" and (ob.get("first") or {}).get("status") != "passed":
            out.append(f"{s['shot']}:last passed 而首帧未过")
    return out


def episode_status(w: World, ep: int) -> dict:
    imp = w.imported().get(ep)
    re_ = w.reg_ep(ep)
    shots = re_.get("shots") or []
    n = len((imp or {}).get("shots") or []) or len(shots)
    S: dict[str, dict] = {}
    S["brief"] = _st("done", detail="正式剧本（已导入）") if imp else _st("todo", needs="owner")
    S["chain"] = _st("done", detail="正式剧本（已导入）") if imp else _st("waiting")
    S["script"] = _st("done", detail="已有导入稿") if imp else _st("todo", cmd=f"{PY} tools/script_rsi/hollywood_r5.py（写作 + 评审，预算见 budget.yaml）")
    S["import"] = _st("done", n, n, f"script_v2.json {n} 镜") if imp and n else _st(
        "todo", cmd=f"{PY} tools/autopilot/producer.py import-staged --obj <暂存稿> --reason <sha256>", needs="code")
    nj = w.jobs_for(ep)
    ready = str(ep) in w.ready
    S["jobs"] = _st("done" if (nj and ready) else ("todo" if imp else "waiting"), nj, n,
                    f"作业 {nj} 条" + ("，已进 ready_episodes" if ready else "，未进 ready_episodes"),
                    cmd=None if (nj and ready) else f"{PY} tools/autopilot/episode_pipeline.py prepare {ep}")
    held = [s["shot"] for s in shots if any(o in w.holds for o in (f"first:{s['shot']}", f"last:{s['shot']}"))]
    a_ok = sum(1 for s in shots if ((s.get("objects") or {}).get("assets") or {}).get("status") == "passed")
    S["assets"] = _st("blocked" if held else ("done" if shots and a_ok == len(shots) else ("waiting" if not shots else "running")),
                      a_ok, len(shots), f"参考齐 {a_ok}/{len(shots)}" + (f"；暂缓 {len(held)} 镜（*_hold.json）" if held else ""),
                      blocker=f"资产暂缓清单挡住 {len(held)} 镜" if held else None, needs="code" if held else None)
    for kind in ("first", "last"):
        has, passed, running, bad = _count(shots, kind, kind)
        S[kind] = _st("done" if shots and has == len(shots) else ("running" if running or has else ("waiting" if not shots else "todo")),
                      has, len(shots), f"已出 {has}/{len(shots)}，在跑 {running}")
    f_has, f_pass, _, f_bad = _count(shots, "first", "")
    l_has, l_pass, _, l_bad = _count(shots, "last", "")
    tot = 2 * len(shots)
    inc = _inconsistent(shots)
    S["image_gate"] = _st("done" if shots and f_pass + l_pass == tot else ("blocked" if f_bad + l_bad else ("running" if f_has + l_has else "waiting")),
                          f_pass + l_pass, tot, f"首帧过 {f_pass} · 尾帧过 {l_pass} · 尽力 / 不合格 {f_bad + l_bad}",
                          blocker=f"{f_bad + l_bad} 个对象尽力 / 不合格（不进合成，等规则或资产修复后 reset）" if f_bad + l_bad else None,
                          needs="claude" if f_bad + l_bad else None)
    if inc:
        S["image_gate"]["detail"] += f"；登记表矛盾 {len(inc)} 处（例 {inc[0]}）"
        S["image_gate"]["inconsistent"] = inc
    v_has, v_pass, v_run, v_bad = _count(shots, "video", "")
    S["video"] = _st("done" if shots and v_has == len(shots) else ("running" if v_has or v_run else "waiting"), v_has, len(shots),
                     f"已出 {v_has}/{len(shots)}")
    S["video_check"] = _st("done" if shots and v_pass == len(shots) else ("blocked" if v_bad else ("running" if v_pass else "waiting")),
                           v_pass, len(shots), f"已定下 {v_pass}/{len(shots)}，尽力 {v_bad}",
                           blocker=f"{v_bad} 镜视频尽力" if v_bad else None, needs="claude" if v_bad else None)
    cut = w.latest_cut(ep)
    upstream_ok = S["video_check"]["status"] == "done"
    if cut and upstream_ok:
        S["assemble"] = _st("done", detail=str(cut.relative_to(w.root)).replace("\\", "/"))
    elif cut:
        S["assemble"] = _st("stale", detail=f"{cut.name} 是旧版（新视频未全部定下）")
    else:
        S["assemble"] = _st("waiting", detail="等视频全部定下（night.finalize 自动合成）")
    post = cut.with_name(cut.stem + "_post.mp4") if cut else None
    S["post"] = _st("done", detail=post.name) if post and post.exists() and upstream_ok else _st(
        "waiting" if not (cut and upstream_ok) else "todo", cmd=f"{PY} tools/director/finish.py {cut.relative_to(w.root).as_posix()}" if cut else None)
    lr = [r for r in ((_jl(w.data / "director/redo_requests.json", {}) or {}).get("requests") or [])
          if str(r.get("shot", "")).startswith(f"ep{ep:02d}-") and r.get("status") == "pending"]
    if lr:
        S["post"]["detail"] += f"；口型重出待处理 {len(lr)} 镜（K-EDT-805，vidgen 自动消费）"
    fs = _jl(w.data / f"film_score/ep{ep:02d}.json")
    # 成片分是不是这一版的：比对成片分 JSON 记的 video 路径 = 现行成片（或其后期版），不比修改时间（SYSARCH 11-02）
    cut_rels = {_rel(w.root, x) for x in (cut, post) if x is not None}
    fresh = bool(fs and cut and upstream_ok and str(fs.get("video") or "").replace("\\", "/") in cut_rels)
    S["film_score"] = _st("done" if fresh else ("stale" if fs else "waiting"),
                          detail=f"{fs.get('total_50')}/50（测到 {fs.get('coverage')}，{fs.get('name')}）" if fs else "")
    gate = _jl(w.data / f"autopilot/flow/gates/ep{ep:02d}_delivery.json", {}) or {}
    dg = w.night_director(ep) or {}
    dgate = dg.get("delivery_gate") or {}
    best_p = w.data / "autopilot/flow/film_best.json"
    best = POL.update_best(best_p, ep, fs) if (fresh and w.write) else ((_jl(best_p, {}) or {}).get(f"ep{ep:02d}") or {}).get("best")
    if gate.get("approved"):
        S["delivery"] = _st("done", detail=f"{gate.get('by')} {gate.get('at')}")
    elif fresh:
        chk = POL.delivery_check(fs, best, len(lr))
        pick = f"K-EDT-817 交 {dgate.get('deliver', '?')}" + ("；" + "；".join(dgate.get("why")) if dgate.get("why") else "")
        if chk["ok"]:
            S["delivery"] = _st("blocked", detail=f"预览闸门过（最低线 {chk['min_line']:g}）；{pick}", blocker="等项目方看预览确认",
                                cmd=f"{PY} tools/autopilot/run.py approve-delivery --episode {ep}", needs="owner")
        else:
            S["delivery"] = _st("blocked", detail=f"预览闸门不过（最低线 {chk['min_line']:g}）；{pick}",
                                blocker="；".join(chk["why"]), needs="code")
        S["delivery"]["gate_check"] = chk
    else:
        S["delivery"] = _st("waiting")
    cur = next((k for k in STAGE_IDS if S[k]["status"] != "done"), None)
    return {"ep": ep, "title": (imp or {}).get("title") or re_.get("title"), "shots": n, "current": cur, "stages": S,
            "blockers": [{"stage": k, "blocker": v["blocker"], "needs": v["needs"]} for k, v in S.items() if v.get("blocker")]}


WRITE_FILES = {"P1": "P1_storyline.json", "P2": "P2_ep{ep:02d}_outline.json", "P3": "P3_ep{ep:02d}_screenplay.json", "P4": "P4_ep{ep:02d}.md"}
RUNS_INDEX = "data/autopilot/flow/runs.json"


def _report_ok(f: Path) -> str | None:
    """run_chain 每段产物旁边的 <名>.report.json → ok / 其他状态 / None（没有）"""
    if not f.exists():
        return None
    rep = _jl(f.with_name(f.name + ".report.json"), {}) or {}
    return rep.get("status") or "unchecked"


def writing_status(root: Path, run_dir: Path, ep: int) -> dict:
    """新剧本 run 目录（data/pipeline/runs/<id>/）→ brief / chain / script / import 四段状态"""
    S: dict[str, dict] = {}
    brief = run_dir / "P0_brief.json"
    S["brief"] = _st("done", detail=_rel(root, brief)) if brief.exists() else _st("todo", needs="owner", blocker="没有 P0 Brief",
                                                                                     cmd=f"{PY} tools/autopilot/run.py flow-start --brief <P0.json> --episode {ep}")
    nodes = {k: _report_ok(run_dir / v.format(ep=ep)) for k, v in WRITE_FILES.items()}
    ok = sum(1 for v in nodes.values() if v == "ok")
    bad = [k for k, v in nodes.items() if v not in (None, "ok", "dry_run")]
    st = (_jl(run_dir / "ui_state.json", {}) or {})
    S["chain"] = _st("done" if ok == 4 else ("blocked" if bad else ("running" if any(nodes.values()) or st.get("status") in ("queued", "running") else "waiting")),
                     ok, 4, "；".join(f"{k}:{v or '—'}" for k, v in nodes.items()),
                     blocker=f"{bad} 没过校验（返修 ≤2 轮后仍不过 → 交写作方）" if bad else None, needs="api_model" if bad else None,
                     cmd=None if ok == 4 else f"{PY} tools/pipeline/run_chain.py --brief {_rel(root, brief)} --episode {ep} --out {_rel(root, run_dir)}")
    af = _jl(run_dir / f"autoflow_ep{ep:02d}.json", {}) or {}       # HOLLYWOOD r8 每集状态
    hw = _jl(run_dir / "hollywood" / f"ep{ep:02d}.json")       # HOLLYWOOD r8 交付契约（见 docs/AUTOPILOT.md §0）
    if hw:
        pk = POL.pick_import(hw.get("candidates") or [], float(hw.get("spent_usd") or 0), int(hw.get("rounds_left") or 0), root)
        S["script"] = _st("done" if pk["pick"] else "running", detail=f"{pk['why']}（选 {pk['pick']}）", needs=None if pk["pick"] else "api_model")
        S["script"]["pick"] = pk
        cf = hw.get("code_fails")
        n_cf = len(cf) if isinstance(cf, (list, dict)) else int(cf or 0)     # r8 写整数或清单都认
        if n_cf:
            S["script"]["detail"] += f"；代码判定失败 {n_cf} 项（导入闸门要求 0）"
    elif af:
        S["script"] = _st("running", detail=f"autoflow：{af.get('verdict') or af.get('stage') or '进行中'}，已花 ${af.get('usd_total', 0)}")
    else:
        S["script"] = _st("todo" if ok == 4 else "waiting", detail="等 HOLLYWOOD r8 写 hollywood/epNN.json",
                          needs="claude" if ok == 4 else None,
                          blocker="HOLLYWOOD r8 全自动环未接（页面仍只跑 10-31 run_chain）" if ok == 4 else None)
    imp = [e for e in _jsonl(root / "data/autopilot/imports.jsonl") if run_dir.name in json.dumps(e, ensure_ascii=False)]
    S["import"] = _st("done", detail=f"导入事件 {len(imp)} 条") if imp else _st(
        "todo" if S["script"]["status"] == "done" else "waiting", needs="owner" if S["script"]["status"] == "done" else None,
        blocker="待导入：import-staged --run 已由 DEBUG-RSI 完成、随 sv-05 部署；导入后 WORKFLOW / FACTORY 加常驻 serve --run" if S["script"]["status"] == "done" else None,
        cmd=f"{PY} tools/autopilot/producer.py import-staged --obj <hollywood 选中稿> --reason <sha256>")
    return S


def _rel(root: Path, p: Path) -> str:
    try:
        return p.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(p)


def _jsonl(p: Path) -> list[dict]:
    out = []
    try:
        for ln in p.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(ln))
            except ValueError:
                pass
    except OSError:
        pass
    return out


def start(brief: Path, ep: int, run_id: str | None = None, root: Path = ROOT, dry: bool = False, launch: bool = True) -> dict:
    """页面 / 命令行启动一部新剧本的全流程：建 run 目录、登记到 runs.json；launch 时后台起写作链（dry = 只组装 prompt 不调模型）。
    之后每一段由各自的常驻 / 工具推进，flow 只现推状态（run.py status --all 里出现这部剧的写作段行）。"""
    run_id = run_id or f"flow_{time.strftime('%Y%m%d_%H%M%S')}_ep{ep:02d}"
    d = root / "data/pipeline/runs" / run_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "P0_brief.json").write_text(Path(brief).read_text(encoding="utf-8"), encoding="utf-8")
    idx_p = root / RUNS_INDEX
    idx = _jl(idx_p, {}) or {}
    rec = {"run_id": run_id, "episode": ep, "dir": _rel(root, d), "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "dry_run": dry}
    idx.setdefault("runs", {})[run_id] = rec
    idx_p.parent.mkdir(parents=True, exist_ok=True)
    _wj(idx_p, idx)
    if launch:
        budget = str(POL.get("budget.writing_episode_cap_usd", 3.0, root))
        cmd = [str(root / PY), "-X", "utf8", "tools/pipeline/run_chain.py", "--brief", str(d / "P0_brief.json"), "--episode", str(ep),
               "--out", str(d), "--budget-usd", budget, "--budget-tag", f"flow-{run_id}"] + (["--dry-run"] if dry else [])
        log = open(d / "flow_chain.log", "a", encoding="utf-8")
        if dry:
            r = subprocess.run(cmd, cwd=str(root), stdout=log, stderr=subprocess.STDOUT, timeout=900)
            rec["chain_rc"] = r.returncode
        else:
            subprocess.Popen(cmd, cwd=str(root), stdout=log, stderr=subprocess.STDOUT)
            rec["chain"] = "launched"
    return rec


def _run_episodes(d: Path) -> list[int]:
    """新 run 目录里出现过的集号（P2 / P3 / P4 / hollywood 产物）；一个都没有 = [1]（只有 Brief 时显示写作段）"""
    import re as _re
    eps = set()
    for pat in ("P2_ep*_outline.json", "P3_ep*_screenplay.json", "P4_ep*.md", "hollywood/ep*.json", "ep*/P4_ep*.md"):
        for f in d.glob(pat):
            m = _re.search(r"ep(\d+)", f.name)
            if m:
                eps.add(int(m.group(1)))
    return sorted(eps) or [1]


def runs_status(root: Path = ROOT) -> list[dict]:
    """非 primary 的 run：flow-start 登记表（data/autopilot/flow/runs.json）+ 多剧登记表（config/pipeline/runs.json，WORKFLOW）。
    每 (run, 集) 一行；没写集号的 run（例：HOLLYWOOD r8 直接建目录的整季 series10_s2）按目录里的产物找集号。"""
    idx = {k: dict(v) for k, v in ((_jl(root / RUNS_INDEX, {}) or {}).get("runs") or {}).items()}
    reg = _jl(root / "config/pipeline/runs.json", {}) or {}
    for rid, r in (reg.get("runs") or {}).items():
        if rid == reg.get("primary"):
            continue
        rec = idx.setdefault(rid, {"run_id": rid, "dir": f"data/pipeline/runs/{rid}"})
        rec.setdefault("dir", f"data/pipeline/runs/{rid}")
        rec.update({k: r[k] for k in ("priority", "status", "budget_usd") if k in r})
        if r.get("episode") and not rec.get("episode"):
            rec["episode"] = r["episode"]
    out = []
    for rid, rec in idx.items():
        d = root / rec["dir"]
        eps = [int(rec["episode"])] if rec.get("episode") else _run_episodes(d)
        cap = POL.run_writing_cap(rid, root)
        for ep in eps:
            S = writing_status(root, d, ep)
            cur = next((k for k in ("brief", "chain", "script", "import") if S[k]["status"] != "done"), "jobs")
            out.append({"run_id": rid, "episode": ep, "dry_run": rec.get("dry_run"), "priority": rec.get("priority", 10),
                        "budget_cap_usd": cap, "current": cur, "stages": S,
                        "blockers": [{"stage": k, "blocker": v["blocker"], "needs": v["needs"]} for k, v in S.items() if v.get("blocker")]})
    return out


def global_status(w: World) -> dict:
    g: dict = {"producer": {}, "handback": {}, "policy": {}}
    od = POL.pause_decision(w.ctrl)
    g["producer"] = {"paused": bool(w.ctrl.get("paused")), "paused_by": w.ctrl.get("paused_by"), "pause_overdue": od,
                     "counts": w.registry.get("counts"), "updated": w.registry.get("updated")}
    c = w.registry.get("counts") or {}
    phases = ((w.net.get("dispatch_mode") or {}).get("phases") or {})
    g["dispatch_phases"] = phases
    server_mode = bool(phases) and all(v == "server" for v in phases.values())
    if server_mode:
        g["producer"]["note"] = "派单在服务器（dispatch_mode 全 server）：笔记本登记表只反映并回的结果，在跑数看服务器心跳"
    elif c.get("ready") and not c.get("running") and not w.ctrl.get("paused"):
        g["producer"]["idle_with_work"] = f"{c.get('ready')} 个对象可派但 0 在跑（resources.gpu_idle_alert_s）"
    for h, rec in w.assets_ready.items():
        sv = POL.deployed_sv(h, w.root)                          # 该机最近一次 deploy 成功的版本（min_code_sv，K-OPS-X08）
        ok, why = POL.handback_ok(rec, server_sv=sv or "（无 deploy 记录）")
        g["handback"][h] = {"ok": ok, "why": why}
    dr = POL.drift_check(w.root)
    g["policy"] = {"drift_bad": [d["item"] for d in dr if not d["ok"]], "drift_checked": len(dr)}
    return g


def status_all(root: Path = ROOT, write: bool = True) -> dict:
    w = World(root, write=write)
    eps = sorted(set(w.imported()) | {int(e.get("ep")) for e in w.registry.get("episodes") or [] if e.get("ep") is not None})
    rows = [episode_status(w, ep) for ep in eps]
    g = global_status(w)
    blockers = [dict(b, ep=r["ep"]) for r in rows for b in r["blockers"]]
    inc = sum(len(r["stages"]["image_gate"].get("inconsistent") or []) for r in rows)
    if inc:
        blockers.append({"ep": None, "stage": "image_gate", "needs": "code",
                         "blocker": f"producer 登记表自相矛盾 {inc} 处（passed 但无当前版 / 尾帧过而首帧未过）→ DEBUG-RSI"})
    if g["producer"].get("pause_overdue"):
        blockers.insert(0, {"ep": None, "stage": "first", "blocker": f"producer 暂停超时 {g['producer']['pause_overdue']}", "needs": "code"})
    if g["producer"].get("idle_with_work"):
        blockers.insert(0, {"ep": None, "stage": "first", "blocker": g["producer"]["idle_with_work"], "needs": "code"})
    for h, v in g["handback"].items():
        if not v["ok"]:
            blockers.append({"ep": None, "stage": "first", "blocker": f"{h} 不可交还：{'；'.join(v['why'])}", "needs": "code"})
    new_runs = runs_status(root)
    for r in new_runs:
        if not r.get("dry_run"):          # 演练 run 只列状态，不进卡点
            blockers += [dict(b, ep=None, run=f"{r['run_id']} ep{int(r['episode']):02d}") for b in r["blockers"]]
    out = {"schema": "nsfs.autopilot.flow/1", "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "stages": STAGE_IDS, "new_runs": new_runs,
           "stage_names": {s["id"]: s["name"] for s in STAGES}, "episodes": rows, "global": g, "blockers": blockers}
    if write:
        p = root / "data/autopilot/flow/status.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        _wj(p, out)
    return out


MARK = {"done": "✅", "running": "▶", "todo": "○", "waiting": "·", "blocked": "⛔", "stale": "↺"}


def render_all(st: dict) -> str:
    head = "集  " + " ".join(f"{s[:6]:>6}" for s in st["stages"]) + "  当前"
    lines = [head]
    for r in st["episodes"]:
        cells = []
        for k in st["stages"]:
            v = r["stages"][k]
            frac = f"{v['done']}/{v['total']}" if v.get("total") else ""
            cells.append(f"{MARK.get(v['status'], '?') + frac:>6}")
        lines.append(f"ep{r['ep']:02d} " + " ".join(cells) + f"  {st['stage_names'].get(r['current'], '完成')}")
    g = st["global"]
    if g.get("dispatch_phases"):
        lines.append(f"\n派单阶段：{g['dispatch_phases']}" + (f"（{g['producer']['note']}）" if g['producer'].get('note') else ""))
    lines.append(f"producer：{'暂停 ' + str(g['producer']['paused_by']) if g['producer']['paused'] else '运行'}；计数 {g['producer'].get('counts')}")
    for h, v in g["handback"].items():
        lines.append(f"交还 {h}：{'可' if v['ok'] else '不可 — ' + '；'.join(v['why'])}")
    lines.append(f"策略漂移：{g['policy']['drift_bad'] or '无'}（比对 {g['policy']['drift_checked']} 项）")
    for r in st.get("new_runs") or []:
        lines.append(f"新剧本 {r['run_id']}（ep{int(r['episode']):02d}{'，演练' if r.get('dry_run') else ''}）：" + " ".join(f"{k}{MARK.get(v['status'], '?')}" for k, v in r["stages"].items())
                     + f"  当前 {r['current']}")
    lines.append(f"\n卡点 {len(st['blockers'])} 个：")
    for b in st["blockers"][:30]:
        lines.append(f"  - {'ep%02d' % b['ep'] if b.get('ep') else (b.get('run') or '全局')} {b['stage']}：{b['blocker']}（需要 {b['needs']}）")
    return "\n".join(lines)


def render_ep(r: dict) -> str:
    lines = [f"ep{r['ep']:02d} {r.get('title') or ''}（{r['shots']} 镜）当前：{r['current']}"]
    for s in STAGES:
        v = r["stages"][s["id"]]
        deciders = "/".join(sorted({now_of(p) for p in s["points"]}))
        lines.append(f"  {MARK.get(v['status'], '?')} {s['name']:<8} [{deciders}] {v['detail']}" + (f"\n      下一步：{v['cmd']}" if v.get("cmd") else "")
                     + (f"\n      卡点：{v['blocker']}" if v.get("blocker") else ""))
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------- 冷启动演练
def _grep(root: Path, rel: str, pat: str) -> bool:
    try:
        return bool(re.search(pat, (root / rel).read_text(encoding="utf-8")))
    except OSError:
        return False


def structural_breaks(root: Path = ROOT) -> list[dict]:
    """新剧本（不是 series10_v1、不经 HOLLYWOOD）要跑通时，代码里写死的断点。全部静态检查，不碰生产。"""
    out = []
    if _grep(root, "tools/autopilot/producer.py", r'^RUN_ID = "series10_v1"'):
        out.append({"stage": "first", "kind": "hardcode", "where": "tools/autopilot/producer.py RUN_ID", "who": "DEBUG-RSI（已派：改读 config/pipeline/run.json）",
                    "what": "producer 写死 run=series10_v1（eps_out / music / review 也写死 series10）", "needs": "claude",
                    "fix": "RUN_ID 改读 control.json run（DEFAULT_CTRL 已有 run 字段）或 NS_RUN 环境变量；路径由 Paths(run_id) 派生"})
    if _grep(root, "tools/autopilot/episode_pipeline.py", r'RUN = ROOT / "data/pipeline/runs/series10_v1"'):
        out.append({"stage": "jobs", "kind": "hardcode", "where": "tools/autopilot/episode_pipeline.py RUN", "who": "WORKFLOW",
                    "what": "逐集流水线写死 series10_v1", "needs": "claude", "fix": "同上，读 run 参数"})
    if not _grep(root, "tools/autopilot/episode_pipeline.py", r"imports\.jsonl"):
        out.append({"stage": "jobs", "kind": "trigger", "where": "tools/autopilot/episode_pipeline.py imported_eps", "who": "WORKFLOW",
                    "what": "新集只靠 CHANGELOG 里“HOLLYWOOD 导入 epNN”这行字发现；不经 HOLLYWOOD 的导入不会被准备", "needs": "claude",
                    "fix": "改看 data/import/script_v2.json 的集 sha 变化（ep_hash 已有），CHANGELOG 只作补充"})
    if _grep(root, "services/api/ns_api/script_inbox.py", r"PRODUCER_BY"):
        out.append({"stage": "import", "kind": "permission", "where": "services/api/ns_api/script_inbox.py", "who": "DEBUG-RSI + UIRSI",
                    "what": "导入接口只收 by=owner 或 PRODUCER 令牌；Claude 会话执行时被权限系统拦（11-01 23:1x 由项目方本人导入）", "needs": "owner",
                    "fix": "无人值守时编排器以 PRODUCER 身份调 import-staged（项目方方案 A 已授权）；Claude 驱动时仍交项目方"})
    return out


def writing_breaks(root: Path = ROOT) -> list[dict]:
    """从 P0 Brief 开始的新剧本，写作 → 导入这一段代码里的断点（静态检查）"""
    out = []
    if _grep(root, "services/api/ns_api/story_runs.py", r"import run_chain") and not _grep(root, "services/api/ns_api/story_runs.py", r"autoflow|hollywood"):
        out.append({"stage": "script", "kind": "not_wired", "where": "services/api/ns_api/story_runs.py",
                    "what": "页面 #/script-create 仍只跑 10-31 的 run_chain；HOLLYWOOD r8（tools/script_rsi/autoflow.py）已能全自动，但页面没接", "needs": "claude",
                    "who": "UIRSI（页面“全流程自动”入口调 run.py flow-start 或 autoflow.py）",
                    "fix": "页面新建后调 autoflow.py run --run-dir <run> --episode N --import dry|live；进度读 status.json 的 new_runs"})
    if _grep(root, "services/api/ns_api/story_runs.py", r"导入仍要你在导入页勾选确认"):
        out.append({"stage": "import", "kind": "owner_click", "where": "services/api/ns_api/story_runs.py send_to_import",
                    "what": "“送去导入”只存草稿，导入还要项目方在导入页勾选", "needs": "owner",
                    "who": "UIRSI（页面）+ DEBUG-RSI（producer.import_staged 写 imports.jsonl）",
                    "fix": "policy.pick_import 选中且 P4 阻断 0 → 走 PRODUCER 通道自动导入（项目方方案 A 已授权），页面只显示可撤销"})
    if not _grep(root, "tools/autopilot/producer.py", r"import-staged[^\n]*--run|\"--run\""):
        out.append({"stage": "import", "kind": "import_run", "where": "tools/autopilot/producer.py import_staged",
                    "what": "import-staged 只会 merge 进主导入稿 data/import/script_v2.json，非 primary run 导不进 data/import/runs/<run>/script_v2.json（第二季只能 dry）", "needs": "claude",
                    "who": "DEBUG-RSI（producer.import_staged 加 --run，按 runs.import_path(run) 写）",
                    "fix": "import-staged --run <run>：写 runs.import_path(run)、备份按 run、imports.jsonl 带 run_id；primary 行为不变"})
    if not (root / "config/pipeline/runs.json").exists():
        out.append({"stage": "import", "kind": "multi_run", "where": "config/pipeline/runs.json（不存在）；producer / episode_pipeline / 服务器工厂",
                    "what": "多剧并行接口未落地：现在只有一个 run_id，新剧本导入无处安放（总调度 02:4x 定：新增 run、不替换 series10）", "needs": "claude",
                    "who": "WORKFLOW（runs.json + episode_pipeline 按 run）+ DEBUG-RSI（producer 多 run + 优先级）+ FACTORY（服务器按 run_id）",
                    "fix": "按 docs/AUTOPILOT.md §0.1 接口落地"})
    if not (root / "tools/script_rsi/autoflow.py").exists() and not _grep(root, "tools/script_rsi/hollywood_r5.py", r"--run-dir"):
        out.append({"stage": "script", "kind": "no_entry", "where": "tools/script_rsi/hollywood_r5.py",
                    "what": "好莱坞返修环只认 series10 的 r4 选中版做基线（R4_ROOT），不能吃新 run 目录的 P4", "needs": "claude",
                    "who": "HOLLYWOOD r8", "fix": "入口加 --run-dir <data/pipeline/runs/id> --episode N，读 P4、写 hollywood/epNN.json"})
    return out


def drill(ep: int, root: Path = ROOT, run_producer_dryrun: bool = False, write: bool = True, brief: Path | None = None) -> dict:
    """冷启动演练（r2 起从 P0 Brief 开始）：用样例 Brief 起一部新剧本——写作链 dry-run（只组装 prompt、不调付费 API），
    再逐段列出判断点（decider）、会停下的地方和负责方；生产段不出图（可选跑 producer 零点击 dryrun）。"""
    steps = []
    breaks = []
    w = World(root)
    live = None
    chain_run = None
    if brief is not None:
        chain_run = start(Path(brief), ep, run_id=f"drill_brief_ep{ep:02d}", root=root, dry=True, launch=(root / "tools/pipeline/run_chain.py").exists())
        ws = writing_status(root, root / chain_run["dir"], ep)
        import re as _re
        lg = (root / chain_run["dir"] / "flow_chain.log")
        txt = lg.read_text(encoding="utf-8", errors="replace") if lg.exists() else ""
        chain_run["dry_links"] = dict(zip(_re.findall(r'"link": "([^"]+)"', txt), _re.findall(r'"status": "([^"]+)"', txt)))
        chain_run["note"] = ("写作链 dry-run 只能组装第一段 prompt（后续段要上一段的产物）；全链无花费冒烟需要 mock 写作模型"
                             "（run.py start --from P0 --dry-run 的 MockWriter 路径），P1–P4 的校验器已由 run_chain 测试覆盖")
        if chain_run["dry_links"]:
            ws["chain"]["detail"] = f"dry-run：{chain_run['dry_links']}"
        live = {"stages": ws}
    for s in STAGES:
        pts = []
        for p in s["points"]:
            dn = now_of(p, root=root)
            pts.append({"what": p["what"], "decider": dn, "target": p["target"], "ref": p["ref"]})
            if dn in ("claude", "owner"):
                breaks.append({"stage": s["id"], "what": p["what"], "needs": dn, "target": p["target"], "ref": p["ref"],
                               "who": p.get("who", ""),
                               "fix": p.get("plan") or ("项目方保留闸门（L-098 委托范围外）" if p["now"] == "owner" else "")})
        steps.append({"stage": s["id"], "name": s["name"], "executor": s["exec"], "auto": s["auto"], "points": pts,
                      "live_status": (live or {}).get("stages", {}).get(s["id"], {}).get("status") if live else None})
    sb = (writing_breaks(root) if brief is not None else []) + structural_breaks(root)
    breaks += [dict(b, target=b.get("target", "owner" if b.get("kind") == "single_run" else "code")) for b in sb]
    pd = None
    if run_producer_dryrun:
        r = subprocess.run([str(root / PY), "-X", "utf8", "tools/autopilot/producer.py", "dryrun"], cwd=str(root),
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
        pd = {"rc": r.returncode, "tail": (r.stdout or r.stderr)[-800:]}
        fin = (_jl(root / "data/producer/dryrun.json", {}) or {}).get("final") or {}
        pd["final"] = {sid: {k: (v or {}).get("status") for k, v in o.items()} for sid, o in fin.items()}
        stuck = {sid: o for sid, o in pd["final"].items() if o.get("video") != "passed"}
        if r.returncode or stuck:
            why = "；".join(f"{sid} {o}" for sid, o in stuck.items())
            reason = next((str((v or {}).get("reason")) for o in fin.values() for v in o.values() if (v or {}).get("reason")), "")
            breaks.append({"stage": "first", "what": f"producer 零点击 dryrun 没走完首帧→尾帧→视频（rc={r.returncode}；{why}）",
                           "needs": "claude", "target": "code", "ref": "tools/autopilot/producer.py dryrun（PRODUCER，经总调度派）",
                           "who": "DEBUG-RSI（已派）",
                           "fix": f"末状态原因：{reason[:160]}；dryrun 要以“视频 passed”为成功条件，否则退出码非 0"})
    out = {"schema": "nsfs.autopilot.drill/1", "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "episode": ep, "mode": "dry-run（不出图、不调付费 API）",
           "from": "P0 Brief" if brief is not None else "import", "writing_run": chain_run,
           "steps": steps, "breakpoints": breaks, "producer_dryrun": pd,
           "by_who": dict(Counter((b.get("who") or "?").split("（")[0] for b in breaks)),
           "summary": dict(Counter(b["needs"] for b in breaks))}
    if write:
        p = root / f"data/autopilot/flow/drill_ep{ep:02d}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        _wj(p, out)
    return out


# ---------------------------------------------------------------------------------------------- 覆盖率
def coverage(root: Path = ROOT, drill_ep: int | None = None, write: bool = True) -> dict:
    import yaml
    pts = [dict(p, stage=s["id"]) for s in STAGES for p in s["points"]] + [dict(p, stage="ops") for p in OPS_POINTS]
    backend = writer_backend(root)
    now = Counter(now_of(p, backend) for p in pts)               # 测试期实际值（L-109：writer 点 = claude_testphase）
    launch = Counter(now_of(p, "api") for p in pts)              # 上线配置值（writer_backend=api）——L-102 目标看这个
    tgt = Counter(p["target"] for p in pts)
    per_stage = {}
    for s in STAGES + [{"id": "ops", "points": OPS_POINTS}]:
        c = Counter(now_of(p, backend) for p in s["points"])
        per_stage[s["id"]] = {"points": len(s["points"]), "now": dict(c),
                              "stage_decider": "claude" if c.get("claude") else ("owner" if c.get("owner") else
                                                ("api_model" if c.get("api_model") else ("local_model" if c.get("local_model") else "code")))}
    dec = (yaml.safe_load((root / POL.DECISIONS).read_text(encoding="utf-8")) or {}).get("decisions") or []
    dcoded = Counter(d.get("coded") for d in dec)
    pol = POL.load(root)
    pst = Counter(it.get("status") for items in pol.values() for it in items.values())
    claude_pts = [dict(stage=p["stage"], what=p["what"], ref=p["ref"], plan=p.get("plan", ""), who=p.get("who", "")) for p in pts if now_of(p, backend) == "claude"]
    dr = None
    dp = root / f"data/autopilot/flow/drill_ep{drill_ep:02d}.json" if drill_ep else None
    if dp and dp.exists():
        dr = _jl(dp)
    # r3：第二季等真实新 run 就是冷启动演练的实战——沿途每个需要人 / Claude / 写作方的点都记进来
    live = []
    for r in runs_status(root):
        if r.get("dry_run"):
            continue
        for b in r["blockers"]:
            live.append({"run": r["run_id"], "episode": r["episode"], "stage": b["stage"], "needs": b["needs"], "what": b["blocker"],
                         "testphase": b["stage"] in ("chain", "script") and backend == "claude_agent"})
    log_p = root / "data/autopilot/flow/live_breaks.jsonl"
    seen = set()
    for x in _jsonl(log_p):
        seen.add((x.get("run"), x.get("episode"), x.get("stage"), x.get("what")))
    new_live = [x for x in live if (x["run"], x["episode"], x["stage"], x["what"]) not in seen]
    if write and new_live:
        log_p.parent.mkdir(parents=True, exist_ok=True)
        with open(log_p, "a", encoding="utf-8") as f:
            for x in new_live:
                f.write(json.dumps(dict(x, first_seen=time.strftime("%Y-%m-%dT%H:%M:%S")), ensure_ascii=False) + "\n")
    out = {"schema": "nsfs.autopilot.coverage/1", "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "round": "distill-r3",
           "live_runs": {"now": live, "history_file": "data/autopilot/flow/live_breaks.jsonl",
                         "history": len(seen) + len(new_live)},
           "goal": "新剧本从剧本导入到成片，decider 里没有 claude（L-102 / §G1-2）",
           "decision_points": len(pts), "writer_backend": backend,
           "deciders_now": dict(now), "deciders_now_testphase": dict(now), "deciders_now_launch": dict(launch), "deciders_target": dict(tgt),
           "claude_share_now": round(now.get("claude", 0) / len(pts), 3), "claude_share_launch": round(launch.get("claude", 0) / len(pts), 3),
           "claude_testphase_points": now.get(TESTPHASE, 0),
           "testphase_note": "L-109 测试期：剧本写 / 评由 Claude agent 执行（项目方为省钱明确选择，不算回退），上线 writer_backend=api 后这些点即 api_model；L-102 目标看 claude_share_launch",
           "claude_share_target": round(tgt.get("claude", 0) / len(pts), 3),
           "per_stage": per_stage, "claude_points": claude_pts,
           "decisions_inventory": {"total": len(dec), "coded": dict(dcoded),
                                   "coded_ratio": round(dcoded.get("yes", 0) / len(dec), 3) if dec else None,
                                   "decider_now": dict(Counter(d.get("decider_now") for d in dec))},
           "policies": {"files": len(pol), "items": sum(len(v) for v in pol.values()), "status": dict(pst)},
           "cold_start_breakpoints": (dr or {}).get("breakpoints"), "cold_start_episode": drill_ep}
    if write:
        p = root / "data/autopilot/coverage.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        _wj(p, out)
    return out


# ---------------------------------------------------------------------------------------------- guard / 交付
def guard(root: Path = ROOT, apply: bool = False) -> dict:
    """策略守卫（resources.pause_max_s，D5 口径；判定 = policy.pause_decision 唯一实现）：alert 写报警；resume 且 --apply 才恢复
    （经 producer.set_paused，审计 by=POLICY_GUARD）。producer 每拍由 DEBUG-RSI 接同一个函数。"""
    ctrl = _jl(root / "data/producer/control.json", {}) or {}
    dec = POL.pause_decision(ctrl)
    res = {"decision": dec, "applied": False}
    if dec:
        alert = {"t": time.time(), "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "code": "A-PAUSE-OVERDUE", "by": "DISTILL policy guard",
                 "rule": "K-OPS-X03 / resources.pause_max_s", "detail": dec}
        ap = root / "data/qa/alerts.jsonl"
        ap.parent.mkdir(parents=True, exist_ok=True)
        with open(ap, "a", encoding="utf-8") as f:
            f.write(json.dumps(alert, ensure_ascii=False) + "\n")
        if apply and dec["action"] == "resume":
            sys.path.insert(0, str(HERE))
            import producer as PR
            PR.set_paused(PR.Paths(root), False, by="POLICY_GUARD", note=f"运维暂停到点自动恢复（{dec['why']}，K-OPS-X03）")
            res["applied"] = True
    return res


def approve_delivery(ep: int, by: str = "owner", note: str = "", root: Path = ROOT) -> Path:
    p = root / f"data/autopilot/flow/gates/ep{ep:02d}_delivery.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    _wj(p, {"approved": True, "by": by, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "note": note}, indent=None)
    return p


# ---------------------------------------------------------------------------------------------- 每拍（run.py tick）
def autoflow_due(root: Path = ROOT) -> list[dict]:
    """HOLLYWOOD autoflow 的“交稿即推进”（总调度 11-02，decider=code）：每个 run 的 writer_tasks/*.json，每集取 _a<k> 最大（同 k 取最新）
    的包，done_marker 已存在 → 该推进；或 writer_out/P4_epNN_{r,a}<k>.md.done 不在 autoflow_epNN.json agent.full_p4_done 里 → 该推进"""
    import re as _re
    due = []
    for d in sorted((root / "data/pipeline/runs").glob("*/writer_tasks")):
        run_dir = d.parent
        best: dict[int, tuple] = {}
        for f in d.glob("*.json"):
            pk = _jl(f, {}) or {}
            ep = pk.get("episode")
            m = _re.search(r"_a(\d+)\.json$", f.name)
            if ep is None or not m:
                continue
            key = (int(m.group(1)), f.stat().st_mtime)
            if int(ep) not in best or key > best[int(ep)][0]:
                best[int(ep)] = (key, f, pk)
        for ep, (_, f, pk) in best.items():
            mk = (pk.get("output") or {}).get("done_marker")
            if mk and (root / mk).exists():
                due.append({"run": run_dir.name, "episode": ep, "package": f.name, "marker": mk, "cmd": None,
                            "sig": f"{f.name}@{(root / mk).stat().st_mtime:.0f}"})
        for f in (run_dir / "writer_out").glob("P4_ep*_*.md.done") if (run_dir / "writer_out").exists() else []:
            m = _re.match(r"P4_ep(\d+)_[ra]\d+\.md\.done$", f.name)
            if not m:
                continue
            ep = int(m.group(1))
            done = ((_jl(run_dir / f"autoflow_ep{ep:02d}.json", {}) or {}).get("agent") or {}).get("full_p4_done") or []
            name = f.name[: -len(".done")]
            if name not in done and not any(x["run"] == run_dir.name and x["episode"] == ep for x in due):
                due.append({"run": run_dir.name, "episode": ep, "package": name, "marker": _rel(root, f),
                            "cmd": None,
                            "sig": f"{name}@{f.stat().st_mtime:.0f}"})
    return due


def autoflow_tick(root: Path = ROOT, apply: bool = True, timeout_s: int = 120) -> dict:
    """（已停用推进，总调度 11-02 W-23 / 根因模式 1 双入口）写作链只留一个推进入口：tools/script_rsi/autoflow.py（网页 /repair、.done 守护 watch），
    每次推进记 <run>/autoflow.log（source cli / web / daemon）。这里只报告“哪些集交了稿在等推进”，不再执行任何推进命令。
    19:17:06 事故：本函数看到 .done 就执行写作包里的 advance_cmd，越过了 P1 闸门出了 P2 包。"""
    due = autoflow_due(root)
    return {"ok": True, "ran": [], "due": due, "note": "推进统一由 autoflow.py watch / 网页 /repair 负责；autoflow_tick 只报告"}


def _autoflow_tick_retired(root: Path = ROOT, apply: bool = True, timeout_s: int = 120) -> dict:
    """旧实现（留档不调用）：按集串行推进；同一个包 + 交稿时刻只推一次；每集 work_epNN/flow_tick.lock 防并发"""
    memo_p = root / "data/autopilot/flow/autoflow_tick.json"
    memo = _jl(memo_p, {}) or {}
    ran = []
    for x in autoflow_due(root):
        k = f"{x['run']}/ep{x['episode']:02d}"
        if memo.get(k) == x["sig"] or not x.get("cmd"):
            continue
        lock = root / "data/pipeline/runs" / x["run"] / f"work_ep{x['episode']:02d}" / "flow_tick.lock"
        if lock.exists() and time.time() - lock.stat().st_mtime < timeout_s * 2:
            ran.append(dict(x, skipped="locked"))
            continue
        if not apply:
            ran.append(dict(x, dry=True))
            continue
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text(time.strftime("%Y-%m-%dT%H:%M:%S"), encoding="utf-8")
        try:
            argv = x["cmd"].split()
            if argv and argv[0].endswith("python.exe"):
                argv[0] = str(root / argv[0]) if not Path(argv[0]).is_absolute() else argv[0]
            r = subprocess.run(argv, cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout_s)
            ran.append(dict(x, rc=r.returncode, tail=(r.stdout or r.stderr)[-300:]))
            if r.returncode == 0:
                memo[k] = x["sig"]
        except subprocess.TimeoutExpired:
            ran.append(dict(x, rc=None, error=f"超时 {timeout_s} s"))
        finally:
            lock.unlink(missing_ok=True)
    if apply:
        memo_p.parent.mkdir(parents=True, exist_ok=True)
        _wj(memo_p, memo)
    return {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "ran": ran, "backend": writer_backend(root)}


def line3_tick(root: Path = ROOT, apply: bool = True, timeout_s: int = 600) -> dict:
    """写手交稿 / 过导入闸门后自动打线 3（剧本）分（HOLLYWOOD，总调度 11-02，decider=code，不调外部 API）：
    data/pipeline/runs/<run>/line3_dirty.json 存在 → 执行其中 cmd（line3_score.py，往 data/rsi/scores.jsonl 追加 line=script）；
    退出码 0 才删 dirty 文件，失败保留、下一拍重试。放在本拍所有推进之后串行跑。"""
    ran = []
    for f in sorted((root / "data/pipeline/runs").glob("*/line3_dirty.json")):
        d = _jl(f, None)
        if not isinstance(d, dict) or not d.get("cmd"):
            ran.append({"run": f.parent.name, "error": "line3_dirty.json 坏了或没有 cmd（保留，等 HOLLYWOOD 修）"})
            continue
        rec = {"run": f.parent.name, "episodes": sorted((d.get("episodes") or {}).keys())}
        if not apply:
            ran.append(dict(rec, dry=True))
            continue
        argv = str(d["cmd"]).split()
        if argv and argv[0].endswith("python.exe") and not Path(argv[0]).is_absolute():
            argv[0] = str(root / argv[0])
        try:
            r = subprocess.run(argv, cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout_s)
            rec.update(rc=r.returncode, tail=(r.stdout or r.stderr)[-300:])
            if r.returncode == 0:
                f.unlink(missing_ok=True)
        except subprocess.TimeoutExpired:
            rec.update(rc=None, error=f"超时 {timeout_s} s（保留，下一拍重试）")
        ran.append(rec)
    return {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "ran": ran}


def api_restart_tick(root: Path = ROOT, dry: bool = False, timeout_s: int = 360) -> dict:
    """UIRSI 的 :8800 空闲才重启守护（tools/uirsi/api_restart_guard.py tick；接 WORKFLOW 重启队列，decider=code）——子进程跑，慢也不拖住状态刷新"""
    g = root / "tools/uirsi/api_restart_guard.py"
    if not g.exists():
        return {"status": "未交付", "why": "tools/uirsi/api_restart_guard.py 不存在"}
    try:
        r = subprocess.run([str(root / PY), "-X", "utf8", str(g), "tick"] + (["--dry"] if dry else []), cwd=str(root),
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return {"status": "超时", "why": f"{timeout_s} s"}
    out = (r.stdout or "").strip()
    try:
        res = json.loads(out[out.index("{"):]) if "{" in out else None      # 守护把整段 JSON 打到 stdout（可能多行）
        return {"status": "ok" if r.returncode == 0 else f"rc={r.returncode}", "result": res}
    except ValueError:
        return {"status": f"rc={r.returncode}", "tail": (r.stdout or r.stderr or "")[-300:]}


PART_FILES = {"line3": "data/autopilot/flow/line3_tick.json", "api": "data/autopilot/flow/api_restart_tick.json"}


def _merge_parts(root: Path, st: dict) -> None:
    """把 line3 / api 两条线最近一次的结果并进 status.global（线还没跑完第一次 = pending）"""
    l3 = _jl(root / PART_FILES["line3"], {}) or {}
    api = _jl(root / PART_FILES["api"], {}) or {}
    st["global"]["line3_tick"] = l3.get("result") or {"ran": [], "note": "line3 线还没跑完第一次"}
    st["global"]["line3_tick_at"] = l3.get("at")
    st["global"]["api_restart"] = api.get("result") or {"status": "pending", "note": ":8800 守护线还没跑完第一次"}
    st["global"]["api_restart_at"] = api.get("at")


def tick_part(part: str, root: Path = ROOT, apply: bool = True, mode: str = "parts") -> dict:
    """编排器每拍的三条线（唯一实现；WORKFLOW 04:2x 拆线：:8800 守护慢时不拖住 status / last_tick）：
      core   status_all + coverage + 写作交稿即推进（autoflow_tick）→ 并入另两条线最近结果 → 写 status.json + last_tick.json
      line3  line3_tick → data/autopilot/flow/line3_tick.json
      api    api_restart_tick → data/autopilot/flow/api_restart_tick.json
    resident_sync 每条线一个线程、互不等待（tools/autopilot/tick_parts.py 只转调本函数）。"""
    if part in PART_FILES:
        r = line3_tick(root, apply=apply) if part == "line3" else api_restart_tick(root, dry=not apply)
        _wj(root / PART_FILES[part], {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "t": time.time(), "dry": not apply, "result": r})
        return {"part": part, "ran": len(r.get("ran") or []) if part == "line3" else None, "status": r.get("status")}
    if part != "core":
        raise ValueError(f"未知的线：{part}（core / line3 / api）")
    st = status_all(root, write=True)
    coverage(root, write=True)
    af = autoflow_tick(root, apply=apply)
    st["global"]["autoflow_tick"] = af
    _merge_parts(root, st)
    # SENTINEL 探针读 last_tick.json：超过 5 分钟没有真跑（dry=false）的 core 线就开工单
    st["global"]["last_tick"] = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "t": time.time(), "dry": not apply,
                                 "pid": __import__("os").getpid(), "mode": mode}
    if apply:
        _wj(root / "data/autopilot/flow/last_tick.json", st["global"]["last_tick"])
    _wj(root / "data/autopilot/flow/status.json", st)
    return {"part": "core", "at": st["at"], "blockers": len(st["blockers"]), "autoflow": len(af["ran"])}


def tick(root: Path = ROOT, apply: bool = True) -> dict:
    """整拍串行（手动 / 备用；常驻用 tick_part 三线并行）：core → line3 → api → 再把两线结果并进 status"""
    c = tick_part("core", root, apply, mode="serial")
    l3 = tick_part("line3", root, apply)
    api = tick_part("api", root, apply)
    st = _jl(root / "data/autopilot/flow/status.json", {}) or {}
    if st.get("global") is not None:
        _merge_parts(root, st)
        _wj(root / "data/autopilot/flow/status.json", st)
    return {"at": c["at"], "blockers": c["blockers"], "autoflow": c["autoflow"], "line3": l3["ran"], "api_restart": api["status"]}
