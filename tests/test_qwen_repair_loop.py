"""tools/qwen_repair_loop.py：切分/拼接、对白逐字、续跑（Qwen 调用全部 mock；合成占位剧本，不是剧情文本）"""
import importlib.util
import json
from pathlib import Path

from ns_schema.h3_lint import alignment_line, frames_for_seconds

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("qwen_repair_loop", ROOT / "tools" / "qwen_repair_loop.py")
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)

SOUNDSCAPE = "Placeholder room tone hums steadily. Placeholder footsteps tap twice on the floor."
LINE = "占位台词一。"


def h3(seconds=10, line=LINE, align_seconds=None):
    align = alignment_line(frames_for_seconds(align_seconds or seconds))
    body = ("[Shot 1] Live-action, cinematic, shallow depth of field, a medium shot begins in the position, framing "
            "and lighting established by Picture 1. The on-screen young woman with a soft voice, speaking at a slow "
            f"pace (S1) says: <d>[Chinese] {line}</d> The subject settles into the pose and composition established "
            "by Picture 2 at the end of the shot.")
    return (f"{align}\n\nintegrated_multimodal_description: {body}\n\noverall_soundscape: {SOUNDSCAPE}"
            f"\n\nnon_diegetic_music: N/A")


def shot(i, seconds=10, line=LINE, with_h3=True, h3_text=None, motion_end=True):
    end = "——占位结束状态" if motion_end else "，占位结束状态"
    parts = [f"**镜{i}｜img**：`中景，占位画面{i}`",
             f"**motion**：`lnwan01，camera push in 缓慢推近，占位动作，眼神占位{end}`",
             f"**时长**：{seconds}秒",
             f"**sound**：占位声音；【配乐】延续，强度1；【H3 audio】{SOUNDSCAPE}",
             f"**对白**：（林晚）“{line}”"]
    if with_h3:
        parts.append("**H3提示词**：\n```text\n" + (h3_text or h3(seconds, line)) + "\n```")
    return "\n\n".join(parts)


def episode(n=1, shots=None):
    shots = shots or [shot(i) for i in range(1, 7)]
    head = (f"## ep{n:02d}《占位标题{n}》\n\n**剧情**：占位剧情。\n\n"
            "**配乐**：占位配乐说明；【BGM】Placeholder BGM prompt with soft piano.\n\n")
    return head + "\n\n".join(shots) + "\n\n---\n\n"


PRE = "# 占位剧本\n\n前言占位。\n\n"


def doc(*eps):
    return PRE + "".join(eps)


def args(tmp_path, src, *extra):
    return [str(src), "--out", str(tmp_path / "out.md"), "--base-url", "http://mock", *extra]


class FakeQwen:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, system, user):
        self.calls.append(user)
        r = self.replies.pop(0)
        return r(user) if callable(r) else r


# ------------------------------------------------------------------ 切分 / 拼接

def test_split_and_splice_roundtrip():
    text = doc(episode(1), episode(2))
    pre, chunks = R.split_doc(text)
    assert pre == PRE and len(chunks) == 2 and pre + "".join(chunks) == text
    seg = R.segment(chunks[0])
    assert [s[0] for s in seg["shots"]] == [1, 2, 3, 4, 5, 6]
    assert R.block_text(chunks[0], 1) == shot(2)
    assert R.block_text(chunks[0], "head").startswith("## ep01") and "**配乐**" in R.block_text(chunks[0], "head")
    new = R.splice(chunks[0], 1, "**镜2｜img**：`中景，替换`")
    assert R.block_text(new, 1) == "**镜2｜img**：`中景，替换`"
    assert R.block_text(new, 0) == shot(1) and R.block_text(new, 2) == shot(3)
    assert new.endswith("---\n\n")
    # 最后一镜：--- 之前的空行保留
    last = R.splice(chunks[0], 5, shot(6, seconds=9))
    assert R.block_text(last, 5) == shot(6, seconds=9) and last.endswith("```\n\n---\n\n")


