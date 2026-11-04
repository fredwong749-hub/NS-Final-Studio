"""W46（W43 第 13 轮：06:02:16 gpu36 S3 回退）——视频登记必须过 C-08 时长核。

现场：vidgen state chosen 换成 v1 变体（另一条 6.58 s 原片）→ register_takes.register 片子门过即 set_active（不核时长）
→ t3（6.58 s）成当前；06:16 trim_takes 裁出的 _le6 与 t2 同 sha → 被当重复跳过、不换回。
修：register 对视频先 c08_video（超 6 s 经 clip_trim 裁，登记裁后片；读不到时长 / 裁后仍超 = C08 fail 不设当前）；
裁后与已登记版同内容 → 原片 sha 记为那版别名（下轮跳过）；trim_takes 遇到这种重复 → 换回那版。
"""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "pipeline"))
sys.path.insert(0, str(ROOT / "tools" / "series10_video"))

import register_takes as RT  # noqa: E402

SHOT = "ep01-S3"


@pytest.fixture
def renders(tmp_path, monkeypatch):
    from ns_render import pipeline as P
    data = tmp_path / "data"
    monkeypatch.setattr(P, "DATA", data)
    monkeypatch.setattr(P, "RENDERS", data / "renders")
    return P, tmp_path


def _clip(p: Path, body: bytes) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(body)
    return p


def _fake_media(monkeypatch, durs: dict[str, float], trims: dict[str, bytes]):
    """时长按文件内容判（拷贝进 takes/ 后仍认得）；裁 = 写 <名>_le6.mp4，内容按原片内容查表"""
    def dur(p):
        return durs.get(Path(p).read_bytes().decode(), 0.0)

    def trim(p):
        p = Path(p)
        body = trims[p.read_bytes().decode()]
        out = p.with_name(p.stem + "_le6.mp4")
        out.write_bytes(body)
        return out
    monkeypatch.setattr(RT, "_dur", dur)
    monkeypatch.setattr(RT, "_trim", trim)


def _item(f: Path, ok=True):
    return {"shot": SHOT, "stage": "video", "file": str(f), "workflow": "video10",
            "postflight": {"ok": ok, "items": [], "reasons": []}}


def _vt(P):
    d = P.load_takes(SHOT)
    return d, [t for t in d["takes"] if t["stage"] == "video"]


def test_short_video_registered_and_current_with_c08_pass(renders, monkeypatch):
    P, tmp = renders
    _fake_media(monkeypatch, {"S": 5.17}, {})
    r = RT.register(_item(_clip(tmp / "clips" / "a.mp4", b"S")), label="VIDEO10 预览片")
    d, vt = _vt(P)
    assert r["status"] == "registered" and r["active"] and d["active"]["video"] == r["n"]
    assert vt[0]["postflight"]["items"][-1] == {"id": "C08", "status": "pass", "detail": "时长 5.170 s（≤ 6.0 s）", "secs": 5.17}


def test_long_video_is_trimmed_before_register(renders, monkeypatch):
    P, tmp = renders
    _fake_media(monkeypatch, {"L": 6.58, "T": 6.0}, {"L": b"T"})
    raw = _clip(tmp / "clips" / "ep01-S3__r24.mp4", b"L")
    r = RT.register(_item(raw), label="VIDEO10 预览片")
    d, vt = _vt(P)
    assert r["status"] == "registered" and r["active"] and d["active"]["video"] == r["n"]
    t = vt[0]
    assert (P.DATA / t["file"]).read_bytes() == b"T"                          # 登记的是裁后片
    o = t["params"]["origin"]
    assert o["src_sha256"] == RT._sha(raw) and o["sha256"] != o["src_sha256"]
    assert t["postflight"]["ok"] and t["postflight"]["items"][-1]["secs"] == 6.0 and "C-08" in t["params"]["label"]
    assert raw.read_bytes() == b"L"                                            # 原片不动
    assert RT.register(_item(raw), label="x")["status"] == "skipped"          # 原片 sha 已认领：下轮不重复登记 / 不重裁


def test_trim_still_long_or_unknown_duration_never_current(renders, monkeypatch):
    P, tmp = renders
    _fake_media(monkeypatch, {"S": 5.0, "L": 6.58, "L2": 6.5}, {"L": b"L2"})
    r0 = RT.register(_item(_clip(tmp / "c" / "ok.mp4", b"S")), label="v")
    r1 = RT.register(_item(_clip(tmp / "c" / "long.mp4", b"L")), label="v")          # 裁后 6.5 s 仍超
    r2 = RT.register(_item(_clip(tmp / "c" / "unk.mp4", b"?")), label="v")           # 读不到时长
    d, vt = _vt(P)
    assert r1["status"] == r2["status"] == "registered" and not r1["active"] and not r2["active"]
    assert d["active"]["video"] == r0["n"]                                            # 当前没被抢
    assert all(t["postflight"]["ok"] is False for t in vt[1:])
    assert "C08" in vt[2]["postflight"]["reasons"][-1]


