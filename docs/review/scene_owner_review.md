# 场景/房屋归属复核（scene owner review）

> 2026-10-30 · 只读复核，未改任何代码与数据。来源：`data/state_timeline.json`（generated_at 2026-10-30T11:57:27，script v2，sha f5aff2f8…）、`data/scenes.json`、`data/import/script_v2.json`、`script play lib/为他而骚 （剧本和镜头）v2.md`。

> 只看地点/房间相关字句；原文引用均已避开情节性内容。

## 0. 范围与结论

- `home_owner_source` 不是 `explicit` 的镜头共 **134** 个（50 个段落）：`characters` 57、`room_history` 22、`episode` 55。任务里说的 79 个 = characters + room_history；`episode`（沿用本集上一段的归属）同样是推断，一并复核。
- **建议改动 19 个**：换房屋归属 13 个（顾沉家 ⇄ 出租屋，或出租屋 → 餐厅），房屋不变只换房间 6 个；**保持 115 个**（高置信 103，中置信 12）。
- 没有判为“低”的条目；“中”的都在第 1 节标出，需要项目方拍板的放在第 5 节。
- 推断集合之外顺带发现 4 个地点明显错并的镜头（第 2 节末），以及若干重复/错并场景（第 3 节）。
- 生成器目前没有读取覆盖文件的入口（`state_timeline.py` 里没有 overrides 逻辑），第 2 节的 JSON 需要另行接入。

### 改动汇总

| 镜头 | 现在 | 建议 | 置信度 |
|---|---|---|---|
| ep02-S6 | 出租屋衣帽间 | 出租屋卧室 | 中 |
| ep14-S6 | 顾沉家卧室 | 出租屋卧室 | 高 |
| ep20-S5 | 出租屋衣帽间 | 出租屋卧室 | 高 |
| ep29-S5 | 出租屋卧室 | 顾沉家卧室 | 中 |
| ep29-S6 | 出租屋卧室 | 顾沉家卧室 | 中 |
| ep39-S1 | 顾沉家浴室 | 顾沉家客厅 | 中 |
| ep39-S2 | 顾沉家浴室 | 顾沉家客厅 | 中 |
| ep39-S3 | 顾沉家浴室 | 顾沉家客厅 | 中 |
| ep39-S4 | 顾沉家浴室 | 顾沉家客厅 | 中 |
| ep53-S1 | 顾沉家浴室 | 出租屋浴室 | 中 |
| ep53-S2 | 顾沉家浴室 | 出租屋浴室 | 中 |
| ep53-S3 | 顾沉家浴室 | 出租屋浴室 | 中 |
| ep53-S4 | 顾沉家浴室 | 出租屋浴室 | 中 |
| ep53-S5 | 顾沉家客厅 | 出租屋客厅 | 中 |
| ep53-S6 | 顾沉家客厅 | 出租屋客厅 | 中 |
| ep54-S5 | 出租屋浴室 | 高级餐厅 | 高 |
| ep60-S4 | 出租屋玄关 | 顾沉家玄关 | 高 |
| ep60-S5 | 出租屋玄关 | 顾沉家玄关 | 高 |
| ep60-S6 | 出租屋玄关 | 顾沉家玄关 | 高 |

## 1. 逐镜复核表

当前判断 = `place`（`home_owner_source`）。episode = 沿用本集上一段；characters = 按入镜人物（顾沉方 / 陈宇）；room_history = 该房间上一次的归属。