def test_parse_reply_think_and_fences():
    raw = "<think>想一想 **镜9｜img**</think>\n好的：\n```markdown\n" + shot(2) + "\n```\n说明文字"
    block, err = R.parse_shot_reply(raw, 2)
    assert err == "" and block == shot(2)
    assert R.parse_shot_reply(shot(3), 2)[1].startswith("镜号被改成")
    assert "2 个镜头块" in R.parse_shot_reply(shot(2) + "\n\n" + shot(3), 2)[1]
    assert R.parse_shot_reply("没有镜头", 2)[0] is None


# ------------------------------------------------------------------ 返修循环

def test_repair_fixes_shot_and_keeps_others(tmp_path):
    src = tmp_path / "in.md"
    bad = shot(2, motion_end=False)                               # S1-W1
    src.write_text(doc(episode(1, [shot(1), bad] + [shot(i) for i in range(3, 7)])), encoding="utf-8")
    q = FakeQwen(["<think>x</think>" + shot(2)])
    assert R.main(args(tmp_path, src), ask=q) == 0
    out = (tmp_path / "out.md").read_text(encoding="utf-8")
    assert out == doc(episode(1))
    assert src.read_text(encoding="utf-8") != out                 # 原文不动
    st = json.loads((tmp_path / "repair" / "state.json").read_text(encoding="utf-8"))
    assert st["units"]["ep01-S2"]["status"] == "fixed" and st["units"]["ep01-S2"]["before"] == ["S1-W1"]
    assert len(q.calls) == 1 and "镜2" in q.calls[0] and "S1-W1" in q.calls[0] and "占位剧情" in q.calls[0]
    assert (tmp_path / "repair" / "replies" / "ep01-S2_r1.txt").exists()


def test_dialogue_change_rejected_original_kept(tmp_path):
    src = tmp_path / "in.md"
    bad = shot(2, motion_end=False)
    text = doc(episode(1, [shot(1), bad] + [shot(i) for i in range(3, 7)]))
    src.write_text(text, encoding="utf-8")
    altered = shot(2, line="占位台词改。")                       # 格式对了，但台词被改
    q = FakeQwen([altered, altered, altered])
    R.main(args(tmp_path, src, "--max-rounds", "3"), ask=q)
    assert (tmp_path / "out.md").read_text(encoding="utf-8") == text
    u = json.loads((tmp_path / "repair" / "state.json").read_text(encoding="utf-8"))["units"]["ep01-S2"]
    assert u["status"] == "unchanged" and len(u["rejects"]) == 3 and "对白" in u["rejects"][0]
    assert "上一次的回复没有被采用" in q.calls[1]


def test_added_dialogue_rejected():
    import ns_agent.importer.script_md as M  # noqa: F401
    old = type("S", (), {"dialogue": [], "dialogue_raw": "", "voiceover": None, "duration": 10})()
    D = type("D", (), {})
    d = D(); d.text, d.speaker_note = "新台词。", "她"
    new = type("S", (), {"dialogue": [d], "dialogue_raw": "（她）“新台词。”", "voiceover": None, "duration": 10})()
    assert "新增" in R.dialogue_check(old, new, False)


def test_mechanical_alignment_fix_without_qwen(tmp_path):
    src = tmp_path / "in.md"
    bad = shot(1, seconds=8, h3_text=h3(seconds=8, align_seconds=10))   # H3-A1 only
    src.write_text(doc(episode(1, [bad] + [shot(i) for i in range(2, 7)])), encoding="utf-8")
    q = FakeQwen([])
    R.main(args(tmp_path, src), ask=q)
    assert q.calls == []
    st = json.loads((tmp_path / "repair" / "state.json").read_text(encoding="utf-8"))
    assert st["units"]["ep01-S1"]["status"] == "fixed" and st["mechanical"]
    out = (tmp_path / "out.md").read_text(encoding="utf-8")
    assert alignment_line(frames_for_seconds(8)) in out


