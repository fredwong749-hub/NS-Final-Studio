# 人类反馈后台 · 接口（FEEDBACK 定，前端 UIRSI2 实现）

后端：`services/api/ns_api/feedback.py`，存储 `data/feedback/`。测试：`tests/test_feedback_api.py`。

## 1. 提交反馈

`POST /api/feedback`（登录即本人：提交人取登录会话，前端不要让项目方填名字）

```json
{
  "text": "手不对",                         // 必填，项目方的原话
  "route": "/?ui=film#ep02",                // location.pathname + search + hash
  "run": "series10_v1",
  "ep": 2,                                   // 也接受 "ep02"
  "shot": "S3",
  "target": {
    "kind": "video",                         // first | last | video | field | ui | shot | episode | other
    "field": null,                           // kind=field：字段名（action / camera / prompt_h3 …）
    "selector": null,                        // kind=ui：data-testid 或 CSS 选择器
    "label": null,                           // 界面上看到的文字（按钮名、标签）
    "file": "renders/ep02/S3/video.mp4"      // 前端知道素材路径就带上
  },
  "take": "video_002_pipeline_49bf18c8.mp4", // 当前 take（号或文件名）
  "timecode": 4.3,                           // 点视频时取 video.currentTime（秒）
  "screenshot": "data:image/png;base64,...", // 可选，≤ 6 MB（html2canvas / 元素截图）
  "viewport": {"w": 1440, "h": 900, "dpr": 2},
  "context": {}                              // 其它自由字段，原样存
}
```

返回整条记录（见 §3）。

## 2. 列表 / 单条 / 元数据

- `GET /api/feedback?status=new,triaged&ep=2&shot=S3&route=/&run=series10_v1&open=1&limit=500`
  → `{items: [记录（不含 history）], counts: {new, triaged, fixing, fixed, verified, closed}, dots: {red, yellow, green}, total}`
  - 帧上角标：`GET /api/feedback?ep=2&open=1`，按 `shot` + `target.kind` 分组显示圆点。
- `GET /api/feedback/{id}` → 整条（含 `history`）
- `GET /api/feedback/{id}/screenshot` → 截图文件
- `GET /api/feedback/meta` → `{statuses: [{key, zh, dot, next}], categories: [{key, zh, owner}], target_kinds, reopen_from}`

## 3. 记录字段（前端显示用）

| 字段 | 说明 |
|---|---|
| id | fb-0001 |
| status / status_zh | new 新反馈 → triaged 已分派 → fixing 修复中 → fixed 已修待复核 → verified 复核通过 → closed 已关单 |
| dot | **只用三种圆点**：red = 新 / 被打回；yellow = 已分派 / 修复中 / 待复核；green = 复核通过 / 已关单。前端按全站色规（灰 / 琥珀 / 绿）显示：red → 琥珀、yellow → 灰、green → 绿（UIRSI2 11-02，接口字段不变） |
| category / owner | 分类（meta.categories）与负责方 |
| root_cause / fix_note / fix_evidence | 根因、修复说明、修复证据 |
| miss_analysis / improvements | 漏检分析、系统改进清单 |
| same_class | 同类扫描 {check, scanned, hits} |
| verify / regression | 复核结果、回归集登记 |
| reopened | 被打回次数 |
| history | [{at, by, status, from, note}] |

## 4. 改状态 / 打回

`POST /api/feedback/{id}/status`  `{status?, note?, ...处理字段}`

- 前端只需要做 **打回（reopen）**：项目方在 fixed / verified / closed 的条目上点“没修好”→ `{"status": "new", "note": "<可选>"}`。只有登录的项目方能打回（否则 403）。
- 其余流转由处理方（FEEDBACK / 各负责方）走，闸门：triaged 要分类 + 负责方；fixed 要修复说明 + 证据；verified 要 `verify.result=pass`；closed 要回归登记 + 至少一项系统改进 + 漏检分析。不满足返回 422，跳步返回 409。

## 5. 前端要求（UIRSI2）

- overview（`?ui=film`）和单集页顶栏加“反馈模式”开关；打开后点任意帧（首帧 / 尾帧 / 视频）或任意元素 → 弹文字框，自动带上 §1 的上下文（视频带 currentTime，元素带 data-testid / 文字），一键提交，不要求项目方填别的。
- 反馈列表抽屉：按状态分组，每条显示圆点 + 原话 + 镜号 + 当前处理说明；fixed / verified / closed 条目上有“没修好”按钮（打回）。
- 风格：电影胶片 A；状态色只用 §3 的三种圆点。

## 6. 两种特殊关单（FEEDBACK 11-02 补）

- **测试单**：`{"status":"closed","category":"test","note":"测试单"}`，任何状态一步关；默认不进列表 / 计数，`?tests=1` 才显示。
- **冻结关单**（项目方决定不处理，如 L-125 V1 冻结）：`{"status":"closed","resolution":"frozen","note":"<决定编号与理由>"}`，只能从 triaged / fixing / fixed / verified 关；不走 fixed / verified，但漏检分析、系统改进、回归登记照样必填。记录带 `resolution: "frozen"`，前端可在已关单旁标“冻结”。
