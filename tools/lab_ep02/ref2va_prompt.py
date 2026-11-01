"""
LAB：Ref2VA 提示词生成器（官方 full-reference 六段格式：data/ab/owner_workflows/minimax_h3_official_skills/
h3-prompt-writing/references/ref-en.txt）。只做格式转换：正文全部取自剧本已有的英文 H3 字段
（compiled.json video_prompt 的 integrated_multimodal_description / overall_soundscape / non_diegetic_music），
对白 <d> 内原文不动；只插入参考标签 <Subject N> / <Audio N>，并去掉 FL2VA 专用的“Picture N 对齐首尾帧”分句
（Ref2VA 里参考图不是首尾帧）。subject_definitions 只描述参考图本身可见的外观（发色、服装），不新增剧情。
中文 image_body 不进提示词（官方要求六段全英文）。

用法：python tools/lab_ep02/ref2va_prompt.py S6 6 [--audio-gu]  > out.txt
  参考图顺序固定：Picture 1 = 林晚脸（lin_wan.png），Picture 2 = 林晚 ep02 造型全身（REF-LW-01_front），
  Picture 3 = 顾沉（gu_chen ar-98f7c63570.png，仅当本镜有顾沉）。--audio-gu：<Audio 1> = 顾沉音色参考。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

W_PAT = r"(?:the |a )?young woman(?: in her twenties)? with long ice-blue hair and straight bangs"
M_PAT = r"(?:the |a )?(?:adult )?man in a black tailored shirt"


def field(vp: str, name: str) -> str:
    m = re.search(name + r":\s*(.*?)(?:\n\n[a-z_]+:|$)", vp, re.S)
    return m.group(1).strip() if m else ""


def strip_fl2va(s: str) -> str:
    s = re.sub(r"\s*begins in the position, framing and lighting established by Picture \d", "", s)
    s = re.sub(r",?\s*and settles into the pose, spacing,? and composition established by Picture \d at the end of the shot", "", s)
    s = re.sub(r",?\s*(?:and\s+)?[^,.;<>]*\bPicture \d\b[^,.;<>]*", "", s)
    return re.sub(r"\s+([,.])", r"\1", s).strip()


def main(shot: str, seconds: float, audio_gu: bool, mf: bool = False, say_at: float | None = None):
    """mf（E5 multiframe）：<Picture 1> = 定稿首帧（[Shot 1] 首帧锚点），<Picture 2> = 林晚脸部裁切，<Picture 3> = 顾沉脸部裁切。
    say_at：在台词子句前写官方时间写法 “At 00:SS.mmm,”（只写时间，不改内容）"""
    c = json.loads((ROOT / f"data/renders/ep02/{shot}/compiled.json").read_text(encoding="utf-8"))
    vp = c["video_prompt"]
    desc = strip_fl2va(field(vp, "integrated_multimodal_description"))
    faces = (c.get("visual_spec") or {}).get("faces_visible") or []
    has_gu = "gu_chen" in faces or re.search(M_PAT, desc) is not None
    # 风格句：[Shot 1] 后第一个分句里的风格词（剧本原文）挪到 [Shot 1] 前（官方：style opening 在 [Shot 1] 之前）
    body = re.sub(r"^\[Shot 1\]\s*", "", desc)
    style = ""
    m = re.match(r"((?:Live-action|Cinematic|live-action|cinematic)[^.]*?depth of field),\s*", body)
    if m:
        style = m.group(1)
        body = body[m.end():]
        body = body[0].upper() + body[1:]
    # 参考标签：第一次出现时 “<Subject N>, 描述”，说话人 “<Subject N> (Sx)”
    body = re.sub(r"[Tt]he on-screen (young woman[^()]*?)\s*\((S\d)\) says:", r"<Subject 1> (\2), the \1, says:", body)
    body = re.sub(r"[Tt]he on-screen ((?:adult )?man[^()]*?)\s*\((S\d)\) says:", r"<Subject 2> (\2), the \1, says:", body)
    body = re.sub(W_PAT, "<Subject 1>, the young woman with long ice-blue hair and straight bangs,", body, count=1)
    if has_gu:
        body = re.sub(M_PAT, "<Subject 2>, the man in a black tailored shirt,", body, count=1)
    body = re.sub(r",\s*([.,])", r"\1", body)
    voice_gu = None
    mm = re.search(r"\(S(\d)\)", body)
    for sx in re.findall(r"<Subject 2> \((S\d)\)", body):
        voice_gu = sx
    if mf:
        sd = ["<Picture 1> is the first frame of [Shot 1], defining the composition, setting, lighting, clothing and positions.",
              "<Subject 1> is the young woman in <Picture 1> whose facial identity comes from <Picture 2>, "
              "with long ice-blue hair and straight bangs."]
        if has_gu:
            sd.append("<Subject 2> is the man in <Picture 1> whose facial identity comes from <Picture 3>, "
                      "with short neat black hair and a black tailored shirt.")
    else:
        sd = ["<Subject 1> is the young woman whose face comes from <Picture 1> and whose outfit comes from <Picture 2>, "
              "with long ice-blue hair and straight bangs."]
        if has_gu:
            sd.append("<Subject 2> is the man in <Picture 3>, with short neat black hair and a black tailored shirt.")
    if audio_gu and has_gu and voice_gu:
        sd.append(f"<Audio 1> is the voice-timbre reference for <Subject 2> ({voice_gu}).")
    subj = "<Subject 1> and <Subject 2>" if has_gu else "<Subject 1>"
    tt = "[keyframe completion + reference generation" if mf else "[reference generation"
    tt += " + audio reference]" if (audio_gu and voice_gu) else "]"
    summ = (f"{tt} A single continuous {seconds:g}-second shot featuring {subj}; " +
            ("the shot begins from <Picture 1> and the face references define identity."
             if mf else "the reference pictures define identity, hair and clothing only and are not frames of the target video.")
            + (f" <Audio 1> guides the voice timbre of <Subject 2>." if audio_gu and voice_gu else ""))
    ret = (["<Picture 1> ([Shot 1] first frame): fully_preserved - composition, setting, lighting and clothing are kept."]
           if mf else [])
    ret.append("<Subject 1> (appears in [Shot 1]): fully_preserved - face, ice-blue hair, bangs and outfit are retained.")
    if has_gu:
        ret.append("<Subject 2> (appears in [Shot 1]): fully_preserved - face, black hair and black tailored shirt are retained.")
    if audio_gu and voice_gu:
        ret.append("<Audio 1>: reference - the voice timbre guides <Subject 2>'s delivery without copying the original signal.")
        body = re.sub(rf"<Subject 2> \({voice_gu}\), (.*?), says:",
                      rf"<Subject 2> ({voice_gu}), \1, using the voice timbre referenced from <Audio 1>, says:", body, count=1)
    if say_at is not None:
        body = re.sub(r"(<Subject \d> \(S\d\), (?:(?!<d>).)*?says:)", lambda m: f"At 00:{say_at:06.3f}, " + m.group(1), body, count=1)
    if mf:
        body = "The shot begins from <Picture 1>. " + body
    dd = (f"The target video is {style.lower() if style else 'live-action and cinematic'}.\n[Shot 1] {body}")
    out = ["subject_definitions:", *sd, "", "summary:", summ, "", "retention_analysis:", *ret, "",
           "detailed_description:", dd, "",
           "overall_soundscape:", field(vp, "overall_soundscape") or "N/A", "",
           "non_diegetic_music:", field(vp, "non_diegetic_music") or "N/A"]
    sys.stdout.reconfigure(encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    sa = None
    if "--say-at" in sys.argv:
        sa = float(sys.argv[sys.argv.index("--say-at") + 1])
    main(sys.argv[1], float(sys.argv[2]), "--audio-gu" in sys.argv, "--mf" in sys.argv, sa)
