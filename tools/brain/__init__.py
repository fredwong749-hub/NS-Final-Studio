"""BRAIN-FW（11-06，项目方“master agent 必须全局接管，依靠模型去执行……写个全局监控，llm 模型比如 fable 进行判断和调度”）：
LLM 在环的全局调度框架。telemetry（只读快照）→ 大脑（API 常驻 brain_api / 会话内 PS-MASTER，见 session_brain.md）→ actions（白名单执行器）。"""
