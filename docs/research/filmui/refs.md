# FILMUI 设计研究 · 电影胶片界面（2026-11-02）

目的：给 momoso 总览 / 审片页做“电影胶片效果”的三个方向，先把真实胶片和真实工业工具的样子查清楚，避免“网页模板贴装饰”。
每条：要点 → 原文或出处 → 链接 → 置信度 → 落到设计上的规则。

## 1. 真实 35mm 电影胶片

| # | 要点 | 出处 | 置信度 | 设计规则 |
|---|---|---|---|---|
| F1 | KeyKode 是 Kodak 1990 年起印在 35mm/16mm 片边的逐帧识别码；人可读部分 12 个字符，后面跟同样信息的条码（USS-128）。例 “KU 22 9611 1802+02.3”：前 2 字母 = 厂商码 + 片种码，6 位卷号（常写成 2+4），4 位英尺计数，“+02” 帧偏移，“.3” 齿孔偏移 | [Wikipedia: Keykode](https://en.wikipedia.org/wiki/Keykode)（原文 “12 characters in human-readable form followed by the same information in barcode form”） | 中（词条标注缺引用，格式与 SMPTE ST 254 一致） | 片边码照真实格式排：`字母2 + 卷号2+4 + 计数4 + +帧`，等宽字体，小字号；我们的值从“集号/镜号”推出，不编造片种 |
| F2 | 35mm 上每 1 英尺 = 16 帧 = 64 齿孔印一次码；中间每 4 齿一个短横 “-” | 同上（原文 “intervals of one foot (16 frames or 64 perforations)”；“a single '-' dash marks every four perforations”） | 中 | 片边码不要每帧都印——每条只在片头印一次完整码，帧下面只印镜号；短横做节奏 |
| F3 | 冲洗后片边可见：片种号 5219（35mm）、乳剂号与卷号、EASTMAN KEYKODE 码、Kodak 内部码 “EJ” | [Kodak VISION3 500T 5219/7219 技术资料](https://www.kodak.com/content/products-brochures/motion-picture/KODAK-VISION3-500T-5219-7219-brochure.pdf)；[5219 tech PDF 镜像](https://juneleung.github.io/filmdoc/Kodak/CrNeg/5219-Vision3-500T-tech.pdf) | 高 | 片头片边印 “EASTMAN 5219”（500T 夜戏多）；250D 是 5207，日戏集可换，但不混用 |
| F4 | KS 齿孔：圆角矩形，1.981mm 高 × 2.794mm 宽；齿距负片 4.740mm（短齿距），正片 4.750mm | [NFSA 词汇：KS perfs](https://www.nfsa.gov.au/preservation/preservation-glossary/ks-perfs)；[Wikipedia: Film perforations](https://en.wikipedia.org/wiki/Film_perforations)；[SMPTE ST 139](https://pub.smpte.org/doc/st139/20031112-pub/st0139-2003.pdf) | 高 | 齿孔宽:高 = 1.41:1，圆角小（不是药丸形）；齿距 = 0.19 × 画幅高 |
| F5 | 4-perf 画幅约 24.9 × 18.7mm（横幅，胶片竖走）；3-perf / 2-perf 用于更宽画幅省片 | [In Depth Cine: 2/3/4-perf](https://www.indepthcine.com/videos/perf-35mm-film)；[Wikipedia: Film perforations](https://en.wikipedia.org/wiki/Film_perforations) | 高 | **我们的画是 9:16 竖幅**：横走片条上，24.9mm 画高对应宽 14.0mm ≈ 3 个齿距（14.22mm）。所以横向片条用“3 齿 / 帧”才几何正确；4 齿 / 帧会把竖幅拉成横幅或留黑边——设计里写明这一点，不硬套 4 齿 |
| F6 | 片条总宽 35mm：两侧各约 2mm 片边 + 齿孔，中间画幅 | 同 F4/F5 | 高 | 片条高 = 1.41 × 画高；上下各 0.2 × 画高给片边 + 齿孔 |
| F7 | 片头 / 片尾（head / tail leader）：卷头标 HEAD、卷尾标 TAIL/FOOT；SMPTE Universal Leader 用秒倒数（8→2，2 处 “2-pop”） | [Wikipedia: Film leader](https://en.wikipedia.org/wiki/Film_leader)；[Avid wiki: SMPTE Universal Leader](https://www.avid.wiki/SMPTE_Universal_Leader) | 中（标准号各处说法不一） | 每条片头留一小段空片基，只印集号；**不画倒数圆圈**（那是装饰，不是信息） |
| F8 | 正片片基黑、齿孔透光；放映 / 看片环境暗，齿孔在灯箱或暗场里显得比片基亮 | 常识 + F4 图片 | 中 | 片基 #050505，齿孔用比页面略亮的暖灰，片边字用暗暖黄（像片边曝光字），对比度压低，不抢画面 |

## 2. 电影工业工具的布局

| # | 要点 | 出处 | 置信度 | 设计规则 |
|---|---|---|---|---|
| T1 | Frame.io V4 播放器：逐帧拖动，悬停时间线出该帧预览；评论以标记落在时间线上 | [Frame.io V4 Player & Commenting](https://blog.frame.io/2024/05/28/frame-io-v4-features-player-and-commenting/)；[Adobe：AE 里的 Frame.io 面板分区（预览 / 评论列表 / 时间线标记 / 播放头 / 工具）](https://helpx.adobe.com/after-effects/desktop/collaboration-with-others/frame-io/collaborate-using-frame-io.html) | 高 | 方向 C：大图主视 + 底部片条当时间线，悬停就预览；评论 / 状态原因跟着当前镜 |
| T2 | Frame.io 2.0：资产滑条——不离开播放页就能在资产间切换 | [Newsshooter: Frame.io 2.0](https://www.newsshooter.com/2017/04/10/frame-io-2-0/) | 中 | 方向 C 的底部片条 = 资产滑条，←/→ 切镜 |
| T3 | ShotGrid / Flow：Playlist 把 Version 编组，在放映室（Screening Room / RV）集体看；可切到 cut 上下文看前后镜 | [Autodesk：Media App 与 Playlists](https://help.autodesk.com/cloudhelp/ENU/SG-Supervisor-Artist/files/sa-review-approval/SG_Supervisor_Artist_sa_review_approval_sa_media_app_playlists_html.html)；[Autodesk：在 cut 中播放](https://help.autodesk.com/cloudhelp/ENU/SG-Supervisor-Artist/files/sa-review-in-context/SG_Supervisor_Artist_sa_review_in_context_sa_playing_in_cut_html.html) | 高 | 一集 = 一个 playlist = 一条片；单集页永远带着“前后镜”上下文（片条） |
| T4 | Avid bin 三种视图：Text（列表）、Frame（缩略图）、Script（缩略图 + 文字列 + 下方留笔记空间）；Storyboard 可排网格、改大小、打印 | [alex4d: Avid for FCP users](https://blog.alex4d.com/avid-for-final-cut-pro-users/)；[ProVideo Coalition: MC101 Lesson 16 bin views](https://www.provideocoalition.com/media-composer-101-lesson-16-bin-views/)；[Frame.io blog: Avid 按故事节拍组织](https://blog.frame.io/2024/01/03/organize-your-avid-media-composer-project-by-story-beats/) | 中 | “每镜一行”= Avid Script view：图在左、字段成列在右，行高由图决定，不用卡片 |
| T5 | Dailies：DIT 卸卡、上临时 LUT、整理后送审；在放映室或云端看；Moxion / PIX 已并入 Autodesk Flow Capture | [Autodesk Flow Capture（原 Moxion）](https://www.autodesk.com/solutions/creative-review.html)；[Pomfort 案例：Mother Mary 双 DIT 流程](https://pomfort.com/article/two-dits-one-pipeline-inside-the-seamless-set-to-post-workflow-for-mother-mary/) | 中 | 看片 = 中性暗灰环境、画面不加任何效果；字段用场记 / 片场语言（镜号、景别、镜头、时长） |
| T6 | 联系印样：摄影师用红色（也有白、黄、橙）油性笔在 contact sheet 上圈选帧、写编号——国家美术馆藏 Robert Frank 1950 年代 contact sheet 有红色 grease pencil 圈选 | [NGA: Robert Frank, Abercrombie & Fitch 5](https://www.nga.gov/collection/art-object-page.89098.html)；[NGA: Rock & roll—Alan Freed 8](https://www.nga.gov/artworks/89162-rock-roll-alan-freed-8)；[Photrio: Contact Sheet Marking](https://www.photrio.com/forum/threads/contact-sheet-marking.80585) | 高 | 方向 B：红笔**只**圈“定稿”的帧，不写字、不打勾；没定稿的不圈。红圈是“选中”标记，不是状态色 |
| T7 | 联系印样是负片直接接触印相：片基（片边）印成黑，片边字印成亮色，齿孔透光处更黑 | 冲印常识；可对照 T6 的 NGA 藏品图 | 中 | 方向 B 片条黑底白字，齿孔比片基更黑；条与条之间露出相纸 |

## 3. 暗色专业界面的排版

| # | 要点 | 出处 | 置信度 | 设计规则 |
|---|---|---|---|---|
| U1 | Material 暗色：底 #121212；文字白色 87% / 60% / 38% 三级；靠表面明度表达层级，不靠阴影；主色要降饱和 | [Material Design 2: Dark theme](https://m2.material.io/design/color/dark-theme) | 高 | 文字只用三级：#e9e6e0（主）/ 62%（次）/ 40%（弃用）；不用投影、不用描边卡片 |
| U2 | 正文对比度至少 4.5:1（WCAG AA） | 同上 | 高 | 次级字 62% 白在 #0e0e0e 上 ≈ 7:1，40% 只用于“未出”这种占位 |
| U3 | 工业工具（Avid / Resolve / RV）的共性：一种无衬线 + 一种等宽；数字等宽；字号 3–4 级 | T4/T5 截图观察 | 中 | 字号只用 11 / 12.5 / 14 / 20；所有编号、焦段、时长用等宽（IBM Plex Mono）；中文用系统黑体 |
| U4 | 网格：8px 基数，图与图之间的间距等于片条帧线宽，而不是网页卡片间距 | 设计判断 | — | 图与图之间 2px 帧线；区块之间 32–48px 留白；不加卡片底色和圆角 |

## 4. 项目方已表达的偏好（汇总，作为验收标准）

- 多看图：特写、中镜、参考图、过程小图；图可以大。
- 不要：彩色胶囊、计数、乱七八糟的符号；DaVinci 调色台风、r44 杂色、r45 齿孔条、纸框——“像普通网页”“装饰假”。
- 状态色全站只许三种圆点：灰（未开始）/ 琥珀（进行中或要处理）/ 绿（通过）。
- 胶片质感只在“框和底”，画面本身不加滤镜、不加颗粒、不改色。

## 5. 对旧方案的诊断（看 pos_A/B/C 截图与 r44/r45 记录得出）

1. **卡片套卡片**：每集一个圆角面板、每帧一个纸框，层级靠框而不是靠排版 → 像网页模板。
2. **装饰与信息混在一起**：纸框上的 “E-6” 印章、每帧重复的“实拍 50mm f/2 · 计划 85mm …”被截断 → 噪声。
3. **一屏只有 3 集、每集只露 7 镜**：不满足“10 集一屏扫完”，看不到每集结尾。
4. **纸色 + 头像圆圈 + 截断文字**：三种视觉语言并存，颜色杂。
5. **齿孔是“画上去的花边”**：比例不对（药丸形、过密），一看就是假的。

结论：新方向一律去掉卡片；片条按 F4–F6 的真实比例算；信息只在片边（等宽小字）和右侧字段列；每屏能看到全部 10 集。
