"""DATAALIGN 2026-11-01（UIPIXEL 报 P1）：唯一出图路径（unified_frame）出的版本一出来就被标“剧本已改 / 过期·需重出”。

根因：过期判定（app._stale_split）拿版本里记的提示词去和**旧编译器**的 image_prompt（_compile_for_display）比，
对不上再用“剧本 img 前 12 字在不在提示词里”兜底。unified_frame 的提示词是 ns_agent.frame_job.build_first 拼的：
asset_refs 槽位标注 + compile_shot（角色锁去服装 K-AST-232、retrigger、S★ 后缀、framing_project）——和旧编译器输出
不同，剧本句首“林晚坐在转椅上”也被景别过滤掉，两种比较都必然失败 → 每个新版本都判“剧本已改”。

修法：版本是 unified 路径出的（workflow = frame_v9_unified），比较基准换成**同一条路径现在会拼出的正文**
（frame_job.compile_frame 去掉 asset_refs 槽位前缀那部分；槽位前缀随参考图变化，由造型 / 输入签名另判）。
正文对得上 = 没过期；对不上再按 inputs_sha 区分“本镜输入已改”（local）与“编译器升级”（global），不再用前 12 字猜。
只读：不改版本记录、不出图。
"""
from __future__ import annotations

UNIFIED_WORKFLOWS = ("frame_v9_unified",)


UNIFIED_RECIPES = ("frame_v9",)


def is_unified(take: dict) -> bool:
    """unified 路径出的版本：画布 unified_frame（workflow），或 ASSETMASTER frames_v2 / 出图线登记进来的 frame_v9 版本
    （workflow=series_pipeline，params.origin.recipe=frame_v9；同一个 frame_job 拼的提示词，总调度 11-01 PW 第 2 条）"""
    if take.get("workflow") in UNIFIED_WORKFLOWS or str(take.get("path") or "").startswith("unified_frame"):
        return True
    origin = ((take.get("params") or {}).get("origin") or {}) if isinstance(take.get("params"), dict) else {}
    return isinstance(origin, dict) and origin.get("recipe") in UNIFIED_RECIPES


_BODY_CACHE: dict = {}
_BODY_TTL_S = 10.0


def unified_bodies(script, ep, shot) -> dict[str, str] | None:
    """带短缓存（10 s，按剧本对象 + 镜号）：/api/shots/{id} 每个 unified 版本都要比一次，同一镜同一请求内重复编译
    曾占该接口一半时间（UIAUDIT r14g 首屏慢）；配置改了最多晚 10 s 生效（按镜缓存另有签名兜底）"""
    import time as _t
    k = (id(script), getattr(shot, "id", None))
    hit = _BODY_CACHE.get(k)
    if hit and _t.time() - hit[0] < _BODY_TTL_S:
        return hit[1]
    v = _unified_bodies(script, ep, shot)
    if len(_BODY_CACHE) > 512:
        _BODY_CACHE.clear()
    _BODY_CACHE[k] = (_t.time(), v)
    return v


def _unified_bodies(script, ep, shot) -> dict[str, str] | None:
    """unified 路径现在的正文：{"image": 首帧正文, "last": 尾帧 last_prompt}；剧本不属于登记了资产的项目 → None"""
    from ns_api.shot_cast import project_for
    project = project_for(script)
    if not project:
        return None
    from ns_agent import asset_refs as AR
    from ns_agent import compiler as C
    from ns_agent import frame_job as FJ
    from ns_agent.bible import load_bible
    from ns_agent.gen_contract import style as ST
    g = script.globals
    if AR.project_cfg(project):
        g, _removed = AR.locks_without_wardrobe(g)
    c = C.compile_shot(ep, FJ.retrigger(shot, g), g, set(), image_style=ST.image_suffix(), bible=load_bible(),
                       framing_project=project)
    return {"image": c.image_prompt, "last": c.last_prompt or ""}


def is_video10(take: dict) -> bool:
    """VIDEO10 出的片子（tools/pipeline/register_takes.py --video10 登记）：提示词由它自己的编译器拼（preflight I6），
    不和画布 H3 视图比；过期只看“由哪版首帧得到”（from_first）≠ 当前首帧"""
    origin = ((take.get("params") or {}).get("origin") or {}) if isinstance(take.get("params"), dict) else {}
    return take.get("stage") == "video" and (take.get("workflow") == "video10"
                                             or str((origin or {}).get("run") or "").endswith("/video"))


# asset_refs.plan_slots 的“参考槽不足、改走文字”说明（frame_job.with_note 插在正文末尾、风格后缀之前）。
# 说明随参考槽位规划变（要算参考图，太重），这里不重算槽位：从版本记的提示词里认出说明，
# 用同一个 with_note 把它放回现在的正文再比——正文其余部分仍须逐字相同（11-01 ep06-S7 #2 误报“编译器升级”）
from ns_agent.asset_refs import TEXT_NOTE_RES as _NOTE_RES  # noqa: E402  系统固定说明句的唯一来源（asset_refs，按拼接顺序）


def match_target(prompt: str, body: str) -> str:
    """unified 版本的比较基准：提示词里带槽位不足说明 → 现在正文 + 同样的说明（同一个 frame_job.with_note）"""
    if not body or prompt.endswith(body):
        return body
    from ns_agent import frame_job as FJ
    # PRODUCER 11-01（K-REN-101 外层单品说明，与 DATAALIGN 协调）：槽位不足说明在前、外层单品说明在后，与 compile_frame 拼的顺序一致
    notes = [n for rx in _NOTE_RES for n in rx.findall(prompt or "")]
    if not notes:
        return body
    return FJ.with_note(body, "".join(f"{n}。" for n in notes))