def test_resume_skips_done_units(tmp_path):
    src = tmp_path / "in.md"
    ep1 = episode(1, [shot(1, motion_end=False)] + [shot(i) for i in range(2, 7)])
    ep2 = episode(2, [shot(1, motion_end=False)] + [shot(i) for i in range(2, 7)])
    src.write_text(doc(ep1, ep2), encoding="utf-8")
    R.main(args(tmp_path, src, "--episodes", "1"), ask=FakeQwen([shot(1)]))
    st = json.loads((tmp_path / "repair" / "state.json").read_text(encoding="utf-8"))
    assert st["episodes_done"] == [1]
    q = FakeQwen([shot(1)])
    R.main(args(tmp_path, src, "--resume"), ask=q)
    assert len(q.calls) == 1 and "ep02" in q.calls[0]
    assert (tmp_path / "out.md").read_text(encoding="utf-8") == doc(episode(1), episode(2))
    # 续跑但不在同一集内重复：同一单元已有状态则跳过
    st = json.loads((tmp_path / "repair" / "state.json").read_text(encoding="utf-8"))
    st["episodes_done"] = [1]
    (tmp_path / "repair" / "state.json").write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    q2 = FakeQwen([])
    R.main(args(tmp_path, src, "--resume"), ask=q2)
    assert q2.calls == []


def test_head_repair_adds_bgm(tmp_path):
    src = tmp_path / "in.md"
    text = doc(episode(1)).replace("**配乐**：占位配乐说明；【BGM】Placeholder BGM prompt with soft piano.\n\n", "")
    src.write_text(text, encoding="utf-8")
    reply = "## ep01《占位标题1》\n\n**剧情**：占位剧情。\n\n**配乐**：占位；【BGM】Placeholder BGM with piano."
    q = FakeQwen([reply])
    R.main(args(tmp_path, src), ask=q)
    st = json.loads((tmp_path / "repair" / "state.json").read_text(encoding="utf-8"))
    assert st["units"]["ep01-head"]["status"] == "fixed"
    assert "【BGM】Placeholder BGM with piano." in (tmp_path / "out.md").read_text(encoding="utf-8")


def test_dry_run_writes_nothing(tmp_path):
    src = tmp_path / "in.md"
    src.write_text(doc(episode(1, [shot(1, motion_end=False)] + [shot(i) for i in range(2, 7)])), encoding="utf-8")
    q = FakeQwen([])
    assert R.main(args(tmp_path, src, "--dry-run"), ask=q) == 0
    assert q.calls == [] and not (tmp_path / "out.md").exists()


def test_abliteration_backend_reads_config(tmp_path, monkeypatch):
    """G8：写作后端可配置，abliteration 读 config/abliteration.local.json，请求带 model 与 Bearer"""
    import json as _json
    cfg = tmp_path / "a.json"   # R = 文件顶部按路径加载的 tools/qwen_repair_loop.py
    cfg.write_text(_json.dumps({"base_url": "https://x.test/v1/", "model": "m-v2", "api_key": "k"}), encoding="utf-8")
    seen = {}

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return _json.dumps({"choices": [{"message": {"content": "OUT", "reasoning": "R"}}]}).encode()

    def fake(req, timeout=0):
        seen["url"], seen["auth"], seen["body"] = req.full_url, req.headers.get("Authorization"), _json.loads(req.data)
        return Resp()
    monkeypatch.setattr(R.urllib.request, "urlopen", fake)
    a = R.Abliteration(False, 0.3, 10, cfg_path=cfg)
    out = a("sys", "user")
    assert out == "<think>R</think>\nOUT"
    assert seen["url"] == "https://x.test/v1/chat/completions" and seen["auth"] == "Bearer k" and seen["body"]["model"] == "m-v2"
