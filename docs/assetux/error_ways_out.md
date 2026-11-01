# “只报错不给出路”检查（ASSETUX，2026-11-01）

- 起因（项目方 11-01 截图 Screenshot 2026-11-01 003559.png）：“这里的报错，我不知道怎么样修改呀？这个是逻辑上的问题吗？我想添加一些衣服到我的库里面去。”
  添加单品时弹框只写红字“这张图已经是单品‘黑色漆皮细带捆绑内衣（平铺，深色背景）’了”。那件单品在折叠的“以前登记的单品”里，项目方看不到，弹框也没有给下一步。
- 规则：knowledge/rules/ui.yaml K-UI-029。提示 = 一句人话说明 + 一键解决（主按钮）+ 需要时的替代路径（次按钮）。只有确实没法自动解决时，才写“去哪里做什么”，并给链接。

## 一、资产中心（ASSETUX 负责，已改）

| 位置 | 改前 | 改后 |
|---|---|---|
| 添加单品：图已在库里 | 红字“这张图已经是单品…了” | 选图后先查库（不写数据），显示“这件已经在 林晚 的库里”，附缩略图、名字和所在位置（当前衣橱 / 以前登记的单品）。<br>主按钮“用这件，挂到造型 B”：一键放进当前衣橱并挂到造型，10 秒内可撤销。<br>次按钮“仍作为新单品添加（另起名）” |
| 添加单品：名称 | 自动填文件名“O12_flatlay_dark_s0” | 图已在库里时，用已有名字。<br>新图由逻辑模型（abliteration，关推理）看图起名，旁边标“看图起的，可以改”，另有“↻ 起个名”按钮可重起。<br>模型不可用时名称留空让人填，不报错 |
| 添加单品：类别 | 必须手动点 | 看图起名时顺便猜类别并自动选上，可以改 |
| 添加单品：上传失败 | 红字 | 黄色说明 + “再试一次”。如果是刚有人登记了同一张图，自动转成“用这件” |
| 点选失败（换身份脸 / 设定图 / 挂造型 / 改名） | 提示条“没成功：…” | 提示条“没成功：…。数据没改动，可以再试一次”，带“再试一次”按钮 |
| 删除单品被拦（还在造型 / 排期里用着） | “删不了：…” | 写明被拦的原因，提示“先在上面的造型里点 A/B/C 把它拿下，再删”，带“再试一次” |
| 旧剧单品被当前剧用到 | 只能在折叠区里找 | 挂到任意造型或点“用这件”后，自动出现在当前衣橱 |

## 二、全站其他地方（扫描结果，交给 UIRSI 和各页负责人按同一规则改）

- 扫描方法：在 apps/web/src 里搜 store.notify 的错误提示（`, "err")`），共 46 处。
- 现状：每处都只有一行“动作 + 失败原因”，没有按钮。
- 建议统一做法：
  - store.notify 加一个可选 action（{label, run}），错误提示至少带“再试一次”。
  - 能判断原因的，给针对性出路。例：“先把这版视频看完再通过”配“从头播放”按钮。
  - “需要项目方本人勾选确认”这类提示，登录后点一下就该直接生效，不该再出现。

