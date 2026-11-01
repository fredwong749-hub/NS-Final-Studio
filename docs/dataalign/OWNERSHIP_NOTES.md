# DATAALIGN 所有权备注

## 2026-11-01 系统固定说明句：唯一来源
- `services/api/ns_api/unified_stale.py`（DATAALIGN）里的 `match_target` 负责认出 frame_v9 正文中由系统插入的固定说明句。它会把这些句子放回“当前正文”，再与版本中记录的提示词比对。
- 只要句子没被认出，刚出的图就会被误标为“编译器升级”或“剧本已改”。
- 这些句子的写法和识别用的正则式，**只在** `services/agent/ns_agent/asset_refs.py` 维护（REFLOCK 文件，总调度 11-01 指派 DATAALIGN 合并）：
  - `TEXT_FALLBACK_NOTE` / `TEXT_FALLBACK_RE`：“参考槽不足、改走文字”（REFLOCK K-REN-136）
  - `OUTER_ITEMS_NOTE` / `OUTER_ITEMS_RE`：“本镜造型X要穿全”（PRODUCER K-REN-101，总调度同意后加在 unified_stale；DATAALIGN 已并入 asset_refs）
  - `TEXT_NOTE_RES`：按 `compile_frame` 的拼接顺序列出全部识别正则式（槽位不足在前、外层单品在后）。`match_target` 只读这一项。
- `frame_job.OUTER_NOTE` / `OUTER_NOTE_RE` 只是引用上面常量的别名，留着是为了兼容旧调用和 `tests/test_outer_items.py`。
- **规矩**：新增或修改系统固定说明句时，在同一次改动里把它加进 `TEXT_NOTE_RES`（注意顺序），再跑 `tests/test_unified_stale.py`、`tests/test_outer_items.py` 和 `tools/qa/data_parity.py --all`（D-FRESH）。