| shot_id | 当前判断 | 建议 | 置信度 | 依据原文 |
|---|---|---|---|---|
| ep01-S5 | 出租屋厨房（episode） | 保持 | 高 | 同集镜4「夜晚出租屋餐桌」同一夜，镜5「厨房水槽前…洗碗」 |
| ep01-S6 | 出租屋卧室（episode） | 保持 | 高 | 镜4起同夜在出租屋；「晚间卧室床上，陈宇熟睡的侧脸」 |
| ep02-S6 | 出租屋衣帽间（episode） | **改 → 出租屋卧室** | 中 | 房屋=出租屋无疑（镜5「出租屋玄关」）；但原文是「深夜衣橱内部…旁边挂着她自己的连衣裙」，是卧室衣柜而非衣帽间 |
| ep04-S5 | 出租屋卧室（episode） | 保持 | 高 | 镜1-4「出租屋餐桌」；镜5「卧室，陈宇睡熟的侧脸」 |
| ep04-S6 | 出租屋卧室（episode） | 保持 | 高 | 镜1-4「出租屋餐桌」；镜5「卧室，陈宇睡熟的侧脸」 |
| ep05-S1 | 顾沉家衣帽间（characters） | 保持 | 高 | ep28镜2写明「顾沉家衣帽间：那件挂了八年的黑漆皮束腰」，与本集镜2顾沉台词「挂了八年」呼应；镜1「一整墙克制的深色西装」 |
| ep05-S2 | 顾沉家衣帽间（characters） | 保持 | 高 | ep28镜2写明「顾沉家衣帽间：那件挂了八年的黑漆皮束腰」，与本集镜2顾沉台词「挂了八年」呼应；镜1「一整墙克制的深色西装」 |
| ep05-S3 | 顾沉家衣帽间（characters） | 保持 | 高 | ep28镜2写明「顾沉家衣帽间：那件挂了八年的黑漆皮束腰」，与本集镜2顾沉台词「挂了八年」呼应；镜1「一整墙克制的深色西装」 |
| ep05-S4 | 顾沉家衣帽间（characters） | 保持 | 高 | ep28镜2写明「顾沉家衣帽间：那件挂了八年的黑漆皮束腰」，与本集镜2顾沉台词「挂了八年」呼应；镜1「一整墙克制的深色西装」 |
| ep05-S5 | 顾沉家衣帽间（characters） | 保持 | 高 | ep28镜2写明「顾沉家衣帽间：那件挂了八年的黑漆皮束腰」，与本集镜2顾沉台词「挂了八年」呼应；镜1「一整墙克制的深色西装」 |
| ep07-S1 | 出租屋卧室（characters） | 保持 | 高 | 剧情《与陈宇的一夜》；「暖黄台灯的卧室，陈宇低头吻她的额头」 |
| ep07-S3 | 出租屋卧室（episode） | 保持 | 高 | 与陈宇同床（台词人为陈宇），同集镜1卧室延续 |
| ep07-S4 | 出租屋卧室（episode） | 保持 | 高 | 与陈宇同床（台词人为陈宇），同集镜1卧室延续 |
| ep07-S5 | 出租屋卧室（episode） | 保持 | 高 | 与陈宇同床（台词人为陈宇），同集镜1卧室延续 |
| ep07-S6 | 出租屋卧室（episode） | 保持 | 高 | 与陈宇同床（台词人为陈宇），同集镜1卧室延续 |
| ep08-S1 | 出租屋卧室（characters） | 保持 | 高 | 「深夜卧室，陈宇睡着」——与陈宇同床即出租屋 |
| ep08-S2 | 出租屋卧室（characters） | 保持 | 高 | 「深夜卧室，陈宇睡着」——与陈宇同床即出租屋 |
| ep08-S3 | 出租屋卧室（characters） | 保持 | 高 | 「深夜卧室，陈宇睡着」——与陈宇同床即出租屋 |
| ep08-S4 | 出租屋卧室（characters） | 保持 | 高 | 「深夜卧室，陈宇睡着」——与陈宇同床即出租屋 |
| ep10-S6 | 出租屋卧室（episode） | 保持 | 高 | 「深夜卧室，陈宇已睡」 |
| ep11-S1 | 出租屋浴室（room_history） | 保持 | 中 | 「深夜浴室，全身镜前」，接ep10（镜1「清晨出租屋」、镜6出租屋卧室）的「愈合第五天」；原文未写房屋，独处在家最合理 |
| ep11-S2 | 出租屋浴室（room_history） | 保持 | 中 | 「深夜浴室，全身镜前」，接ep10（镜1「清晨出租屋」、镜6出租屋卧室）的「愈合第五天」；原文未写房屋，独处在家最合理 |
| ep11-S3 | 出租屋浴室（room_history） | 保持 | 中 | 「深夜浴室，全身镜前」，接ep10（镜1「清晨出租屋」、镜6出租屋卧室）的「愈合第五天」；原文未写房屋，独处在家最合理 |
| ep11-S4 | 出租屋浴室（room_history） | 保持 | 中 | 「深夜浴室，全身镜前」，接ep10（镜1「清晨出租屋」、镜6出租屋卧室）的「愈合第五天」；原文未写房屋，独处在家最合理 |
| ep11-S5 | 出租屋浴室（room_history） | 保持 | 中 | 「深夜浴室，全身镜前」，接ep10（镜1「清晨出租屋」、镜6出租屋卧室）的「愈合第五天」；原文未写房屋，独处在家最合理 |
| ep11-S6 | 出租屋浴室（room_history） | 保持 | 中 | 「深夜浴室，全身镜前」，接ep10（镜1「清晨出租屋」、镜6出租屋卧室）的「愈合第五天」；原文未写房屋，独处在家最合理 |
| ep14-S6 | 顾沉家卧室（episode） | **改 → 出租屋卧室** | 高 | 镜5「她回家路上，出租车窗外的夜」→镜6「深夜卧室，她借着手机微光」，回的是自己家，不是顾沉家 |
| ep16-S4 | 顾沉家浴室（episode） | 保持 | 中 | 镜3「顾沉家，他递来一个丝绒小盒」→镜4「当晚，浴室」，画外「他的声音」且「她，回头看他」，他在场 |
| ep16-S5 | 顾沉家卧室（episode） | 保持 | 中 | 同一晚延续；镜6独白「陈宇今晚打电话来」——她不在陈宇身边，应仍在顾沉家 |
| ep16-S6 | 顾沉家卧室（episode） | 保持 | 中 | 同一晚延续；镜6独白「陈宇今晚打电话来」——她不在陈宇身边，应仍在顾沉家 |
| ep20-S3 | 出租屋浴室（episode） | 保持 | 高 | 剧情「她在家里一个人的“预习”」；镜1「出租屋深夜」→「浴室镜前」 |
| ep20-S4 | 出租屋卧室（episode） | 保持 | 高 | 「床上，她与陈宇的日常」 |
| ep20-S5 | 出租屋衣帽间（episode） | **改 → 出租屋卧室** | 高 | 「睡前她的手机特写…一张他拍的照片——那件漆皮束腰挂在衣帽间」：衣帽间只出现在手机照片里（顾沉家），人在出租屋睡前 |
| ep20-S6 | 出租屋卧室（episode） | 保持 | 高 | 「床头小夜灯下…星空罩着她的床」，独白「陈宇，睡吧」 |
| ep29-S5 | 出租屋卧室（room_history） | **改 → 顾沉家卧室** | 中 | 「他把她拉上床…（他）“我教了你三个月”」——“他”是顾沉不是陈宇，不会在出租屋；原文未写房屋，按顾沉家卧室 |
| ep29-S6 | 出租屋卧室（room_history） | **改 → 顾沉家卧室** | 中 | 「他把她拉上床…（他）“我教了你三个月”」——“他”是顾沉不是陈宇，不会在出租屋；原文未写房屋，按顾沉家卧室 |
| ep31-S3 | 出租屋卧室（episode） | 保持 | 高 | 镜1「出租屋门口…陈宇」，本集与陈宇共度 |
| ep31-S4 | 出租屋卧室（episode） | 保持 | 高 | 镜1「出租屋门口…陈宇」，本集与陈宇共度 |
| ep31-S5 | 出租屋浴室（episode） | 保持 | 高 | 「陈宇沉沉睡去；她轻手轻脚下床…走进浴室」 |
| ep31-S6 | 出租屋浴室（episode） | 保持 | 高 | 「陈宇沉沉睡去；她轻手轻脚下床…走进浴室」 |
| ep33-S2 | 出租屋卧室（episode） | 保持 | 高 | 镜1「出租屋沙发上」；「陈宇亲手架设…手机架上床头」 |
| ep33-S3 | 出租屋卧室（episode） | 保持 | 高 | 镜1「出租屋沙发上」；「陈宇亲手架设…手机架上床头」 |
| ep33-S4 | 出租屋卧室（episode） | 保持 | 高 | 镜1「出租屋沙发上」；「陈宇亲手架设…手机架上床头」 |
| ep33-S5 | 出租屋客厅（episode） | 保持 | 高 | 「客厅沙发的暗处，屏幕的光」，同夜出租屋（陈宇在卧室睡） |
| ep33-S6 | 出租屋客厅（episode） | 保持 | 高 | 「客厅沙发的暗处，屏幕的光」，同夜出租屋（陈宇在卧室睡） |
| ep34-S1 | 出租屋客厅（room_history） | 保持 | 高 | 镜4「看向出租屋卧室的方向」——人在出租屋客厅 |
| ep34-S2 | 出租屋客厅（room_history） | 保持 | 高 | 镜4「看向出租屋卧室的方向」——人在出租屋客厅 |
| ep34-S3 | 出租屋客厅（room_history） | 保持 | 高 | 镜4「看向出租屋卧室的方向」——人在出租屋客厅 |
| ep34-S4 | 出租屋客厅（room_history） | 保持 | 高 | 镜4「看向出租屋卧室的方向」——人在出租屋客厅 |
| ep34-S5 | 出租屋客厅（room_history） | 保持 | 高 | 镜4「看向出租屋卧室的方向」——人在出租屋客厅 |
| ep34-S6 | 出租屋卧室（episode） | 保持 | 高 | 「她回到床上、从背后抱住熟睡的陈宇」 |
| ep36-S1 | 顾沉家书房（characters） | 保持 | 中 | 「夜晚…站在书桌前的顾沉」；同集镜3客厅「小茶几…沙发」为顾沉家；但书桌也可能是他公司办公室 |
| ep36-S2 | 顾沉家书房（characters） | 保持 | 中 | 「夜晚…站在书桌前的顾沉」；同集镜3客厅「小茶几…沙发」为顾沉家；但书桌也可能是他公司办公室 |
| ep36-S3 | 顾沉家客厅（episode） | 保持 | 高 | 「她立于小茶几前…他坐在沙发上」，与ep37/41「顾沉家客厅」陈设一致，ep37即在此开局 |
| ep36-S4 | 顾沉家客厅（episode） | 保持 | 高 | 「她立于小茶几前…他坐在沙发上」，与ep37/41「顾沉家客厅」陈设一致，ep37即在此开局 |
| ep36-S5 | 顾沉家客厅（episode） | 保持 | 高 | 「她立于小茶几前…他坐在沙发上」，与ep37/41「顾沉家客厅」陈设一致，ep37即在此开局 |
| ep36-S6 | 顾沉家客厅（episode） | 保持 | 高 | 「她立于小茶几前…他坐在沙发上」，与ep37/41「顾沉家客厅」陈设一致，ep37即在此开局 |
| ep37-S2 | 顾沉家衣帽间（episode） | 保持 | 高 | 镜1「顾沉家客厅」；「更衣间门帘后…隔着帘，听到顾沉去开门」 |
| ep37-S3 | 顾沉家客厅（episode） | 保持 | 高 | 镜1「顾沉家客厅：布置完成的场地」；「进门与顾沉握手」「单人椅」 |
| ep37-S4 | 顾沉家客厅（episode） | 保持 | 高 | 镜1「顾沉家客厅：布置完成的场地」；「进门与顾沉握手」「单人椅」 |
| ep37-S5 | 顾沉家客厅（episode） | 保持 | 高 | 镜1「顾沉家客厅：布置完成的场地」；「进门与顾沉握手」「单人椅」 |
| ep37-S6 | 顾沉家客厅（episode） | 保持 | 高 | 镜1「顾沉家客厅：布置完成的场地」；「进门与顾沉握手」「单人椅」 |
| ep38-S1 | 顾沉家客厅（characters） | 保持 | 高 | 「软垫圈」「单人椅」与ep37顾沉家客厅布置一致，紧接上集 |
| ep38-S2 | 顾沉家客厅（characters） | 保持 | 高 | 「软垫圈」「单人椅」与ep37顾沉家客厅布置一致，紧接上集 |
| ep38-S3 | 顾沉家客厅（characters） | 保持 | 高 | 「软垫圈」「单人椅」与ep37顾沉家客厅布置一致，紧接上集 |
| ep38-S4 | 顾沉家客厅（characters） | 保持 | 高 | 「软垫圈」「单人椅」与ep37顾沉家客厅布置一致，紧接上集 |
| ep38-S5 | 顾沉家客厅（characters） | 保持 | 高 | 「软垫圈」「单人椅」与ep37顾沉家客厅布置一致，紧接上集 |
| ep38-S6 | 顾沉家客厅（characters） | 保持 | 高 | 「软垫圈」「单人椅」与ep37顾沉家客厅布置一致，紧接上集 |
| ep39-S1 | 顾沉家浴室（characters） | **改 → 顾沉家客厅** | 中 | 房屋=顾沉家无疑；但镜1-4原文无“浴室”，是ep38客厅场的收尾（镜4「顾沉把黑漆皮风衣盖在她身上…Alex蹲下整理物品」），镜5才写「浴室」 |
| ep39-S2 | 顾沉家浴室（characters） | **改 → 顾沉家客厅** | 中 | 房屋=顾沉家无疑；但镜1-4原文无“浴室”，是ep38客厅场的收尾（镜4「顾沉把黑漆皮风衣盖在她身上…Alex蹲下整理物品」），镜5才写「浴室」 |
| ep39-S3 | 顾沉家浴室（characters） | **改 → 顾沉家客厅** | 中 | 房屋=顾沉家无疑；但镜1-4原文无“浴室”，是ep38客厅场的收尾（镜4「顾沉把黑漆皮风衣盖在她身上…Alex蹲下整理物品」），镜5才写「浴室」 |
| ep39-S4 | 顾沉家浴室（characters） | **改 → 顾沉家客厅** | 中 | 房屋=顾沉家无疑；但镜1-4原文无“浴室”，是ep38客厅场的收尾（镜4「顾沉把黑漆皮风衣盖在她身上…Alex蹲下整理物品」），镜5才写「浴室」 |
| ep39-S5 | 顾沉家浴室（characters） | 保持 | 高 | 「浴室：顾沉为她冲洗」「浴室门口的分别」 |
| ep39-S6 | 顾沉家浴室（characters） | 保持 | 高 | 「浴室：顾沉为她冲洗」「浴室门口的分别」 |
| ep40-S1 | 顾沉家浴室（room_history） | 保持 | 高 | 「浴室雾气中：她背靠他胸口、两人共浴」，对顾沉称“老公”——只可能在顾沉家 |
| ep40-S2 | 顾沉家浴室（room_history） | 保持 | 高 | 「浴室雾气中：她背靠他胸口、两人共浴」，对顾沉称“老公”——只可能在顾沉家 |
| ep40-S3 | 顾沉家浴室（room_history） | 保持 | 高 | 「浴室雾气中：她背靠他胸口、两人共浴」，对顾沉称“老公”——只可能在顾沉家 |
| ep40-S4 | 顾沉家浴室（room_history） | 保持 | 高 | 「浴室雾气中：她背靠他胸口、两人共浴」，对顾沉称“老公”——只可能在顾沉家 |
| ep40-S5 | 顾沉家浴室（room_history） | 保持 | 高 | 「浴室雾气中：她背靠他胸口、两人共浴」，对顾沉称“老公”——只可能在顾沉家 |
| ep40-S6 | 顾沉家卧室（episode） | 保持 | 高 | 「浴后的卧室…顾沉站在床边看」 |
| ep41-S5 | 顾沉家衣帽间（episode） | 保持 | 高 | 镜1-4「顾沉家客厅」；「衣帽间：射灯亮起——黑漆皮束腰已挂在原位」 |
| ep42-S3 | 顾沉家衣帽间（episode） | 保持 | 高 | 镜1「顾沉家客厅夜」；「更衣间帘后」「她走出帘子」 |
| ep42-S4 | 顾沉家衣帽间（episode） | 保持 | 高 | 镜1「顾沉家客厅夜」；「更衣间帘后」「她走出帘子」 |
| ep42-S5 | 顾沉家客厅（episode） | 保持 | 高 | 「走到软垫圈中央」「单人椅上的顾沉」 |
| ep42-S6 | 顾沉家客厅（episode） | 保持 | 高 | 「走到软垫圈中央」「单人椅上的顾沉」 |
| ep43-S1 | 顾沉家客厅（characters） | 保持 | 高 | 承接ep42：「单人椅上的顾沉」，软垫圈布置不变 |
| ep43-S2 | 顾沉家客厅（characters） | 保持 | 高 | 承接ep42：「单人椅上的顾沉」，软垫圈布置不变 |
| ep43-S3 | 顾沉家客厅（characters） | 保持 | 高 | 承接ep42：「单人椅上的顾沉」，软垫圈布置不变 |
| ep43-S4 | 顾沉家客厅（characters） | 保持 | 高 | 承接ep42：「单人椅上的顾沉」，软垫圈布置不变 |
| ep43-S5 | 顾沉家客厅（characters） | 保持 | 高 | 承接ep42：「单人椅上的顾沉」，软垫圈布置不变 |
| ep43-S6 | 顾沉家客厅（characters） | 保持 | 高 | 承接ep42：「单人椅上的顾沉」，软垫圈布置不变 |
| ep44-S1 | 顾沉家客厅（characters） | 保持 | 高 | 承接ep43：「锁向单人椅」「单人椅上的顾沉」 |
| ep44-S2 | 顾沉家客厅（characters） | 保持 | 高 | 承接ep43：「锁向单人椅」「单人椅上的顾沉」 |
| ep44-S3 | 顾沉家客厅（characters） | 保持 | 高 | 承接ep43：「锁向单人椅」「单人椅上的顾沉」 |
| ep44-S4 | 顾沉家客厅（characters） | 保持 | 高 | 承接ep43：「锁向单人椅」「单人椅上的顾沉」 |
| ep44-S5 | 顾沉家客厅（characters） | 保持 | 高 | 承接ep43：「锁向单人椅」「单人椅上的顾沉」 |
| ep44-S6 | 顾沉家客厅（characters） | 保持 | 高 | 承接ep43：「锁向单人椅」「单人椅上的顾沉」 |
| ep45-S1 | 顾沉家客厅（characters） | 保持 | 高 | 承接ep44：「当着单人椅的方向」 |
| ep45-S2 | 顾沉家客厅（characters） | 保持 | 高 | 承接ep44：「当着单人椅的方向」 |
| ep45-S3 | 顾沉家客厅（characters） | 保持 | 高 | 承接ep44：「当着单人椅的方向」 |
| ep45-S4 | 顾沉家客厅（characters） | 保持 | 高 | 承接ep44：「当着单人椅的方向」 |
| ep45-S5 | 顾沉家客厅（characters） | 保持 | 高 | 承接ep44：「当着单人椅的方向」 |
| ep45-S6 | 顾沉家客厅（characters） | 保持 | 高 | 承接ep44：「当着单人椅的方向」 |
| ep46-S1 | 顾沉家客厅（characters） | 保持 | 高 | 「她走向单人椅的行进镜…顾沉在椅上」 |
| ep46-S2 | 顾沉家客厅（characters） | 保持 | 高 | 「她走向单人椅的行进镜…顾沉在椅上」 |
| ep46-S3 | 顾沉家客厅（characters） | 保持 | 高 | 「她走向单人椅的行进镜…顾沉在椅上」 |
| ep46-S4 | 顾沉家客厅（characters） | 保持 | 高 | 「她走向单人椅的行进镜…顾沉在椅上」 |
| ep46-S5 | 顾沉家客厅（characters） | 保持 | 高 | 「她走向单人椅的行进镜…顾沉在椅上」 |
| ep46-S6 | 顾沉家客厅（characters） | 保持 | 高 | 「她走向单人椅的行进镜…顾沉在椅上」 |
| ep48-S1 | 顾沉家客厅（characters） | 保持 | 高 | 「散场的客厅…向顾沉和她一一鞠躬告辞」「门廊送别」——主人家是顾沉 |
| ep48-S2 | 顾沉家客厅（characters） | 保持 | 高 | 「散场的客厅…向顾沉和她一一鞠躬告辞」「门廊送别」——主人家是顾沉 |
| ep48-S3 | 顾沉家客厅（characters） | 保持 | 高 | 「散场的客厅…向顾沉和她一一鞠躬告辞」「门廊送别」——主人家是顾沉 |
| ep48-S4 | 顾沉家客厅（characters） | 保持 | 高 | 「散场的客厅…向顾沉和她一一鞠躬告辞」「门廊送别」——主人家是顾沉 |
| ep48-S5 | 顾沉家客厅（characters） | 保持 | 高 | 「散场的客厅…向顾沉和她一一鞠躬告辞」「门廊送别」——主人家是顾沉 |
| ep48-S6 | 顾沉家客厅（characters） | 保持 | 高 | 「散场的客厅…向顾沉和她一一鞠躬告辞」「门廊送别」——主人家是顾沉 |
| ep52-S5 | 出租屋客厅（episode） | 保持 | 高 | 镜1「深夜出租屋床上」，镜4「抓着手机走到客厅」→「客厅：…蜷在沙发一角」 |
| ep52-S6 | 出租屋卧室（episode） | 保持 | 高 | 「她回到床上、重新睡进陈宇臂弯」 |
| ep53-S1 | 顾沉家浴室（room_history） | **改 → 出租屋浴室** | 中 | 镜5「拨给顾沉的动作举了三次没按下去」+镜6「电话那头」——顾沉不在场，不在他家；前后集ep52/ep54都在出租屋。注意原文有「浴缸」 |
| ep53-S2 | 顾沉家浴室（room_history） | **改 → 出租屋浴室** | 中 | 镜5「拨给顾沉的动作举了三次没按下去」+镜6「电话那头」——顾沉不在场，不在他家；前后集ep52/ep54都在出租屋。注意原文有「浴缸」 |
| ep53-S3 | 顾沉家浴室（room_history） | **改 → 出租屋浴室** | 中 | 镜5「拨给顾沉的动作举了三次没按下去」+镜6「电话那头」——顾沉不在场，不在他家；前后集ep52/ep54都在出租屋。注意原文有「浴缸」 |
| ep53-S4 | 顾沉家浴室（room_history） | **改 → 出租屋浴室** | 中 | 镜5「拨给顾沉的动作举了三次没按下去」+镜6「电话那头」——顾沉不在场，不在他家；前后集ep52/ep54都在出租屋。注意原文有「浴缸」 |
| ep53-S5 | 顾沉家客厅（episode） | **改 → 出租屋客厅** | 中 | 同上：「客厅：她抱着膝盖坐在沙发上…拨给顾沉」，是打电话给顾沉，所以是出租屋客厅 |
| ep53-S6 | 顾沉家客厅（episode） | **改 → 出租屋客厅** | 中 | 同上：「客厅：她抱着膝盖坐在沙发上…拨给顾沉」，是打电话给顾沉，所以是出租屋客厅 |
| ep54-S5 | 出租屋浴室（episode） | **改 → 高级餐厅** | 高 | 「餐中细节蒙太奇：他为她布菜…她起身去洗手间时——他替她理了理椅背风衣」，独白「这里这份是烛光」——仍在餐厅，不是出租屋浴室 |
| ep55-S5 | 出租屋阳台（episode） | 保持 | 高 | 镜1「周末出租屋客厅」；「她起身的背影走向阳台」，镜6「身后的出租屋灯光」 |
| ep56-S6 | 出租屋卧室（episode） | 保持 | 高 | 镜1「深夜出租屋」；「她挂了电话回到卧室——重新滑进陈宇被窝」 |
| ep58-S2 | 出租屋浴室（episode） | 保持 | 高 | 镜1「深夜，出租屋：陈宇熟睡」→「她立到浴室全身镜前」 |
| ep58-S3 | 出租屋浴室（episode） | 保持 | 高 | 镜1「深夜，出租屋：陈宇熟睡」→「她立到浴室全身镜前」 |
| ep58-S4 | 出租屋卧室（episode） | 保持 | 中 | 「镜中的她—梳妆台上的“军火库”—卧室方向的、熟睡的陈宇」，与镜1「出租屋…梳妆台」同构；房屋无疑，房间在浴室/卧室之间（见问题） |
| ep58-S5 | 出租屋卧室（episode） | 保持 | 高 | 「她回到床上躺下前」 |
| ep58-S6 | 出租屋卧室（episode） | 保持 | 高 | 「她回到床上躺下前」 |
| ep60-S4 | 出租屋玄关（characters） | **改 → 顾沉家玄关** | 高 | 镜1「顾沉家楼下…他家门前」→镜4「他伸手接过风衣、把漆皮挂上玄关衣架」，镜6「陈宇发来一条消息」——她不在陈宇身边；应是顾沉家玄关，不是出租屋 |
| ep60-S5 | 出租屋玄关（characters） | **改 → 顾沉家玄关** | 高 | 镜1「顾沉家楼下…他家门前」→镜4「他伸手接过风衣、把漆皮挂上玄关衣架」，镜6「陈宇发来一条消息」——她不在陈宇身边；应是顾沉家玄关，不是出租屋 |
| ep60-S6 | 出租屋玄关（characters） | **改 → 顾沉家玄关** | 高 | 镜1「顾沉家楼下…他家门前」→镜4「他伸手接过风衣、把漆皮挂上玄关衣架」，镜6「陈宇发来一条消息」——她不在陈宇身边；应是顾沉家玄关，不是出租屋 |

