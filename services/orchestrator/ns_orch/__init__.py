"""
「开始生产」编排器（T42）：每个项目 + 每集一台持久化的简单状态机（JSON，幂等、可断点续跑）。

- 笔记本步骤（导入、画面说明、非成人首/尾帧、成片装配）由 Executor 执行；笔记本从不出视频（TASKS 规则 7）。
- gpu3 步骤（成人首尾帧、视频、QA、声音、4K）通过 gpu3 桥交接（series 控制 + 状态读取），笔记本只看进度。
- 关口 G2–G5（以及「交 gpu3」授权）在「待办」里成卡片；项目方点之前，关口之后的步骤不会运行。

    from ns_orch.engine import Engine
    Engine(ctx, executor, bridge).tick()
"""
