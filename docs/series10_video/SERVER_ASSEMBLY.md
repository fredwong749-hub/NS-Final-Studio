# 服务器端整集合成接口（VIDEO10 ↔ WORKFLOW / VOICE10，2026-11-01）

总调度 G0（11-01 ~17:00）：原片不拉回笔记本（跳板约 17 KB/s），合成在负责该集的服务器上做，只把小体积预览拉回。
本文是 VIDEO10 的 W4 合成逻辑（K-EDT-V10）在服务器上跑起来需要的东西，WORKFLOW 做服务器常驻时照此部署。

## 入口
`tools/series10_video/night.py`（服务器常驻版，只管本机负责的集）→ `finalize(ep, host, …)`：
1. `vidgen.py proxies <host> <ep>`：写 `video/episodes/epNN/manifest.json`（每镜 `source` = 原片 `video/clips/…`，`proxy` = 540×960 审片代理）。服务器上本来就在本地，不用 ssh 自己。
2. `tools/series10_video/upscale_preview.py epNN`：原片 → `<名>_sr1080.mp4`（lanczos 1080 宽 + 亮度 unsharp 0.6、CRF 16；SeedVR2 1080 质检过了才用它，见 docs/SOP_production.md §12）。ffmpeg：`NS_FFMPEG` > PATH > `/root/claude-kimi-ns-studio-v1/env/ffmpeg/bin/ffmpeg` > `/root/work/fredw/tools_bin/ffmpeg`。
3. `assembly_sources(manifest)`：只用原片 / 放大版，代理禁止进成片；原片缺 → `ASSEMBLE_WAIT`，不重做代理。
4. `tools/assemble_episode.py epNN --sources-from … --variant vN --dialogue-source h3 [--no-bgm]` → `data/episodes/series10/epNN_vN.mp4`。

## 服务器上要有的
| 东西 | 来源 | 负责 |
|---|---|---|
| 仓库代码：tools/series10_video、tools/assemble_episode.py、services/post、packages、config/voices.json、config/render_quality.json 等 | 笔记本推送（deploy.py 现在只推 tools/series10_video 等 4 个目录，不够） | WORKFLOW |
| data/import/script_v2.json（H3 台词）、data/renders/epNN/S*/（尽力镜的静帧占位） | 笔记本推送 | WORKFLOW |
| data/cache/tts/（已合成过的句子缓存，15 MB；ep01 v2 的 TTS 全部命中缓存，backend 记为 NoneType） | 笔记本推送 | WORKFLOW |
| 配音解释器（config/voices.json speech_python：sherpa-onnx==1.13.8 + kokoro / SenseVoice 模型目录）；缺时 night.py 记 hold_tts（K-OPS-309），不耗版本号 | 服务器安装 | VOICE10 |
| 旁白克隆后端 remote_tts（gpu36 venv_tts） | 已有 | VOICE10 |
| Python 依赖：pydantic、yaml、opencv、PIL（离线时 gpu33 一个解释器缺 yaml / pydantic，见 night.log 10:44） | venv | WORKFLOW |

## 拉回笔记本的
`data/episodes/series10/epNN_vN.mp4`（1080×1920，约 2.5 Mbps × 40 s ≈ 12 MB，跳板 17 KB/s 要 12 分钟——建议同时出一份 540×960 审片版拉回，原尺寸留服务器）、`epNN_vN.timeline.json`、`docs/series10_video/epNN_review.md`、`data/review_pages/series10_video/epNN/`。
