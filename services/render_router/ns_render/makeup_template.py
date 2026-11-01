"""人物定妆照（资产定妆候选）系统取景模板（fredw-92/CHR，2026-10-31）。

夜间 ND 的定妆候选模板是英文取景句在前（“定妆照·正面肖像：head and shoulders … 85mm lens at f/8 …”），
人物文字排在一长段英文后面，且没有身份参考时 Image 2.1 Turbo 默认出了西方面孔。这里改为：
  1) 人物文字（角色锁 / 人物表原文，原样）放在提示词最前；
  2) 造型行原文其次；
  3) 有身份参考时，参考用途句（= ns_render.refs.ROLE_FACE）在人物文字之后；
  4) 取景句全部中文，保留原模板的摄影意图（景别、朝向、中灰无缝背景、均匀正面光、85mm / 50mm f/8、
     全脸 / 全身清晰、自然皮肤质感、无文字水印；三视图 = 正 / 侧 / 背并排）。
人物文字与造型文字由写作模型 / 项目方提供，这里只拼接，不改写、不判断。
"""
from __future__ import annotations

from ns_render.refs import ROLE_FACE

PLATE_BG = "背景为无缝纯中灰影棚背景，柔和均匀的正面布光，无道具。"

# view → (标签, 取景句, 宽, 高)
VIEWS: dict[str, tuple[str, str, int, int]] = {
    "front": ("正面肖像",
              "头肩近景，正面，正对镜头，头部端正，眼睛看向镜头，表情自然放松、双唇闭合。" + PLATE_BG +
              "85mm 镜头 f/8，整张脸清晰对焦，皮肤质感自然、可见毛孔。画面无文字、无水印。",
              768, 1344),
    "half": ("半身",
             "腰部以上半身，正面，肩膀放松，目光平和柔和。" + PLATE_BG +
             "50mm 镜头 f/8，皮肤质感自然，服装材质细节清晰。画面无文字、无水印。",
             768, 1344),
    "full": ("全身",
             "全身参考照，正面，面对镜头，从头到脚完整入画，站直，双臂自然放松、略离身体，双脚微微分开。" + PLATE_BG +
             "50mm 镜头 f/8，从头到脚全部清晰，皮肤质感自然。画面无文字、无水印。",
             768, 1344),
    "turn": ("三视",
             "角色三视图：同一个人在同一张图里并排出现三次，每次都是从头到脚的全身，站直，双臂自然放松——"
             "左：正面，面对镜头；中：侧面，身体朝向画面左边缘；右：背面，背对镜头。三个视图服装完全相同。" + PLATE_BG +
             "50mm 镜头 f/8，从头到脚全部清晰。画面无文字、无标签、无水印。",
             1344, 768),
}


def makeup_prompt(person: str, look: str, view: str, name: str = "", ref_index: int | None = None) -> str:
    """定妆照提示词：人物文字（原样）→ 造型（原样）→ [身份参考用途句] → 定妆照·取景（中文系统模板）。
    person / look 由调用方从角色锁、人物表、造型行原文取来，这里只去掉首尾空白和句末标点再拼句号。"""
    if view not in VIEWS:
        raise ValueError(f"view 只能是 {list(VIEWS)}")
    lab, frame, _w, _h = VIEWS[view]
    person = (person or "").strip().rstrip("。；;，, ")
    if not person:
        raise ValueError("人物文字不能为空（取自角色锁 / 人物表原文）")
    parts = [f"人物：{person}。"]
    look = (look or "").strip().rstrip("。；;，, ")
    if look:
        parts.append(f"造型：{look}。")
    if ref_index is not None:
        parts.append(ROLE_FACE.format(i=ref_index, name=name or "人物"))
    parts.append(f"定妆照·{lab}：{frame}")
    return "".join(parts)


def view_size(view: str) -> tuple[int, int]:
    _lab, _frame, w, h = VIEWS[view]
    return w, h
