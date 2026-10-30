"""画布里的人工修改。只存差异，剧本原文不动；为空的字段表示沿用编译结果。"""
from pydantic import BaseModel


class ShotEdit(BaseModel):
    image_prompt: str | None = None     # 整段替换首帧提示词
    image_negative: str | None = None
    video_prompt: str | None = None     # 旧版视频提示词整段替换（只影响 legacy_video_prompt，不进 H3）
    camera: str | None = None           # 运镜，如 "camera push in 缓慢推近"；放在视频提示词最前
    expression: str | None = None       # 表情关键词，如 "睫毛颤动，咬唇"
    image_seed: int | None = None
    video_seed: int | None = None
    last_frame: str | None = None       # 目标尾帧：图片路径（相对 data/），或 "next" = 下一镜的首帧
    # 尾帧独立资产（canvas-ui-spec-v2 §3.5.1）
    last_prompt: str | None = None      # 整段替换尾帧提示词（生成模式）
    last_seed: int | None = None
    last_source: str | None = None      # gen | next | upload | video；None = 按 last_frame / 已有版本推断
    # 导演加强（项目方亲自写，原样追加到首帧/尾帧提示词，放在镜头内容之后、风格后缀之前；为空 = 不加任何东西）
    boost_first: str | None = None
    boost_last: str | None = None
    # H3 声音（E8，官方提示词指南 §4.6/§4.7）：替换视频提示词末尾的 overall_soundscape / non_diegetic_music 段
    soundscape: str | None = None
    h3_body: str | None = None          # H3 提示词正文（integrated_multimodal_description，英文）；对齐句 / 配乐 N/A 不可改
    music: str | None = None
    note: str = ""
    updated_at: str | None = None


class EpisodeEdit(BaseModel):
    """整集的导演加强（data/renders/epXX/episode_edit.json），先于镜头级加强追加"""
    boost_first: str | None = None
    boost_last: str | None = None
    music: str | None = None            # 整集默认背景音乐（non_diegetic_music），镜头没写时用
    updated_at: str | None = None


class Take(BaseModel):
    """一次渲染结果"""
    n: int
    stage: str                          # image | last | video
    file: str                           # 相对 data/ 的路径
    seed: int
    prompt: str
    negative: str = ""
    seconds: float | None = None
    frames: int | None = None
    last_frame: str | None = None
    created_at: str
    workflow: str | None = None         # qwen_t2i | qwen_edit | h3_fl2va
    reference: str | None = None        # 锁脸参考图（相对项目根目录）
    qc: dict | None = None              # 自动质检结果，如 {"nudity": false, "hits": [], "clip_bare": 0.1}
    raw_file: str | None = None         # 调色前的原图（相对 data/）；file 为调色后的版本
    grade: dict | None = None           # 调色参数，如 {"method": "reinhard_lab", "strength": 0.6, "dark": false}
    score: dict | None = None           # 多候选评分（C5）：{"total", "parts": {...}, "missing": [...], "reasons": [...]}
    round: int | None = None            # 第几轮候选（1 起）
    references: list[str] | None = None  # 全部参考图（相对项目根目录，按 图1、图2… 顺序）
    look_hash: str | None = None        # 渲染时本镜造型解析哈希（API 在任务完成后补写），变了 = 本镜输入变化
    source: str | None = None           # 尾帧来源 gen | next | upload | video；首帧上传为 upload
    bible_version: str | None = None    # T06：出图时的规则版本（ns_agent.compiler.bible_version），信息用
    inputs_sha: str | None = None       # T51：出图时本镜输入哈希（state_timeline.json），与当前不同 = 过期