## 2. 建议覆盖（拟放 `config/scene_overrides.json`，**未创建**，由项目方/负责人决定）

`shots` = 建议改动；`extra_shots` = 推断集合之外发现的错并（地点来源为 inherited/explicit 但明显不对），可选采纳；`confirm_keep` = 高置信保持的镜头，接入后可标为已确认、不再 needs_review。新场景 `sk_gu_chen_entry`（顾沉家玄关）目前不在 scenes.json 里。

```json
{
  "format": "scene_overrides/v1",
  "source_review": "docs/review/scene_owner_review.md",
  "script": "v2",
  "script_sha": "f5aff2f838126a1576835a6a192cb800574409bd5a408b3221148b6494fb12e9",
  "shots": {
    "ep02-S6": {
      "place_key": "rental_bedroom",
      "scene_id": "sk_rental_bedroom",
      "place": "出租屋卧室",
      "home_owner": "rental",
      "confidence": "中",
      "reason": "房屋=出租屋无疑（镜5「出租屋玄关」）；但原文是「深夜衣橱内部…旁边挂着她自己的连衣裙」，是卧室衣柜而非衣帽间"
    },
    "ep14-S6": {
      "place_key": "rental_bedroom",
      "scene_id": "sk_rental_bedroom",
      "place": "出租屋卧室",
      "home_owner": "rental",
      "confidence": "高",
      "reason": "镜5「她回家路上，出租车窗外的夜」→镜6「深夜卧室，她借着手机微光」，回的是自己家，不是顾沉家"
    },
    "ep20-S5": {
      "place_key": "rental_bedroom",
      "scene_id": "sk_rental_bedroom",
      "place": "出租屋卧室",
      "home_owner": "rental",
      "confidence": "高",
      "reason": "「睡前她的手机特写…一张他拍的照片——那件漆皮束腰挂在衣帽间」：衣帽间只出现在手机照片里（顾沉家），人在出租屋睡前"
    },
    "ep29-S5": {
      "place_key": "gu_chen_bedroom",
      "scene_id": "sk_gu_chen_bedroom",
      "place": "顾沉家卧室",
      "home_owner": "gu_chen",
      "confidence": "中",
      "reason": "「他把她拉上床…（他）“我教了你三个月”」——“他”是顾沉不是陈宇，不会在出租屋；原文未写房屋，按顾沉家卧室"
    },
    "ep29-S6": {
      "place_key": "gu_chen_bedroom",
      "scene_id": "sk_gu_chen_bedroom",
      "place": "顾沉家卧室",
      "home_owner": "gu_chen",
      "confidence": "中",
      "reason": "「他把她拉上床…（他）“我教了你三个月”」——“他”是顾沉不是陈宇，不会在出租屋；原文未写房屋，按顾沉家卧室"
    },
    "ep39-S1": {
      "place_key": "gu_chen_living",
      "scene_id": "sk_gu_chen_living",
      "place": "顾沉家客厅",
      "home_owner": "gu_chen",
      "confidence": "中",
      "reason": "房屋=顾沉家无疑；但镜1-4原文无“浴室”，是ep38客厅场的收尾（镜4「顾沉把黑漆皮风衣盖在她身上…Alex蹲下整理物品」），镜5才写「浴室」"
    },
    "ep39-S2": {
      "place_key": "gu_chen_living",
      "scene_id": "sk_gu_chen_living",
      "place": "顾沉家客厅",
      "home_owner": "gu_chen",
      "confidence": "中",
      "reason": "房屋=顾沉家无疑；但镜1-4原文无“浴室”，是ep38客厅场的收尾（镜4「顾沉把黑漆皮风衣盖在她身上…Alex蹲下整理物品」），镜5才写「浴室」"
    },
    "ep39-S3": {
      "place_key": "gu_chen_living",
      "scene_id": "sk_gu_chen_living",
      "place": "顾沉家客厅",
      "home_owner": "gu_chen",
      "confidence": "中",
      "reason": "房屋=顾沉家无疑；但镜1-4原文无“浴室”，是ep38客厅场的收尾（镜4「顾沉把黑漆皮风衣盖在她身上…Alex蹲下整理物品」），镜5才写「浴室」"
    },
    "ep39-S4": {
      "place_key": "gu_chen_living",
      "scene_id": "sk_gu_chen_living",
      "place": "顾沉家客厅",
      "home_owner": "gu_chen",
      "confidence": "中",
      "reason": "房屋=顾沉家无疑；但镜1-4原文无“浴室”，是ep38客厅场的收尾（镜4「顾沉把黑漆皮风衣盖在她身上…Alex蹲下整理物品」），镜5才写「浴室」"
    },
    "ep53-S1": {
      "place_key": "rental_bathroom",
      "scene_id": "sk_rental_bathroom",
      "place": "出租屋浴室",
      "home_owner": "rental",
      "confidence": "中",
      "reason": "镜5「拨给顾沉的动作举了三次没按下去」+镜6「电话那头」——顾沉不在场，不在他家；前后集ep52/ep54都在出租屋。注意原文有「浴缸」"
    },
    "ep53-S2": {
      "place_key": "rental_bathroom",
      "scene_id": "sk_rental_bathroom",
      "place": "出租屋浴室",
      "home_owner": "rental",
      "confidence": "中",
      "reason": "镜5「拨给顾沉的动作举了三次没按下去」+镜6「电话那头」——顾沉不在场，不在他家；前后集ep52/ep54都在出租屋。注意原文有「浴缸」"
    },
    "ep53-S3": {
      "place_key": "rental_bathroom",
      "scene_id": "sk_rental_bathroom",
      "place": "出租屋浴室",
      "home_owner": "rental",
      "confidence": "中",
      "reason": "镜5「拨给顾沉的动作举了三次没按下去」+镜6「电话那头」——顾沉不在场，不在他家；前后集ep52/ep54都在出租屋。注意原文有「浴缸」"
    },
    "ep53-S4": {
      "place_key": "rental_bathroom",
      "scene_id": "sk_rental_bathroom",
      "place": "出租屋浴室",
      "home_owner": "rental",
      "confidence": "中",
      "reason": "镜5「拨给顾沉的动作举了三次没按下去」+镜6「电话那头」——顾沉不在场，不在他家；前后集ep52/ep54都在出租屋。注意原文有「浴缸」"
    },
    "ep53-S5": {
      "place_key": "rental_living",
      "scene_id": "sk_rental_living",
      "place": "出租屋客厅",
      "home_owner": "rental",
      "confidence": "中",
      "reason": "同上：「客厅：她抱着膝盖坐在沙发上…拨给顾沉」，是打电话给顾沉，所以是出租屋客厅"
    },
    "ep53-S6": {
      "place_key": "rental_living",
      "scene_id": "sk_rental_living",
      "place": "出租屋客厅",
      "home_owner": "rental",
      "confidence": "中",
      "reason": "同上：「客厅：她抱着膝盖坐在沙发上…拨给顾沉」，是打电话给顾沉，所以是出租屋客厅"
    },
    "ep54-S5": {
      "place_key": "restaurant",
      "scene_id": "sk_restaurant",
      "place": "高级餐厅",
      "home_owner": null,
      "confidence": "高",
      "reason": "「餐中细节蒙太奇：他为她布菜…她起身去洗手间时——他替她理了理椅背风衣」，独白「这里这份是烛光」——仍在餐厅，不是出租屋浴室"
    },
    "ep60-S4": {
      "place_key": "gu_chen_entry",
      "scene_id": "sk_gu_chen_entry",
      "place": "顾沉家玄关",
      "home_owner": "gu_chen",
      "confidence": "高",
      "reason": "镜1「顾沉家楼下…他家门前」→镜4「他伸手接过风衣、把漆皮挂上玄关衣架」，镜6「陈宇发来一条消息」——她不在陈宇身边；应是顾沉家玄关，不是出租屋"
    },
    "ep60-S5": {
      "place_key": "gu_chen_entry",
      "scene_id": "sk_gu_chen_entry",
      "place": "顾沉家玄关",
      "home_owner": "gu_chen",
      "confidence": "高",
      "reason": "镜1「顾沉家楼下…他家门前」→镜4「他伸手接过风衣、把漆皮挂上玄关衣架」，镜6「陈宇发来一条消息」——她不在陈宇身边；应是顾沉家玄关，不是出租屋"
    },
    "ep60-S6": {
      "place_key": "gu_chen_entry",
      "scene_id": "sk_gu_chen_entry",
      "place": "顾沉家玄关",
      "home_owner": "gu_chen",
      "confidence": "高",
      "reason": "镜1「顾沉家楼下…他家门前」→镜4「他伸手接过风衣、把漆皮挂上玄关衣架」，镜6「陈宇发来一条消息」——她不在陈宇身边；应是顾沉家玄关，不是出租屋"
    }
  },
  "extra_shots": {
    "ep29-S4": {
      "place_key": "gu_chen_bedroom",
      "scene_id": "sk_gu_chen_bedroom",
      "place": "顾沉家卧室",
      "home_owner": "gu_chen",
      "confidence": "中",
      "reason": "「愈合完成的验证日：她跪在他面前」——不是穿孔当天，不在穿孔工作室（当前沿用镜1的穿孔工作室）；与镜5-6同一处"
    },
    "ep28-S1": {
      "place_key": "tattoo_studio",
      "scene_id": "sk_tattoo_studio",
      "place": "纹身店",
      "home_owner": null,
      "confidence": "中",
      "reason": "「纹身最后一台的完工画面」——是纹身店，被并进了镜2「顾沉家衣帽间」所在段"
    },
    "ep08-S6": {
      "place_key": "rental_bedroom",
      "scene_id": "sk_rental_bedroom",
      "place": "出租屋卧室",
      "home_owner": "rental",
      "confidence": "中",
      "reason": "「清晨闹钟响起，她在晨光里睁眼…起身，拉开窗帘」——镜5是梦境里的穿孔工作室，醒来是在家（同集镜1-4出租屋卧室）"
    },
    "ep07-S2": {
      "place_key": "rental_bedroom",
      "scene_id": "sk_rental_bedroom",
      "place": "出租屋卧室",
      "home_owner": "rental",
      "confidence": "中",
      "reason": "「双重曝光构图，现实陈宇的吻，与叠影中电梯里顾沉的吻影」——实景是出租屋卧室，电梯只是叠影素材"
    }
  },
  "confirm_keep": [
    "ep01-S5",
    "ep01-S6",
    "ep04-S5",
    "ep04-S6",
    "ep05-S1",
    "ep05-S2",
    "ep05-S3",
    "ep05-S4",
    "ep05-S5",
    "ep07-S1",
    "ep07-S3",
    "ep07-S4",
    "ep07-S5",
    "ep07-S6",
    "ep08-S1",
    "ep08-S2",
    "ep08-S3",
    "ep08-S4",
    "ep10-S6",
    "ep20-S3",
    "ep20-S4",
    "ep20-S6",
    "ep31-S3",
    "ep31-S4",
    "ep31-S5",
    "ep31-S6",
    "ep33-S2",
    "ep33-S3",
    "ep33-S4",
    "ep33-S5",
    "ep33-S6",
    "ep34-S1",
    "ep34-S2",
    "ep34-S3",
    "ep34-S4",
    "ep34-S5",
    "ep34-S6",
    "ep36-S3",
    "ep36-S4",
    "ep36-S5",
    "ep36-S6",
    "ep37-S2",
    "ep37-S3",
    "ep37-S4",
    "ep37-S5",
    "ep37-S6",
    "ep38-S1",
    "ep38-S2",
    "ep38-S3",
    "ep38-S4",
    "ep38-S5",
    "ep38-S6",
    "ep39-S5",
    "ep39-S6",
    "ep40-S1",
    "ep40-S2",
    "ep40-S3",
    "ep40-S4",
    "ep40-S5",
    "ep40-S6",
    "ep41-S5",
    "ep42-S3",
    "ep42-S4",
    "ep42-S5",
    "ep42-S6",
    "ep43-S1",
    "ep43-S2",
    "ep43-S3",
    "ep43-S4",
    "ep43-S5",
    "ep43-S6",
    "ep44-S1",
    "ep44-S2",
    "ep44-S3",
    "ep44-S4",
    "ep44-S5",
    "ep44-S6",
    "ep45-S1",
    "ep45-S2",
    "ep45-S3",
    "ep45-S4",
    "ep45-S5",
    "ep45-S6",
    "ep46-S1",
    "ep46-S2",
    "ep46-S3",
    "ep46-S4",
    "ep46-S5",
    "ep46-S6",
    "ep48-S1",
    "ep48-S2",
    "ep48-S3",
    "ep48-S4",
    "ep48-S5",
    "ep48-S6",
    "ep52-S5",
    "ep52-S6",
    "ep55-S5",
    "ep56-S6",
    "ep58-S2",
    "ep58-S3",
    "ep58-S5",
    "ep58-S6"
  ]
}
```

