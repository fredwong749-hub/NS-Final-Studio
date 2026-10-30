"""T60：集摘要缓存 + 单集详情（fredw-25）"""
import threading
import time

from ns_api import episodes_fast as EF


def _ep(n, shots):
    return {"number": n, "title": f"t{n}", "high_intensity": False, "tag": "", "synopsis": "s", "edit": {}, "music": {},
            "audio_supported": True, "readiness": {"ready": 1, "total": len(shots)}, "explicit_hold_count": 0, "shots": shots}


def _shot(i, **kw):
    return {"id": f"ep01-S{i}", "index": i, "review": {"state": "passed" if i == 1 else "unreviewed"},
            "first_frame": "/f.png", "video": "/v.mp4" if i == 1 else None, "duration": {"seconds": 8, "source": "script"},
            "h3_lint": ["很大"] * 50, "image_prompt": "长", "expression": {"text": "x", "source": "auto", "cues": []},
            "characters": [{"character": "lin_wan", "name": "林晚", "face_url": "/a", "slots": [1, 2], "conflicts": []}], **kw}


def test_light_episode_projection():
    e = EF.light_episode(_ep(1, [_shot(1), _shot(2)]))
    assert e["light"] is True
    assert e["summary"] == {"shots": 2, "ready": 1, "seconds": 16, "first_frames": 2, "videos": 1, "passed": 1}
    s = e["shots"][0]
    assert "h3_lint" not in s and "image_prompt" not in s
    assert s["expression"] == {"source": "auto"}
    assert s["characters"] == [{"character": "lin_wan", "name": "林晚", "face_url": "/a", "look_id": None,
                                "look_label": None, "look_name": None, "d_state": None}]


def test_cache_cold_then_stale_while_revalidate():
    calls = []

    def build():
        calls.append(time.time())
        time.sleep(0.05)
        return [_ep(1, [_shot(1)])]

    c = EF.SummaryCache(build, ttl_s=0.1)
    data, at = c.get()                       # 冷启动同步算
    assert len(calls) == 1 and data[0]["number"] == 1
    data2, at2 = c.get()                     # 新鲜：不重算
    assert len(calls) == 1 and at2 == at
    time.sleep(0.15)
    t = time.perf_counter()
    c.get()                                  # 过期：立即返回旧值，后台重算
    assert time.perf_counter() - t < 0.04
    time.sleep(0.15)
    assert len(calls) == 2


def test_cache_concurrent_cold_requests_build_once():
    calls = []

    def build():
        calls.append(1)
        time.sleep(0.1)
        return [_ep(1, [_shot(1)])]

    c = EF.SummaryCache(build)
    ts = [threading.Thread(target=c.get) for _ in range(5)]
    [t.start() for t in ts]
    [t.join(3) for t in ts]
    assert len(calls) == 1


def _diff_paths(a, b, path=""):
    if isinstance(a, dict) and isinstance(b, dict):
        return [p for k in set(a) | set(b) if a.get(k) != b.get(k) for p in _diff_paths(a.get(k), b.get(k), f"{path}.{k}")]
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        return [p for i, (x, y) in enumerate(zip(a, b)) if x != y for p in _diff_paths(x, y, f"{path}[{i}]")]
    return [path]


def test_detail_matches_legacy_and_summary_endpoint():
    """单集接口与旧接口同一集逐字相同。用的是真实数据：两次计算相隔约 2–3 s，期间别的会话（gpu3 同步等）
    可能刚好写入，所以不一致时重试，3 次都不一致才算失败（封板修复：原来偶发失败）"""
    from ns_api import app as APP
    diffs = []
    for _ in range(3):
        full = APP.episodes()
        one = APP.episode_detail(full[0]["number"])
        if one == full[0]:
            break
        diffs = _diff_paths(full[0], one)
    else:
        raise AssertionError(f"单集与旧接口 3 次都不一致：{diffs[:10]}")
    s = APP.episodes_summary()
    assert [e["number"] for e in s["episodes"]] == [e["number"] for e in full]
    assert all(e["light"] for e in s["episodes"])


def test_spa_serves_root_static_files_and_blocks_traversal():
    from fastapi.testclient import TestClient
    from ns_api import app as APP
    if not APP.WEB_DIST.exists():
        return
    c = TestClient(APP.app)
    if (APP.WEB_DIST / "favicon.svg").exists():
        assert c.get("/favicon.svg").headers["content-type"].startswith("image/svg")
    assert c.get("/some/route").headers["content-type"].startswith("text/html")
    assert c.get("/..%2F..%2Fpyproject.toml").headers["content-type"].startswith("text/html")
    assert c.get("/api/nope").status_code == 404


def test_script_change_resets_look_store_script(monkeypatch):
    """封板修复：剧本重新导入后，造型模块缓存的剧本也要换掉"""
    from ns_api import app as APP
    from ns_agent.looks import default_store
    store = default_store()
    store._script = "旧剧本"
    called = []
    monkeypatch.setattr(APP._summary_cache, "invalidate", lambda: called.append(1))
    APP._on_script_changed()
    assert store._script is None and called == [1]
    assert store.script.episodes  # 下次访问按磁盘上的剧本重读
