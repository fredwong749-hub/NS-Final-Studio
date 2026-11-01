// ASSETUX：单品挂造型“替换哪一项”的判定（node --test；Node 22+ 直接剥类型跑 .ts）。
// 11-01 审计日志：旧逻辑在衣橱卡上点“A”会按槽位自动替换一个部件（超短裙 → 替换“米白衬衫”）。
// 总调度 11-01：默认 = 加为本造型的额外单品，不替换任何已登记部件；只有人明确选了“替换哪一项”才替换。
import { test } from "node:test";
import assert from "node:assert/strict";
import { partFor, nounOf, choicesFor } from "../../src/v3/assets/hub_match.ts";

const part = (slot, label, status = "sheet_only", zone = null) => ({ slot, slot_name: "", label, raw: label, zone, item_id: null, item_name: null, item_image: null, status, extra: false });
const A = { look: "A", parts: [part("outfit", "米白衬衫", "sheet_only", "upper"), part("outfit", "深灰西装裙", "sheet_only", "lower"), part("outfit", "短款西装外套", "missing", "upper"), part("shoes", "透明12cm细高跟", "wardrobe", "feet"), part("accessory", "细银链", "sheet_only", "neck")] };
const B = { look: "B", parts: [part("outfit", "黑色漆皮束腰", "sheet_only", "upper"), part("outfit", "黑色漆皮短裙", "wardrobe", "lower"), part("shoes", "12cm侧开透明细高跟", "wardrobe", "feet"), part("accessory", "九串铁珠", "sheet_only", "waist")] };

test("品类词", () => {
  assert.equal(nounOf("黑色镜面漆皮超短裙"), "短裙");
  assert.equal(nounOf("冰川满钻尖甲（手背）"), "尖甲");
});

test("默认永远不替换：审计日志里的每次点击都只是“加到造型（额外）”", () => {
  for (const [lk, slot, name, zone] of [
    [A, "outfit", "黑色镜面漆皮超短裙", "lower"],
    [A, "outfit", "黑色漆皮长风衣", "upper"],
    [A, "accessory", "横杆铃铛链环", "body"],
    [B, "accessory", "钢珠吊坠圈环", "body"],
    [B, "outfit", "黑色漆皮细带捆绑内衣", "upper"], // 总调度：不能默认替换项目方刚定的“黑色漆皮束腰”
  ]) {
    const r = partFor(lk, slot, name, zone);
    assert.equal(r.extra, true, name);
    assert.equal(r.part, name, name);
  }
});

test("可替换的候选只列同槽位、同部位；名字最像的只作提示", () => {
  const r = partFor(B, "outfit", "黑色镜面漆皮超短裙", "lower");
  assert.deepEqual(r.options, ["黑色漆皮短裙"]);
  assert.equal(r.suggest, "黑色漆皮短裙");
  assert.equal(r.extra, true); // 仍然默认不替换
  const r2 = partFor(A, "outfit", "黑色漆皮长风衣", "upper");
  assert.deepEqual(r2.options, ["米白衬衫", "短款西装外套"]);
  assert.equal(r2.suggest, null);
  const r3 = partFor(A, "accessory", "横杆铃铛链环", "body");
  assert.deepEqual(r3.options, []);
  assert.equal(r3.reason, "zone");
});

test("部件换单品的候选按部位过滤（上衣不列下装，项链不列身体穿环）", () => {
  const item = (id, slot, zone) => ({ id, slot, zone, name: id, looks: [], tags: [] });
  const items = [item("O09 超短裙", "outfit", "lower"), item("O08 长风衣", "outfit", "upper"), item("横杆铃铛链环", "accessory", "body"), item("银项链", "accessory", "neck")];
  assert.deepEqual(choicesFor(items, A.parts[0]).map((x) => x.id), ["O08 长风衣"]);
  assert.deepEqual(choicesFor(items, A.parts[1]).map((x) => x.id), ["O09 超短裙"]);
  assert.deepEqual(choicesFor(items, A.parts[4]).map((x) => x.id), ["银项链"]);
});
