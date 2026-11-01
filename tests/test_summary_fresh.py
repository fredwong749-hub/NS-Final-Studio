"""DATAALIGN 2026-11-01（总调度 P1）：
1) 按镜缓存单飞——并发请求同一镜同一签名只算一次（重启后头几个 /api/episodes 10 / 18 / 6 s = 各算一遍）；
2) 集摘要同步刷新——takes.json 等逐镜输入变了，/api/episodes/summary 不再等 60 s（D-COUNT：ep03 摘要首帧 0、详情 1）。"""
import threading
import time

from ns_api import episodes_fast as EF
from ns_api import shot_cache as SC


def test_shot_cache_single_flight():
    c = SC.ShotCache()
    calls = []

    def compute():
        calls.append(1)
        time.sleep(0.2)
        return {"v": 1}

    out = []
    ts = [threading.Thread(target=lambda: out.append(c.get("ep01-S1", ("sig",), compute))) for _ in range(6)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(calls) == 1 and len(out) == 6 and all(o is out[0] for o in out)
    c.get("ep01-S1", ("sig2",), compute)          # 签名变了 → 重算
    assert len(calls) == 2


def test_summary_refresh_now_is_synchronous():
    n = {"v": 0}

    def build():
        n["v"] += 1
        return [{"number": 1, "shots": [], "summary": {"first_frames": n["v"]}}]

    c = EF.SummaryCache(build, ttl_s=60.0)
    data, _ = c.get()
    assert data[0]["number"] == 1 and n["v"] == 1
    c.refresh_now()                                # 输入变了：同步重算，返回时已是新一代
    assert n["v"] == 2
    data2, at2 = c.get()
    assert at2 > 0 and n["v"] == 2                 # 新鲜：不再重算


def test_summary_endpoint_refreshes_when_shot_inputs_change(monkeypatch):
    from ns_api import app as APP
    APP.episodes_summary()                         # 冷启动
    for _ in range(600):                           # 等启动预热 / 后台重算结束（它们也会写 built 签名）
        if APP._WARM["done"] and not APP._summary_cache._refreshing:
            break
        time.sleep(0.05)
    monkeypatch.setattr(APP, "_summary_inputs_sig", lambda: ("现在的签名",))   # 不依赖真实目录（别的会话可能正在出图）
    called = []
    monkeypatch.setattr(APP._summary_cache, "refresh_now", lambda *a, **k: called.append(1))
    APP._SUMMARY_SIG["built"] = ("旧签名",)          # 模拟：上次算摘要之后出了新版本（takes.json 变了）
    APP.episodes_summary()
    assert called == [1]
    APP._SUMMARY_SIG["built"] = ("现在的签名",)
    APP.episodes_summary()
    assert called == [1]                           # 签名没变：不重算


def test_snapshot_roundtrip_only_for_same_script(tmp_path, monkeypatch):
    """P2：预热期间用的磁盘快照——剧本文件没变才用，变了就不用（不拿别版剧本的数据顶）"""
    from ns_api import api_snapshot as S
    monkeypatch.setattr(S, "in_tests", lambda: False)        # 写到 tmp_path；真实测试流程里快照一律不写
    script = tmp_path / "script_v2.json"
    script.write_text("{}", encoding="utf-8")
    S._last_write.clear()
    S.save(tmp_path, "episodes", b"[1,2,3]", script)
    for _ in range(50):
        if S.load(tmp_path, "episodes", script):
            break
        time.sleep(0.05)
    body, at = S.load(tmp_path, "episodes", script)
    assert body == b"[1,2,3]" and at > 0
    script.write_text('{"changed": true}', encoding="utf-8")
    assert S.load(tmp_path, "episodes", script) is None


def test_shot_cache_disk_roundtrip(tmp_path):
    """重启后按镜缓存从磁盘读回：签名一致直接命中（不重算），签名变了照常重算"""
    a = SC.ShotCache()
    a.get("ep01-S1", ("sig",), lambda: {"v": 1})
    assert a.dump(tmp_path / "c.pkl") == 1
    b = SC.ShotCache()
    assert b.load(tmp_path / "c.pkl") == 1
    calls = []
    assert b.get("ep01-S1", ("sig",), lambda: calls.append(1) or {"v": 2}) == {"v": 1} and not calls
    assert b.get("ep01-S1", ("sig2",), lambda: calls.append(1) or {"v": 2}) == {"v": 2} and calls == [1]


def test_snapshot_writers_off_in_tests_and_follow_data_dir(tmp_path, monkeypatch):
    """ITERAUDIT 11-01：按镜缓存 / 接口快照的后台写线程在测试里不得启动（会活过测试、写到真实 data/）；路径跟 P.DATA 走"""
    from ns_api import api_snapshot as S
    from ns_api import app as APP
    assert S.in_tests()
    before = {t.name for t in threading.enumerate()}
    APP._SHOT_DUMP["at"] = 0
    APP._dump_shot_cache()
    S.save(tmp_path, "x", b"1", tmp_path / "nope.json")
    assert not ({t.name for t in threading.enumerate()} - before) & {"shot-cache-dump", "snapshot-x"}
    assert not (tmp_path / "cache").exists()
    monkeypatch.setattr(APP.P, "DATA", tmp_path)
    assert APP.shot_cache_file() == tmp_path / "cache" / "api_snapshots" / "shot_cache.pkl"


def test_shot_detail_cached_equals_fresh():
    """总调度 P1（整体卡 15–17 s）：/api/shots/{id} 按镜缓存，缓存结果与现算逐字段相同；第二次命中缓存"""
    import json
    from ns_api import app as APP
    sid = APP._script.episodes[0].shots[0].id
    fresh = APP._shot_detail(sid)
    APP.shot(sid)
    h0 = APP._shot_detail_cache.hits
    cached = APP.shot(sid)
    assert APP._shot_detail_cache.hits == h0 + 1
    strip = lambda d: json.dumps({k: v for k, v in d.items() if k != "summary"}, sort_keys=True, default=str)  # noqa: E731
    assert strip(fresh) == strip(cached)