### 推断集合之外的错并（已含在 `extra_shots`）

| shot_id | 现在 | 建议 | 置信度 | 依据原文 |
|---|---|---|---|---|
| ep29-S4 | 穿孔工作室（inherited） | 顾沉家卧室 | 中 | 「愈合完成的验证日：她跪在他面前」——不是穿孔当天，不在穿孔工作室（当前沿用镜1的穿孔工作室）；与镜5-6同一处 |
| ep28-S1 | 顾沉家衣帽间（inherited） | 纹身店 | 中 | 「纹身最后一台的完工画面」——是纹身店，被并进了镜2「顾沉家衣帽间」所在段 |
| ep08-S6 | 穿孔工作室（inherited） | 出租屋卧室 | 中 | 「清晨闹钟响起，她在晨光里睁眼…起身，拉开窗帘」——镜5是梦境里的穿孔工作室，醒来是在家（同集镜1-4出租屋卧室） |
| ep07-S2 | 电梯（explicit） | 出租屋卧室 | 中 | 「双重曝光构图，现实陈宇的吻，与叠影中电梯里顾沉的吻影」——实景是出租屋卧室，电梯只是叠影素材 |

## 3. scenes.json：疑似重复 / 错并的场景

| 场景 | 问题 |
|---|---|
| `sk_rental_home`（出租屋，未分房间） | 15 镜是“出租屋”泛称，和具体房间场景重复。按原文应拆开：ep05-S6 / ep27-S6 / ep28-S6（「挂回自己房间的衣架上」）/ ep32-S4~S6 / ep41-S6 / ep58-S1 → 出租屋卧室；ep31-S1、ep54-S3（「出租屋门口」）→ 出租屋玄关；ep49-S6、ep54-S1~S2（「两碗面」「晚餐」）→ 出租屋餐桌；ep10-S1（「清晨出租屋，她对着镜子」）→ 浴室或卧室待定；ep31-S2「室内」待定。 |
| `sk_gu_chen_home`（顾沉家，未分房间） | ep16-S3、ep24-S6、ep27-S5 只写了「顾沉家」，需要定房间（大概率客厅），否则会单独出一张底板。 |
| `sk_rental_closet`（出租屋衣帽间） | 两段都不成立：ep02-S6 是「衣橱内部」（卧室衣柜），ep20-S5 是手机里顾沉家衣帽间的照片。出租屋设定「温馨狭小的家」，ep57 写的是卧室「衣柜」。建议删除此场景。 |
| `sk_rental_entry`（出租屋玄关） | ep60_seg02（ep60-S4~S6）应是顾沉家玄关，错并进来；而 ep31-S1、ep54-S3 的「出租屋门口」在 `sk_rental_home` 里，应并进来。 |
| `sk_gu_chen_gate`（顾沉家楼下） | ep60-S2/S3 原文是「门开：顾沉立在门内」「门内」，已是门槛/玄关，不是楼下；建议与新建的“顾沉家玄关”合并或拆分。 |
| `sk_gu_chen_closet`（顾沉家衣帽间） | 混了两种空间：ep05/28/41 的「高级衣帽间…射灯…一整墙深色西装」与 ep37/42 的「更衣间门帘后」。是否同一房间需确认（第 5 节）。另 ep28-S1 纹身完工画面被并进来。 |
| `sk_rental_bathroom`（出租屋浴室） | ep54_seg03（ep54-S5）是在餐厅起身去洗手间，错并。 |
| `sk_gu_chen_bathroom`（顾沉家浴室） | ep53_seg01（ep53-S1~S4）建议改回出租屋；ep39-S1~S4 应是客厅。改后只剩 ep16-S4、ep39-S5~S6、ep40-S1~S5。 |
| `sk_gu_chen_living`（顾沉家客厅） | ep53_seg02（ep53-S5~S6）建议改回出租屋客厅。 |
| `sk_gu_chen_bedroom` / `sk_rental_bedroom` | ep14_seg04（ep14-S6）应从顾沉家卧室移到出租屋卧室；ep29_seg02（ep29-S5~S6）应从出租屋卧室移到顾沉家卧室。 |
| `sk_piercing_studio`（穿孔工作室） | ep08-S6（醒来拉窗帘）、ep29-S4（验证日）是继承来的，不在工作室。 |
| `sk_elevator`（电梯） | ep07_seg02（ep07-S2）是卧室里的双重曝光，实景不在电梯。 |
| `sk_street` 与 `sk_alley` | ep22–25 两者交替出现，可能是同一条街/巷的两个机位，需确认是否共用一张底板。 |
| `sk_rental_study`（出租屋书房） | 原文只有「出租屋书桌」，小出租屋未必有独立书房；可能是卧室或客厅一角的书桌。 |