| 位置 | 现在的提示 |
|---|---|
| apps/web/src/components/LooksSection.tsx:50 | notify('造型修改失败：${(e as Error).message}', "err"); |
| apps/web/src/components/ShotCard.tsx:390 | st.notify('上传失败：${(e as Error).message}', "err"); |
| apps/web/src/components/ShotTable.tsx:75 | const d = st.details[s.id] ?? (await api.shot(s.id).catch((e: Error) => void st.notify('${s.id} 加载失败：${e.messa |
| apps/web/src/keymap.ts:143 | if (usesGpu3Chain(s.details[sel])) return handled(), s.notify("gpu3 负责此镜：当前版本由 gpu3 决定（画布只看 / 对比）", "err"); |
| apps/web/src/keymap.ts:173 | if (!LOCK_SUPPORTED) s.notify("锁定接口待后端提供", "err"); |
| apps/web/src/store.tsx:1001 | notify('切换失败：${(e as Error).message}', "err"); |
| apps/web/src/store.tsx:1033 | if (bad.length) notify('未能标记：${bad.join("；")}', "err"); |
| apps/web/src/store.tsx:571 | notify('${j.shot_id} ${STAGE_LABEL[j.stage]}渲染失败', "err"); |
| apps/web/src/store.tsx:677 | notify('${id} 保存失败：${(e as Error).message}', "err"); |
| apps/web/src/store.tsx:724 | notify('本集加强保存失败：${(e as Error).message}', "err"); |
| apps/web/src/store.tsx:756 | if (summaryById.get(id)?.explicit_hold) return notify('${id}：${EXPLICIT_LABEL}，不做自动重出', "err"); |
| apps/web/src/store.tsx:766 | notify('${id} 发给 gpu3 失败：${(e as Error).message}', "err"); |
| apps/web/src/store.tsx:788 | notify('${id}：${EXPLICIT_LABEL}，不做自动出图', "err"); |
| apps/web/src/store.tsx:800 | notify('${id} 提交失败：${(e as Error).message}', "err"); |
| apps/web/src/store.tsx:865 | notify('批量提交失败：${(e as Error).message}', "err"); |
| apps/web/src/store.tsx:947 | if (expired.length) notify('已请 gpu3 超过 6 小时仍无新版本：${expired.join("、")}（标记已撤，可再请一次）', "err"); |
| apps/web/src/store.tsx:980 | if (summaryById.get(id)?.explicit_hold) return notify('${id}：${EXPLICIT_LABEL}，不做自动出图', "err"); |
| apps/web/src/v3/EpisodeProduce.tsx:191 | notify('取消失败：${(e as Error).message}', "err"); |
| apps/web/src/v3/EpisodeProduce.tsx:273 | notify('整集出片没开始：${/Failed to fetch／NetworkError/i.test((e as Error).message) ? "后台服务没响应（Failed to fetch），稍后重试" |
| apps/web/src/v3/candidates.ts:70 | notify('${name} 没设成：${(e as Error).message}', "err"); |
| apps/web/src/v3/edit/AssetDrawer.tsx:314 | studio.notify('加参考：${errText(e, "W5 /assets/{id}/refs")}', "err"); |
| apps/web/src/v3/edit/AssetDrawer.tsx:325 | studio.notify('去掉参考：${errText(e, "W5 DELETE /refs")}', "err"); |
| apps/web/src/v3/edit/AssetDrawer.tsx:352 | studio.notify("只能拖图片进来", "err"); |
| apps/web/src/v3/edit/AssetDrawer.tsx:387 | studio.notify('生成：${errText(e, "W5 /assets/{id}/gen-jobs")}', "err"); |
| apps/web/src/v3/edit/AssetDrawer.tsx:408 | studio.notify('定稿底图：${sceneNotReady(e) ? "后端未就绪（/api/assets/scenes/{id}/plate）" : (e as Error).message}', "err |
| apps/web/src/v3/edit/AssetDrawer.tsx:420 | studio.notify('取消定稿：${(e as Error).message}', "err"); |
| apps/web/src/v3/edit/AssetDrawer.tsx:428 | if (save === "episode" && !owner) return studio.notify("设为本集默认需要项目方本人勾选确认", "err"); |
| apps/web/src/v3/edit/AssetDrawer.tsx:460 | studio.notify('保存：${errText(e, "W5 /assets/{id}/versions")}', "err"); |
| apps/web/src/v3/edit/EditCenter.tsx:197 | if (!vidCur) return notify('现在看的是视频 #${cur.n}，不是本镜在用的那版；先在版本条里选回在用的版本再通过', "err"); |
| apps/web/src/v3/edit/EditCenter.tsx:198 | if (!watched) return notify("先把这版视频完整看一遍再通过（拖到结尾也算）", "err"); |
| apps/web/src/v3/edit/EditCenter.tsx:244 | if (gate) return notify(gate, "err"); |
| apps/web/src/v3/edit/EditCenter.tsx:251 | if (g) return notify(g, "err"); |
| apps/web/src/v3/edit/EditCenter.tsx:264 | if (!ch) return notify("本镜没有出场人物，先在资产页选资产", "err"); |
| apps/web/src/v3/edit/EditCenter.tsx:287 | () => void navigator.clipboard?.writeText(cur?.prompt ?? "").then(() => notify("已复制"), () => notify("复制失败", "e |
| apps/web/src/v3/edit/RefSwitchPanel.tsx:147 | if (scope === "episode" && !owner) return studio.notify("改本集默认需要项目方本人勾选确认", "err"); |
| apps/web/src/v3/edit/RefSwitchPanel.tsx:177 | studio.notify('应用：${errText(e, "W5 /refs/apply")}', "err"); |
| apps/web/src/v3/edit/RightTabs.tsx:165 | studio.notify('导演加强：${(e as Error).message}', "err"); |
| apps/web/src/v3/edit/RightTabs.tsx:553 | studio.notify('上传首帧失败：${(err as Error).message}', "err"); |
| apps/web/src/v3/edit/actions.ts:105 | notify('定稿：${isNotReady(e) ? "后端未就绪（W2 /takes/…/lock）" : (e as Error).message}', "err"); |
| apps/web/src/v3/edit/actions.ts:34 | notify('${label}：${errText(e, "W2 /frame-jobs")}', "err"); |
| apps/web/src/v3/edit/actions.ts:64 | notify('出视频：${errText(e, "W3 /video-jobs")}', "err"); |
| apps/web/src/v3/pages/AssetsPage.tsx:205 | if (ch.looks.some((l) => letterOf(ch, l) === letter)) return studio.notify('形象 ${letter} 已经有了，换一个字母', "err"); |
| apps/web/src/v3/pages/AssetsPage.tsx:231 | studio.notify('新建形象：${errText(e)}', "err"); |
| apps/web/src/v3/pages/AssetsPage.tsx:252 | studio.notify('上传图：${errText(e)}', "err"); |
| apps/web/src/v3/pages/CutPage.tsx:120 | st.notify('合成没开始：${String((e as Error).message ?? e)}', "err"); |
| apps/web/src/v3/pages/ScenesTab.tsx:161 | onErr={(m) => studio.notify(m, "err")} |
