"""T58 封板 debug：批量重写（tools/script_chat_batch.py）与定向返修（tools/script_chat_repair.py）。
写作模型和格式校验都用替身：不连 gpu3，不跑真校验器；只测流程（首写 / 拆两半 / 续跑 / 定向返修 / 预算 / 台词清单）。"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import script_chat_batch as B  # noqa: E402
import script_chat_repair as RP  # noqa: E402
from ns_api import script_chat as S  # noqa: E402


def shot(k, speaker=None, line=None, extra=""):
    d = f"**对白**：（{speaker}）“{line}”\n" if line else ""
    return (f"**镜{k}｜img**：中景，林晚{extra}\n**motion**：lnwan01，static camera，她抬眼——她看向窗外，双手扶住栏杆\n"
            f"**时长**：8秒\n{d}**H3提示词**：\n```text\nx\n```\n")


def episode(n, shots):
    return f"## ep{n:02d}《测试》\n\n**剧情**：占位\n\n**配乐**：占位；【BGM】Piano.\n\n" + "".join(shots)


SRC = episode(1, [shot(1, "顾沉", "甲句。"), shot(2, "她", "乙句。"), shot(3, "他", "丙句。"), shot(4)])


def ok_report(text, tag="x", registry=None):   # registry：fredw-92/D2 逐集继承
    """替身校验：只看镜数（6–8 以外记集级 block），其它一律通过"""
    shots = S.split_shots(text)[1]
    issues = [] if 1 <= len(shots) <= 8 else [{"rule_id": "QW-E2", "level": "block", "field": "", "detail": "镜数"}]
    return {"number": 1, "title": "测试", "issues": issues, "repair": "集头返修" if issues else "",
            "shots": [{"id": f"s{k}", "index": k, "duration": 8, "ok": True, "issues": [], "repair": ""} for k in shots]}


class FakeModel:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, messages, cfg=None, max_tokens=None):
        self.calls.append(messages[-1]["content"])
        return {"content": self.replies.pop(0), "reasoning": "", "finish": "stop",
                "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}}


@pytest.fixture
def env(tmp_path, monkeypatch):
    src = tmp_path / "src.md"
    src.write_text("# 头\n\n" + SRC + "\n---\n", encoding="utf-8")
    monkeypatch.setattr(S, "STORE", tmp_path / "store")
    monkeypatch.setattr(S, "count_tokens", lambda text, cfg=None: len(text) // 4)
    monkeypatch.setattr(S, "validate_episode_text", ok_report)
    monkeypatch.setattr(S, "validate_draft", lambda s, episode=None: {"draft": "x", "episodes": [], "blocking": 0,
                                                                        "warnings": 0})
    monkeypatch.setattr(B, "model_price", lambda: {"prompt": 0.0, "completion": 0.0, "input_cache_read": 0.0})
    monkeypatch.setattr(B.time, "sleep", lambda s: None)
    monkeypatch.setattr(RP.time, "sleep", lambda s: None)
    return src


def run(src, *args):
    return B.main(["--source", str(src), "--workers", "1", *args])


def last_session():
    d = sorted(p for p in S.STORE.iterdir() if (p / "session.json").exists())[-1]
    return S.load_session(d.name)


def test_first_write_includes_dialogue_checklist(env, monkeypatch):
    fm = FakeModel([SRC])
    monkeypatch.setattr(S, "complete", fm)
    run(env)
    s = last_session()
    assert s["episodes"]["1"].startswith("## ep01《")
    assert "必须逐字出现的台词" in fm.calls[0] and "甲句。" in fm.calls[0] and "丙句。" in fm.calls[0]


def test_split_in_two_when_appendix_dropped(env, monkeypatch):
    real = S.prompt_for
    monkeypatch.setattr(S, "prompt_for", lambda u, context=None, cfg=None: (
        real(u, context, cfg)[0], [{"name": "附录·A1", "dropped": "hit"}] if "以下是" in u and "前半" not in u
        and "后半" not in u else []))
    first = episode(1, [shot(1, "顾沉", "甲句。"), shot(2, "她", "乙句。")])
    second = shot(3, "他", "丙句。") + shot(4)
    fm = FakeModel([first, second])
    monkeypatch.setattr(S, "complete", fm)
    run(env)
    text = last_session()["episodes"]["1"]
    assert sorted(S.split_shots(text)[1]) == [1, 2, 3, 4]
    assert "前半" in fm.calls[0] and "后半" in fm.calls[1]


def test_missing_line_targeted_repair_splices_and_renumbers(env, monkeypatch):
    lossy = episode(1, [shot(1, "顾沉", "甲句。"), shot(2, "她", "乙句。"), shot(3), shot(4)])   # 丢了丙句
    fixed = shot(2, "她", "乙句。") + shot(3, "他", "丙句。") + shot(4) + shot(5, extra="，拆出的新镜")
    fm = FakeModel([lossy, fixed])
    monkeypatch.setattr(S, "complete", fm)
    run(env)
    text = last_session()["episodes"]["1"]
    assert "丙句。" in text and "【缺台词返修】" in fm.calls[1]
    assert sorted(S.split_shots(text)[1]) == [1, 2, 3, 4, 5]          # 拆镜后全集镜号顺延


def test_resume_repairs_existing_draft_without_rewrite(env, monkeypatch):
    s = S.new_session("续跑", independent=True)
    s["episodes"]["1"] = episode(1, [shot(1, "顾沉", "甲句。"), shot(2, "她", "乙句。"), shot(3), shot(4)])
    S.save_session(s)
    fm = FakeModel([shot(2, "她", "乙句。") + shot(3, "他", "丙句。") + shot(4)])
    monkeypatch.setattr(S, "complete", fm)
    run(env, "--session", s["id"])
    assert len(fm.calls) == 1 and "【缺台词返修】" in fm.calls[0]     # 没有重写整集，只修缺句
    assert "丙句。" in S.load_session(s["id"])["episodes"]["1"]


def test_budget_stops_new_episodes(env, monkeypatch):
    two = env.parent / "two.md"
    two.write_text("# 头\n\n" + SRC + "\n---\n\n" + SRC.replace("ep01", "ep02") + "\n---\n", encoding="utf-8")
    monkeypatch.setattr(B, "model_price", lambda: {"prompt": 1.0, "completion": 1.0, "input_cache_read": 1.0})
    fm = FakeModel([SRC, SRC.replace("ep01", "ep02")])
    monkeypatch.setattr(S, "complete", fm)
    B.main(["--source", str(two), "--workers", "1", "--budget-usd", "10"])
    assert len(fm.calls) == 1 and "2" not in last_session()["episodes"]


def test_missing_lines_repair_infeasible_returns_none():
    # 当前稿 8 镜，缺“乙句”，前后已保留的句子在镜 2、镜 3 → 段内最多 2 镜，却要放三人轮流的三句 → 局部修不可能合格
    cur = episode(1, [shot(1), shot(2, "顾沉", "甲句。"), shot(3, "他", "丙句。")] + [shot(k) for k in range(4, 9)])
    src = episode(1, [shot(1, "顾沉", "甲句。"), shot(2, "她", "乙句。"), shot(3, "他", "丙句。")])
    assert S.missing_lines_repair(src, cur) is None


def test_repair_tool_uses_targeted_repair(env, monkeypatch):
    s = S.new_session("返修", independent=True)
    s["episodes"]["1"] = episode(1, [shot(1, "顾沉", "甲句。"), shot(2, "她", "乙句。"), shot(3), shot(4)])
    S.save_session(s)
    fm = FakeModel([shot(2, "她", "乙句。") + shot(3, "他", "丙句。") + shot(4)])
    monkeypatch.setattr(S, "complete", fm)
    rc = RP.main([s["id"], "1", "--rounds", "1", "--source", str(env)])
    assert rc == 0 and "【缺台词返修】" in fm.calls[0]
    assert "丙句。" in S.load_session(s["id"])["episodes"]["1"]


def test_splice_reply_must_start_at_range_start():
    """回复从后面的镜开始（漏了镜 a）不接受，否则会把镜 a 连同台词丢掉（封板修复）"""
    assert S.splice_reply_ok(shot(2) + shot(3), 2)
    assert not S.splice_reply_ok(shot(3) + shot(4), 2)
    assert not S.splice_reply_ok("没有镜头", 2)
