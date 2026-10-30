# 画布前端冒烟回归（ui_smoke）

封板 / 发版前跑一遍：无头 Chrome 逐页逐个交互真点，记录 console 报错、未捕获异常、失败请求（≥400 / 网络失败）、
卡在“加载中”、横向溢出、期望元素没出现，并截图。只读：不出图、不导入、不发送、不上传、不通过 / 打回、不设为当前；
确认框只打开再按 Esc。

```bash
node tools/ui_smoke/smoke.mjs                                   # 24 个场景 × 1366/1600 × 深/浅 = 96 次
node tools/ui_smoke/smoke.mjs episode inspector-tabs            # 只跑指定场景
BASE=http://127.0.0.1:8800/ node tools/ui_smoke/smoke.mjs       # 推荐：对 API 托管的 dist 跑（先 npm run build）
WIDTHS=1600 THEMES=dark node tools/ui_smoke/smoke.mjs           # 快速单组合
```

- 输出：`shots/<场景>-<宽>-<主题>.jpg`（场景结束时）、`shots/<场景>-open-<宽>-<主题>.jpg`（菜单 / 抽屉打开时）、`results.json`。
- 退出码 = 失败次数（0 = 全过），可直接放进脚本 / CI。
- 默认 `BASE=http://127.0.0.1:5173/`（vite dev）。dev 模式下别的会话改源码会触发热更新，偶发“useStudio 必须在
  StudioProvider 里使用”之类的瞬时异常——封板回归请用 `BASE=http://127.0.0.1:8800/`（打包后的 dist）。
- 需要：Node ≥ 22（内置 WebSocket）、Chrome（`CHROME=` 可改路径）、画布 API 在跑。
- 场景定义在 `smoke.mjs` 顶部 `SC` 数组；步骤：`key`、`click`（选择器）、`clickText`（按钮文字开头）、`expect`、`gone`、`wait`、
  `eval`（返回非空字符串 = 问题）、`esc`、`shot`。