## 4. 光线未知（time / key_direction / colour_temp 有空值）

33 个场景里，底板光线（`plate_detail.light`）三项齐全的 13 个；三项全空的 2 个：`sk_counter`、`sk_office_pantry`；部分缺失的 18 个：`sk_rental_dining`、`sk_rental_kitchen`、`sk_rental_closet`、`sk_rental_bathroom`、`sk_gu_chen_closet`、`sk_car`、`sk_rental_study`、`sk_gu_chen_home`、`sk_gu_chen_bathroom`、`sk_banquet`、`sk_subway`、`sk_tattoo_studio`、`sk_office_restroom`、`sk_gu_chen_study`、`sk_canteen`、`sk_rental_balcony`、`sk_restaurant`、`sk_gu_chen_gate`。段落级几乎每个场景都有缺字段的段（见下表），底板生成前需要逐场景定一个主光。

| scene_id | 地点 | 底板光线 time/key/temp | 缺字段的段落 |
|---|---|---|---|
| sk_office_lobby | 写字楼大堂 | morning/side/warm | — |
| sk_elevator | 电梯 | morning/front/neutral | ep01_seg02(time,colour_temp)；ep03_seg01(time)；ep06_seg04(colour_temp)；ep07_seg02(time,key_direction,colour_temp)；ep51_seg01(time,key_direction,colour_temp)；ep59_seg02(time,key_direction,colour_temp) |
| sk_rental_dining | 出租屋餐桌 | night/？/warm | ep01_seg03(key_direction)；ep04_seg01(time,key_direction) |
| sk_rental_kitchen | 出租屋厨房 | night/window/？ | ep01_seg04(colour_temp) |
| sk_rental_bedroom | 出租屋卧室 | night/back/neutral | ep01_seg05(colour_temp)；ep04_seg02(time,key_direction,colour_temp)；ep07_seg01(time,key_direction)；ep07_seg03(time,key_direction)；ep08_seg01(key_direction,colour_temp)；ep10_seg05(key_direction,colour_temp)；ep20_seg03(time,key_direction,colour_temp)；ep20_seg05(key_direction,colour_temp)；ep22_seg01(time,key_direction)；ep29_seg02(time,key_direction,colour_temp)；ep33_seg02(colour_temp)；ep34_seg02(time,key_direction,colour_temp)；ep52_seg01(key_direction,colour_temp)；ep52_seg03(time,colour_temp)；ep56_seg02(time,colour_temp)；ep57_seg01(key_direction) |
| sk_office | 写字楼办公区 | night/side/warm | ep10_seg02(time,key_direction,colour_temp)；ep10_seg04(key_direction,colour_temp)；ep18_seg02(time,colour_temp)；ep18_seg04(time,key_direction,colour_temp)；ep49_seg02(time,key_direction,colour_temp)；ep51_seg02(time,key_direction,colour_temp) |
| sk_taxi | 出租车 | night/window/cool | ep02_seg02(key_direction)；ep14_seg03(colour_temp) |
| sk_rental_entry | 出租屋玄关 | morning/back/warm | ep02_seg03(time,key_direction)；ep59_seg01(key_direction,colour_temp)；ep60_seg02(time,colour_temp) |
| sk_rental_closet | 出租屋衣帽间 | night/top/？ | ep02_seg04(key_direction,colour_temp)；ep20_seg04(colour_temp) |
| sk_street | 街道 | night/back/warm | ep03_seg02(key_direction)；ep09_seg02(time,key_direction)；ep22_seg02(time,key_direction,colour_temp)；ep22_seg04(time,key_direction,colour_temp)；ep23_seg02(time) |
| sk_rental_bathroom | 出租屋浴室 | night/？/warm | ep03_seg03(time,key_direction,colour_temp)；ep06_seg03(key_direction,colour_temp)；ep11_seg01(key_direction)；ep20_seg02(time,key_direction,colour_temp)；ep26_seg02(key_direction,colour_temp)；ep31_seg03(time,key_direction,colour_temp)；ep54_seg03(time,key_direction,colour_temp)；ep58_seg02(time,key_direction,colour_temp) |
| sk_gu_chen_closet | 顾沉家衣帽间 | ？/top/warm | ep05_seg01(time,colour_temp)；ep28_seg01(time,key_direction,colour_temp)；ep37_seg02(time,colour_temp)；ep41_seg02(time,colour_temp)；ep42_seg02(time) |
| sk_rental_home | 出租屋 | night/front/cool | ep10_seg01(key_direction,colour_temp)；ep27_seg03(key_direction,colour_temp)；ep28_seg02(key_direction,colour_temp)；ep31_seg01(time,key_direction)；ep32_seg02(key_direction)；ep41_seg03(key_direction,colour_temp)；ep49_seg05(key_direction,colour_temp)；ep54_seg01(time,key_direction,colour_temp)；ep58_seg01(key_direction,colour_temp) |
| sk_counter | 专柜 | ？/？/？ | ep06_seg01(time,key_direction,colour_temp) |
| sk_car | 豪车车内 | night/window/？ | ep06_seg02(colour_temp)；ep18_seg05(key_direction,colour_temp) |
| sk_piercing_studio | 穿孔工作室 | night/back/cool | ep08_seg02(key_direction)；ep09_seg01(key_direction)；ep15_seg01(time,key_direction)；ep16_seg01(time)；ep29_seg01(time,key_direction,colour_temp) |
| sk_office_pantry | 公司茶水间 | ？/？/？ | ep10_seg03(time,key_direction,colour_temp)；ep18_seg03(time,key_direction,colour_temp) |
| sk_gu_chen_bedroom | 顾沉家卧室 | night/back/warm | ep12_seg01(time,colour_temp)；ep14_seg04(key_direction,colour_temp)；ep16_seg04(key_direction,colour_temp)；ep21_seg01(time)；ep30_seg01(time,colour_temp)；ep32_seg01(time,key_direction,colour_temp)；ep35_seg01(colour_temp)；ep40_seg02(time,key_direction,colour_temp) |
| sk_rental_study | 出租屋书房 | night/？/warm | ep14_seg01(key_direction)；ep20_seg01(key_direction,colour_temp) |
| sk_gu_chen_living | 顾沉家客厅 | night/back/warm | ep14_seg02(time,key_direction,colour_temp)；ep36_seg02(time,key_direction,colour_temp)；ep37_seg01(time,key_direction,colour_temp)；ep37_seg03(time,key_direction,colour_temp)；ep38_seg01(time,colour_temp)；ep41_seg01(time,key_direction,colour_temp)；ep42_seg01(key_direction)；ep42_seg03(time,key_direction)；ep43_seg01(time,colour_temp)；ep44_seg01(time,colour_temp)；ep45_seg01(time)；ep46_seg01(time)；ep47_seg01(time)；ep53_seg02(time,key_direction,colour_temp) |
| sk_gu_chen_home | 顾沉家 | night/？/？ | ep16_seg02(time,key_direction,colour_temp)；ep24_seg02(time,key_direction,colour_temp)；ep27_seg02(key_direction,colour_temp) |
| sk_gu_chen_bathroom | 顾沉家浴室 | night/back/？ | ep16_seg03(colour_temp)；ep39_seg01(time,colour_temp)；ep40_seg01(time,colour_temp)；ep53_seg01(key_direction,colour_temp) |
| sk_banquet | 酒店宴会厅 | ？/top/？ | ep17_seg01(time,colour_temp) |
| sk_subway | 地铁 | morning/？/？ | ep18_seg01(key_direction,colour_temp)；ep49_seg01(key_direction,colour_temp)；ep59_seg03(key_direction,colour_temp) |
| sk_alley | 小巷 | dusk/back/warm | ep22_seg03(time,key_direction,colour_temp)；ep23_seg03(time,key_direction,colour_temp)；ep24_seg01(key_direction)；ep25_seg01(colour_temp) |
| sk_tattoo_studio | 纹身店 | ？/？/cool | ep26_seg01(time,key_direction,colour_temp)；ep27_seg01(time,key_direction) |
| sk_office_restroom | 公司洗手间 | dusk/？/？ | ep30_seg02(time,key_direction,colour_temp)；ep49_seg04(key_direction,colour_temp) |
| sk_rental_living | 出租屋客厅 | night/front/cool | ep33_seg01(time,key_direction,colour_temp)；ep33_seg03(key_direction,colour_temp)；ep34_seg01(time,key_direction,colour_temp)；ep52_seg02(time)；ep55_seg01(time,key_direction,colour_temp)；ep56_seg01(key_direction,colour_temp) |
| sk_gu_chen_study | 顾沉家书房 | night/？/？ | ep36_seg01(key_direction,colour_temp) |
| sk_canteen | 员工食堂 | day/？/？ | ep49_seg03(key_direction,colour_temp) |
| sk_rental_balcony | 出租屋阳台 | night/？/？ | ep50_seg01(time,key_direction,colour_temp)；ep55_seg02(key_direction,colour_temp)；ep55_seg03(time,key_direction,colour_temp) |
| sk_restaurant | 高级餐厅 | ？/back/warm | ep54_seg02(time,key_direction)；ep54_seg04(time,colour_temp) |
| sk_gu_chen_gate | 顾沉家楼下 | night/back/？ | ep60_seg01(colour_temp) |

