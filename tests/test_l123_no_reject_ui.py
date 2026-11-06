"""L-123（项目方 16:4x：“去掉这个逻辑，我不太喜欢什么要这个，不要那个”）：界面里只有正向动作“用这张”和“修改”。
源码级检查：8 个组件里不再有“不要 / 不选 / 已标不要 / ✗ 按钮 / 原因弹框 / 条件说明”，快捷键是 A = 用这张、E = 修改；
“修改”的一句话仍写学习环（/api/edits feedback）。后端 reject 接口保留给系统内部和自动闸门。"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web" / "src"


def read(p: str) -> str:
    return (WEB / p).read_text(encoding="utf-8")


def code_only(src: str) -> str:
    """去掉整行注释后的代码（说明性注释里允许提到旧名字）"""
    return "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith(("//", "/*", "*", "{/*")))


GONE = ("或不要", "✗ 不要", "✗ 已标不要", "不要并重出", "只标记不要", "已标不要", "看完一遍后可通过", "首尾帧都定稿后才能出视频", "先完整播放一遍")


def test_no_reject_wording_in_the_eight_components():
    for f in ("v3/Verdict.tsx", "v3/assets/Verdict.tsx", "v3/ReviewRow.tsx", "v3/CandidateBox.tsx", "v3/edit/EditCenter.tsx",
              "v3/assets/PeopleHub.tsx", "v3/pages/ScenesTab.tsx", "v3/edit/AssetDrawer.tsx", "components/ReviewMode.tsx", "v3/Canvas.tsx", "v3/status.ts", "v3/shotWord.ts"):
        c = code_only(read(f))
        for w in GONE:
            assert w not in c, f"{f} 还有：{w}"
        assert "setRejectFor" not in c or f == "v3/Canvas.tsx" and False, f"{f} 还在打开打回框"
    assert "s.setRejectFor([" not in read("keymap.ts") and 'case "x"' not in read("keymap.ts")


def test_two_actions_only_use_and_edit():
    v = read("v3/Verdict.tsx")
    assert "用这张" in v and "修改" in v and "EditBox" in v and "RejectBox" not in v
    a = read("v3/assets/Verdict.tsx")
    assert "vd-use" in a and "vd-edit" in a and "vd-no" not in a and "RejectDialog" not in a
    e = read("v3/EditBox.tsx")
    assert "换个种子再来" in e and "suggestions" in e


def test_learning_data_still_written_from_edit_sentence():
    a = read("v3/assets/Verdict.tsx")
    assert "/api/edits" in a and "/api/asset-rejects" in a and "feedback: text" in a          # 资产：口径不变
    v = read("v3/Verdict.tsx") + read("v3/Verdict.helpers.ts")                                  # UIUX-LOOP r5：提交逻辑挪到了 Verdict.helpers.ts
    assert "editApi.create" in v and "feedback: text" in v                                     # 镜头（视频）：口径不变
    assert "/frame-edit`" in v                                                                 # 首尾帧：L-123 延伸的永不拒收通道


def test_hotkeys_a_use_e_edit_and_no_watch_gate():
    ec = read("v3/edit/EditCenter.tsx")
    assert '(k === "a" || k === "e")' in ec and "keyAct.current.edit" in ec and '"x"' not in ec.split("L-123：A = 用这张")[1][:400]
    st = read("store.tsx")
    assert "useCallback((s: ShotSummary | undefined) => !!s, [])" in st                        # 没有“看完才能通过”的门槛
    assert "A / E" in read("components/Dialogs.tsx")


def test_delete_only_in_more_menu_and_goes_to_recycle():
    hub = read("v3/assets/PeopleHub.tsx")
    assert hub.count("<MoreMenu") >= 3 and "移到回收区" in hub
    assert 'className="hub-face-del"' not in hub and 'className="hub-item-del"' not in hub


def test_reject_endpoint_kept_for_internal_use():
    src = (ROOT / "services" / "api" / "ns_api" / "asset_actions.py").read_text(encoding="utf-8")
    assert '"/api/assets/{asset_id}/reject"' in src                                            # 保留，界面不再暴露
    assert "/api/assets/" not in code_only(read("v3/assets/Verdict.tsx"))


def test_frames_page_wired_to_topbar_and_old_canvas_kept():
    assert '"#/frames"' in read("v3/TopBarV3.helpers.ts") and "FramesPage" in read("App.tsx")
    top = read("v3/TopBarV3.tsx")
    assert 'label: "出图", to: "#/frames"' in top
    assert '["canvas", "画布（审片 / 精修）"' in top                                            # 旧画布入口保留
    fp = read("v3/pages/FramesPage.tsx")
    assert "/api/frames-index" in fp and "SafeImg" in fp and "onError" in fp and "<Verdict" in fp


def test_owner_queue_cards_only_use_and_edit():
    """W5 UIUX 11-03（L-134 + L-123）：#/queue 的每类卡片（闸门 / 拍板 / 抽检 / 挑选 / 详情）只有“批准 / 用这张”+“修改”；
    后端的“不同意 / 稍后”不渲染成按钮；全局“打回”弹框不再挂载"""
    q = code_only(read("v3/pages/OwnerQueuePage.tsx"))
    for w in GONE + ("不同意", "稍后", "打回", "RejectDialog", "item.options.map("):
        assert w not in q, f"OwnerQueuePage 还有：{w}"
    qa = read("v3/queueActs.ts")
    assert '"批准"' in qa and '"修改"' in qa and '"用这张"' in qa and "LATER" in qa
    app = code_only(read("App.tsx"))
    assert "<RejectDialog" not in app and "RejectDialog," not in app


def test_queue_decide_edit_means_request_change_with_reason():
    """W5b（A5 P2-2）：拍板类（decide）的第二个按钮 = “要求修改 + 一句话理由”，不是“不要了”。
    后端字段（POST /api/owner/decide）：choice = 反向选项 reject，reason = “要求修改：<那句话>”；必须写了那句话才能提交"""
    qa = read("v3/queueActs.ts")
    assert 'label: "要求修改"' in qa and 'prefix: "要求修改："' in qa and 'submit: "提交：要求修改"' in qa
    assert 'it.kind === "decide"' in qa and "DECIDE_EDIT.label" in qa
    assert "export function editReason(" in qa and 'it.kind !== "decide" || !NEG.includes(choice) || !r' in qa
    q = code_only(read("v3/pages/OwnerQueuePage.tsx"))
    assert "editReason(it, choice, reason)" in q                                                # 提交前统一加前缀
    assert "edit.ask ??" in q and "edit.submit ??" in q and "{edit.label}" in q                 # 按钮 / 提示 / 提交文案都跟 queueActs 走
    assert 'disabled={!(said || txt.trim())}' in q                                               # 不写理由交不了
    src = (ROOT / "services" / "api" / "ns_api" / "owner_queue.py").read_text(encoding="utf-8")
    assert '{"key": "reject", "label": "不同意"}' in src and "reason: str = \"\"" in src          # 后端口径没变：choice=reject + reason
