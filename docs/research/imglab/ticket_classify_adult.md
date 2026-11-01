# 工单：classify_adult 整集连坐（IMGLAB → 总调度转归属方，11-02）

**现象**：series10_v1 导入稿 102 镜里有 83 镜被 `ns_agent.compiler.classify_adult` 判成 adult，理由只有“整集🔴”，或者“整集🔴”加上“关键词:铁珠”这类服装关键词。
ep06-S2（两人在客厅看蓝图）这种镜头也被判成成人，结果实验出图和“单镜非成人”筛选都用不了。

**代码**：services/agent/ns_agent/compiler.py `classify_adult`。
- 现行写法：`b.adult_per_shot()` 为假时，只要 `ep.high_intensity` 为真，就给本集每一镜都加“整集🔴”。
- 逐镜开关已经有了：config/adult_overrides.json 的 `"per_shot": true`。打开后改按【亲密声】、关键词或人工指定逐镜判定。

**注意**：docstring 写的是“项目方 2026-10-30 定‘恢复整集判定’”。这是项目方决定，不能由 loop 直接推翻。需要总调度向项目方确认，二选一：
- A. 生产仍按整集判定（影响 safe_negative、视频 LoRA 等），**另加**一个只读的逐镜判定 `classify_adult_per_shot`，专门给实验和筛选用；
- B. 生产也改成逐镜判定。

**建议的 check（归属方实现）**：
1. 单测：同一个 🔴 集里，一镜正文只有服装和对话、另一镜有【亲密声】，逐镜判定结果必须是一 False 一 True。
2. 关键词表复核：“铁珠”这类服装或道具词单独出现时，不应该判成成人。这条需要项目方确认，Claude 不评判内容尺度。
3. 数据回扫：报告逐镜判定前后的 adult 镜数（现在是 83/102）。

IMGLAB 这边：A/B 和冒烟只用 `c.adult == False` 的镜（tools/imglab/ab.py `is_adult`），不用整集标记豁免。