另：`ep58_seg03`（ep58-S4~S6）整段被标为 morning，因为镜6写了「晨光」，但本集剧情是「深夜全身镜」，镜4-5 应是夜。

## 5. 只有项目方能回答的问题

1. 出租屋浴室有没有浴缸？ep53 原文「泡在浴缸里」。本复核按“拨给顾沉、他在电话那头”判为出租屋；如果出租屋设定没有浴缸，要么出租屋加浴缸，要么 ep53 另有安排。
2. ep29-S4~S6（舌钉愈合后的“验证日”）、ep16-S4~S6（拿到小银铃的当晚）、ep36-S1~S2（书桌前）具体在哪？原文只写“他”“床”“书桌”，本复核按顾沉家处理。ep36 的书桌是顾沉家书房还是他公司办公室？
3. 顾沉家「衣帽间」（ep05/28/41：射灯、整墙西装）和「更衣间门帘」（ep37/42：她在帘后换装，客人在客厅听得见）是不是同一个房间？一张还是两张底板？
4. 出租屋格局：是否有独立书房（ep14/20「出租屋书桌」）、衣帽间（建议没有）、梳妆台在卧室还是浴室（ep58）？
5. ep60 结尾（S4~S6 玄关相拥、桌上手机收到陈宇消息）是否确定在顾沉家？本复核据此建议新建 `sk_gu_chen_entry`（顾沉家玄关）。
6. `sk_street` 和 `sk_alley`（ep22–25）是同一个地方吗？
7. 覆盖文件是否就用 `config/scene_overrides.json` 这个路径/格式，由谁接入 `state_timeline.py`（目前没有读取覆盖的逻辑）？
