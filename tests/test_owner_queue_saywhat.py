"""通知直说（PLAN_OWNER_CHAT 分期 1，L-172 / L-174，A-G3 11-03）：每条待办带 say_what / why / actions[] / block_level；
按钮只打现有入口（/api/owner/decide、/api/owner/pick、页面链接），不另起登记链；只读告知不进 count；要你做的在前。"""
import json
from pathlib import Path

from ns_api import owner_inbox as OI
from ns_api import owner_queue as OQ

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web" / "src"


def _pick(**kw):
    it = {"kind": "pick", "candidates": [], "recommend": None, "pick_api": "/api/owner/pick", "title": "", "detail": "", "link": None}
    it.update(kw)
    return it


def test_decide_says_approve_and_consequence():
    h = OQ.humanize({"id": "r-spend", "kind": "decide", "category": "spend", "title": "买 200 元语音额度", "detail": "配音要用", "link": "#/overview"})
    assert h["say_what"].startswith("需要你批准：买 200 元语音额度") and "不批准" in h["say_what"]
    assert h["block_level"] == "red" and [a["label"] for a in h["actions"]] == ["批准", "要求修改（写一句）", "去对应页面看"]
    assert h["actions"][0]["path"] == "/api/owner/decide" and h["actions"][0]["body"] == {"id": "r-spend", "choice": "approve"}
    assert h["actions"][1]["needs_reason"] is True and h["actions"][1]["body"]["choice"] == "reject"       # 后端口径不变：reject + reason


def test_gate_sentence_and_links():
    h = OQ.humanize({"id": "gate:run:ep02", "kind": "gate", "title": "《透明高跟》第 2 集等你看", "detail": "写好了", "link": "#/script-create?flow=run&anchor=eps"})
    assert h["say_what"] == "看一下《透明高跟》第 2 集的稿子，满意就点“用这版”" and h["block_level"] == "red"
    assert [a["method"] for a in h["actions"]] == ["LINK", "LINK"] and h["actions"][0]["label"] == "去看 · 用这版"
    h = OQ.humanize({"id": "gate:run:P1", "kind": "gate", "title": "《透明高跟》故事线没到门槛，等你定方向", "detail": "x", "link": "#/a"})
    assert h["say_what"].startswith("定一下《透明高跟》故事线的方向")


def test_asset_picks_name_level_and_no_internal_ids():
    cands = [{"key": "s1200", "label": "候选 1（seed 1200）"}, {"key": "s1201", "label": "候选 2（seed 1201）"}]
    h = OQ.humanize(_pick(id="pick:sheet:ch_tang_yao:A", title="挑 唐瑶 造型 A 的设定图（2 选 1）", candidates=cands, recommend={"choice": "s1201", "why": "契约全过"},
                          link="data/review_pages/v2_assets/run/sheet-ch_tang_yao-A", episode=1))
    assert h["say_what"] == "挑唐瑶的造型设定图：2 张候选，推荐第 2 张" and h["block_level"] == "red" and h["sub_kind"] == "sheet"
    assert h["actions"][0] == {"key": "use_rec", "label": "用推荐（第 2 张）", "style": "primary", "method": "POST", "path": "/api/owner/pick",
                               "body": {"id": "pick:sheet:ch_tang_yao:A", "choice": "s1201"}, "href": None, "needs_reason": False}
    assert h["actions"][1]["body"]["choice"] == "revise" and h["actions"][1]["needs_reason"]
    assert h["actions"][2]["method"] == "LINK" and h["actions"][2]["href"].startswith("/data/review_pages/")
    for s in (h["say_what"], h["why"]):
        assert "ch_" not in s and "seed" not in s and "pick:" not in s                                    # 文案规范：无内部 id
    # 派生资产已自动选用 → 黄、开头就说“不用你做事”
    h2 = OQ.humanize(_pick(id="pick:item:ch_tang_yao:A_acc1", title="已自动选用：唐瑶 单品“银色细手链”的图（候选 1（seed 1103）），可修改", candidates=cands[:1],
                           recommend={"choice": "s1200", "why": "系统按分数自动选用"}, auto_picked="s1200"))
    assert h2["say_what"].startswith("不用你做事：系统已替唐瑶选好单品图") and h2["block_level"] == "yellow"
    assert all(a["key"] != "use_rec" for a in h2["actions"])


