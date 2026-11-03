// UIFIX-F 11-03：场景显示名只来自当前剧的场景登记；登记没有 = “场景未登记：id”，绝不按 id 单词拼中文、绝不回退 V1。
// 复现：V2 第 1 集分镜页出现“办公室夜”——V1 状态表的 sk_office_night 经 SOP 接口挂到 V2 镜头上，旧 WORD 表把它拼成了中文。
// 跑法：cd apps/web && node --test e2e/uirsi/scene_label.test.mjs（Node 22+ 直接剥类型跑 .ts）
import { test } from "node:test";
import assert from "node:assert/strict";
import { plateMatchesScene, resolveSceneLabel, sceneIdOf, sopSceneId, unregisteredLabel } from "../../src/v3/sceneLabel.pure.ts";

test("登记里没有的场景：显示“场景未登记：id”，不拼“办公室夜”", () => {
  assert.equal(resolveSceneLabel("sk_office_night", new Map()), unregisteredLabel("sk_office_night"));
  assert.equal(resolveSceneLabel("sk_office_night", null), "场景未登记：sk_office_night");
  assert.equal(resolveSceneLabel("sk_white_cyc", new Map()), "场景未登记：sk_white_cyc");
  assert.doesNotMatch(resolveSceneLabel("sk_gu_apartment", new Map()), /顾沉|公寓/); // 旧 WORD 表的 V1 词汇不再出现
});

test("登记有名字就用名字；已是人话的原样；路径也能认出 id", () => {
  const names = new Map([["sk_white_cyc", "影棚白幕"]]);
  assert.equal(resolveSceneLabel("sk_white_cyc", names), "影棚白幕");
  assert.equal(resolveSceneLabel("sk_white_cyc/plate.png", names), "影棚白幕");
  assert.equal(resolveSceneLabel("影棚白幕", new Map()), "影棚白幕");
  assert.equal(resolveSceneLabel(null, names), null);
  assert.equal(sceneIdOf("assets/scenes/sk_office_night/refs/ar-1.png"), "sk_office_night");
});

test("SOP 带出的 scene_id：状态表过期（按别的剧本生成）时不信；新后端按 scene_id_source 判", () => {
  const stale = { scene_id: "sk_office_night", blockers: [{ code: "timeline_stale" }], stages: {} };
  assert.equal(sopSceneId(stale), null);
  const staleS2 = { scene_id: "sk_office_night", blockers: [], stages: { S2: { blockers: [{ code: "timeline_stale" }] } } };
  assert.equal(sopSceneId(staleS2), null);
  assert.equal(sopSceneId({ scene_id: "sk_elevator", blockers: [], stages: {} }), "sk_elevator");
  assert.equal(sopSceneId({ scene_id: "sk_white_cyc", scene_id_source: "script", blockers: [{ code: "timeline_stale" }] }), "sk_white_cyc");
  assert.equal(sopSceneId({ scene_id: null, scene_id_source: null }), null);
  assert.equal(sopSceneId(undefined), null);
});

test("底图属于别的场景（V1 残留）→ 不显示", () => {
  assert.equal(plateMatchesScene("sk_office_night/refs/ar-9565919866.png", "sk_white_cyc"), false);
  assert.equal(plateMatchesScene("sk_white_cyc/plate.png", "sk_white_cyc"), true);
  assert.equal(plateMatchesScene("sk_office_night/plate.png", null), true); // 本镜没写场景：无从比对
  assert.equal(plateMatchesScene(null, "sk_white_cyc"), false);
});