def test_trim_failure_is_c08_fail(renders, monkeypatch):
    P, tmp = renders
    _fake_media(monkeypatch, {"S": 5.0, "L": 6.58}, {})
    monkeypatch.setattr(RT, "_trim", lambda p: (_ for _ in ()).throw(RuntimeError("ffmpeg boom")))
    RT.register(_item(_clip(tmp / "c" / "ok.mp4", b"S")), label="v")
    r = RT.register(_item(_clip(tmp / "c" / "long.mp4", b"L")), label="v")
    d, vt = _vt(P)
    assert not r["active"] and d["active"]["video"] == 1 and "裁切失败" in vt[1]["postflight"]["items"][-1]["detail"]


def test_variant_trims_to_same_content_as_existing_take_is_alias_not_current(renders, monkeypatch):
    """06:02/06:16 S3 现场：r24 已裁登记 t1（当前）；v1 变体原片不同 sha、裁后与 t1 同内容 → 不新登记、不改当前、记别名"""
    P, tmp = renders
    _fake_media(monkeypatch, {"S": 5.0, "R24": 6.58, "V1": 6.58, "T": 6.0}, {"R24": b"T", "V1": b"T"})
    r1 = RT.register(_item(_clip(tmp / "clips" / "r24.mp4", b"R24")), label="v")
    r_other = RT.register(_item(_clip(tmp / "clips" / "s.mp4", b"S")), label="v")       # 之后别的版成了当前
    assert r1["active"] and r_other["active"]
    v1 = _clip(tmp / "clips" / "v1.mp4", b"V1")
    r = RT.register(_item(v1), label="v")
    d, vt = _vt(P)
    assert r["status"] == "skipped" and r["n"] == r1["n"] and len(vt) == 2
    assert d["active"]["video"] == r_other["n"]                                          # 不挤掉后来的当前
    assert RT._sha(v1) in vt[0]["params"]["origin"]["alias_sha256"]
    assert RT.register(_item(v1), label="v")["reason"] == "已登记（sha256 相同）"         # 下轮直接跳过


def test_no_postflight_video_still_not_activated(renders, monkeypatch):
    P, tmp = renders
    _fake_media(monkeypatch, {"S": 5.0}, {})
    r = RT.register({"shot": SHOT, "stage": "video", "file": str(_clip(tmp / "c" / "a.mp4", b"S"))}, label="v")
    d, _ = _vt(P)
    assert r["status"] == "registered" and "active" not in r and not (d.get("active") or {}).get("video")


def test_trim_takes_reactivates_dup_when_active_is_long(renders, monkeypatch):
    """S3 06:16：当前 t3 = 6.58 s 原片（旧代码登记的）；trim_takes 裁出 == t2 → 换回 t2"""
    P, tmp = renders
    _fake_media(monkeypatch, {"R24": 6.58, "V1": 6.58, "T": 6.0}, {"R24": b"T", "V1": b"T"})
    RT.register(_item(_clip(tmp / "clips" / "r24.mp4", b"R24")), label="v")             # t1 = 裁后 T（当前）
    # 旧代码路径：v1 原片未裁直接登记成 t2 并设当前
    real = RT.c08_video
    monkeypatch.setattr(RT, "c08_video", lambda src: (src, None))
    r_bad = RT.register(_item(_clip(tmp / "clips" / "v1.mp4", b"V1")), label="v")
    monkeypatch.setattr(RT, "c08_video", real)
    assert P.load_takes(SHOT)["active"]["video"] == r_bad["n"] == 2
    spec = importlib.util.spec_from_file_location("trim_takes_c08", ROOT / "tools/series10_video/trim_takes.py")
    TT = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(TT)
    res = TT.fix_shot(SHOT, P, RT, dur=RT._dur, trim=RT._trim)
    assert res["status"] == "reactivated_dup" and res["n"] == 1 and res["from_n"] == 2
    assert P.load_takes(SHOT)["active"]["video"] == 1
    assert TT.fix_shot(SHOT, P, RT, dur=RT._dur, trim=RT._trim)["status"] == "ok"        # 再跑：已合规不动