def test_look_frame_spot_voice():
    h = OQ.humanize(_pick(id="pick:look:run:ep01:abc", title="确认第 1 集造型：卓琳、祁念", candidates=[{"key": "confirm", "label": "确认本集造型"}],
                          recommend={"choice": "confirm", "why": ""}, people=[{"name": "卓琳"}, {"name": "祁念"}], episode=1, link="#/assets"))
    assert h["say_what"] == "确认第 1 集的造型：卓琳、祁念（点一下就行）" and h["actions"][0]["body"]["choice"] == "confirm" and h["block_level"] == "red"
    fr = _pick(id="p-two", title="x", pick_api=None, candidates=[{"key": "a", "label": "v1", "sid": "ep01-S03", "stage": "image", "n": 1}, {"key": "b", "label": "v2", "sid": "ep01-S03", "stage": "image", "n": 2}],
               recommend={"choice": "b", "why": "契约分最高"})
    h = OQ.humanize(fr)
    assert h["say_what"] == "挑第 1 集第 3 镜的首帧：2 张候选，推荐第 2 张（契约分最高）" and h["block_level"] == "red"
    assert h["actions"][0]["path"] == "/api/owner/decide" and h["actions"][0]["body"]["choice"] == "b" and h["actions"][-1]["href"] == "#ep01-S03"
    assert OQ.humanize(fr, delegate_on=True)["block_level"] == "yellow" and "代选" in OQ.humanize(fr, delegate_on=True)["why"]   # 代选开着才许诺“30 分钟代选”
    h = OQ.humanize({"id": "spot:ep01-S03:image:2", "kind": "spot", "sid": "ep01-S03", "stage": "image", "n": 2, "title": "", "detail": ""})
    assert h["say_what"].startswith("看一眼第 1 集第 3 镜第 2 版首帧") and [a["label"] for a in h["actions"]] == ["没问题", "有问题（写原因）"]
    h = OQ.humanize(_pick(id="pick:voice_v2:tang_yao", title="挑一个唐瑶的声音", candidates=[{"key": "a", "label": "a", "audio": "/x.wav"}], recommend={"choice": "a", "why": ""}))
    assert h["say_what"].startswith("挑唐瑶的声音") and h["block_level"] == "yellow"


def test_humanize_never_raises_and_falls_back():
    h = OQ.humanize({"id": "weird", "kind": "pick", "title": None, "candidates": None, "recommend": "not-a-dict"})
    assert h["say_what"] and h["block_level"] in ("red", "yellow", "grey") and isinstance(h["actions"], list)


def test_sort_red_first_then_yellow_then_grey():
    items = [{"block_level": "grey", "kind": "info"}, {"block_level": "yellow", "sub_kind": "spot"}, {"block_level": "red", "sub_kind": "face"}, {"block_level": "red", "kind": "decide"}]
    assert [x.get("sub_kind") or x.get("kind") for x in sorted(items, key=OQ.sort_key)] == ["decide", "face", "spot", "info"]


def test_inbox_readonly_not_counted_and_has_no_buttons(tmp_path, monkeypatch):
    from ns_api import script_library as SLIB
    monkeypatch.setattr(SLIB, "REPO", tmp_path)
    (tmp_path / "config" / "pipeline").mkdir(parents=True)
    (tmp_path / "config" / "pipeline" / "runs.json").write_text('{"runs": {}}', encoding="utf-8")
    monkeypatch.setattr(OI.OQ, "build", lambda root, now=None: {"items": [], "counts": {"decide": 0, "spot": 0, "pick": 0}, "count": 0, "master_waits": {"n": 2, "title": "总调度在定 2 项"}})
    iss = tmp_path / "data" / "pipeline" / "issues.jsonl"
    iss.parent.mkdir(parents=True)
    rows = [{"id": "ISS-1", "event": "open", "time": "2026-11-03 10:00:00", "run": "r", "episode": 1, "who": "ASSET-WORKER", "what": "资产作业 scene-sk_rooftop_bar 连续失败：seed 1200 …", "blocking": True},
            {"id": "ISS-2", "event": "open", "time": "2026-11-03 11:00:00", "who": "X", "what": "不阻断的小事", "blocking": False},
            {"id": "ISS-3", "event": "open", "time": "2026-11-03 12:00:00", "who": "Y", "what": "已关的", "blocking": True}, {"id": "ISS-3", "event": "close", "time": "2026-11-03 12:30:00"}]
    iss.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    r = OI.inbox(tmp_path)
    assert r["count"] == 0 and r["levels"] == {"red": 0, "yellow": 0, "grey": 0}
    ro = r["readonly"]
    assert [x["id"] for x in ro] == ["ro:master_waits", "ro:ISS-1"] and all(x["actions"] == [] and x["block_level"] == "grey" for x in ro)
    assert ro[1]["say_what"].endswith("系统已派 ASSET-WORKER 处理，不需要你做事") and "sk_" not in ro[1]["say_what"]


def test_frontend_cards_read_say_what_and_mount_chat_panel():
    q = (WEB / "v3" / "pages" / "OwnerQueuePage.tsx").read_text(encoding="utf-8")
    assert "it.say_what" in q and "it.why" in q and "block_level" in q and "it.actions" in q
    assert "OwnerChatPanel" in q and "owner-chat-mount" in q                                               # W30 挂点
    css = (WEB / "v3" / "ownerqueue.css").read_text(encoding="utf-8")
    assert "@media (max-width: 720px)" in css                                                              # 手机宽度可用
    ts = (WEB / "v3" / "ownerQueue.ts").read_text(encoding="utf-8")
    assert "say_what" in ts and "block_level" in ts and "readonly" in ts
