"""K-REN-954 种子流（PROMPTFIX 11-02，ALIGNMENT 第 6 步；ep07-S3 尾帧 v16 / v19 同一种子 271940492627291 反复出同一个陌生人）。

旧做法：producer 每轮从第 1 次数起，seed = seed_for("<镜>/producer/<kind>", attempt) 只看次数 → 下一轮重派时
第 1/2/3 次又是同三颗种子，失败过的种子被原样重用（ep07-S3 v14=v17、v15=v18、v16=v19）。

新策略（确定性、可复现、可追踪）：
- 流：key = "<镜>/<stage>/<salt>"（stage = image | last；salt = 阶梯变体名，例如 strategyA，缺省空）；
  第 k 颗 = pipeline.seed_for(key, k)，k 从本次 attempt 起往后走。
- 跳过：这一镜这一 stage 在 takes.json 里用过的种子（不管过没过）一律跳过 → 重试永不复用用过的种子；
  同一份 takes 账本 + 同一 attempt → 两台算出的种子相同（可复现）。
- 首帧 / 尾帧各自一条流（stage 不同），尾帧不借首帧的种子（尾帧是对首帧的编辑，图1 已锁画面）。
- 同场一致性不靠种子：不同提示词下同一颗种子不带来画面一致；同场一致靠参考槽（身份脸 / 场景底图 / 本场造型）和场景定稿句。
- 每次记录 {policy, key, k, skipped, seed} → 作业 seed_policy → take.params.compile_trace（unified_frame._run）。
开关：config/recipes/image_framing.json promptfix.seed_stream（false = 旧做法）。
"""
from __future__ import annotations

POLICY = "K-REN-954/v1"


def used_seeds(takes: list[dict] | None, stage: str) -> set[int]:
    out = set()
    for t in takes or []:
        if (t.get("stage") == stage) and t.get("seed") is not None:
            try:
                out.add(int(t["seed"]))
            except (TypeError, ValueError):
                pass
    return out


def pick(shot: str, stage: str, attempt: int, takes: list[dict] | None = None, salt: str = "") -> tuple[int, dict]:
    from . import pipeline as P
    used = used_seeds(takes, stage)
    key = f"{shot}/{stage}/{salt}"
    k = max(1, int(attempt))
    skipped = 0
    while True:
        s = P.seed_for(key, k)
        if s not in used:
            break
        k += 1
        skipped += 1
    return s, {"policy": POLICY, "key": key, "k": k, "skipped": skipped, "seed": s, "excluded": len(used)}
