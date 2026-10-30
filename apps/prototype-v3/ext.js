// 原型扩展：§6 本镜参考切换 · §7 图片精修循环 + 资产编辑 · §8 剧本创作页 / 模型与 API 配置
// 只在浏览器内存里演示，不读写任何生产文件、不调用任何模型。
(() => {
const P = window.P, st = P.st, D = P.D, $ = P.$, esc = P.esc, H = P.hooks;
const R = D.refs;
const SLOT_ZH = { outfit: "服装", shoes: "鞋", makeup: "妆容", nails: "美甲", hair: "发型", accessory: "饰品" };
const PSLOTS = Object.keys(SLOT_ZH);
const TIME_ZH = { night: "夜", morning: "早", dusk: "黄昏", day: "日" };
const LAYER_ZH = { shot: "本镜改过", scene: "本场改过", ep: "本集改过" };
const shotsOf = () => st.shots;
const S = (i) => st.shots[i].src;
const rmodal = $("#rmodal"), rbox = $("#rbox"), pop = $("#pop");

// ================= §6 数据：集默认 → 场景 → 镜头 =================
st.epDef = {}; st.ov = {}; st.ref = null; st.gearOv = {}; st.queue = []; st.loop = null; st.assetVers = {};
// 缺的整套形象 B/C 用“占位”演示（明确标注，不是资产）
Object.entries(R).forEach(([c, r]) => {
  const letters = ["A", "B", "C"];
  while (r.looks.length < 3) { const L = letters[r.looks.length]; r.looks.push({ id: `PH-${c}-${L}`, letter: L, name: `占位 ${L}`, img: null, placeholder: true, note: "资产库里还没有，演示用占位" }); }
  st.epDef[c] = (r.looks.find((l) => l.default) || r.looks[0]).id;
});
const lookOf = (c, id) => R[c].looks.find((l) => l.id === id);
const partOf = (c, id) => PSLOTS.map((k) => R[c].parts[k]).flat().find((p) => p.id === id);
function eff(i, c) {
  const o = st.ov[i]?.[c] || {};
  return { look: o.look || st.epDef[c], parts: { ...R[c].current, ...(o.parts || {}) }, refImg: o.refImg || null, refFrom: o.refFrom || null, layer: o.layer || null };
}
function effScene(i) {
  const o = st.ov[i]?.scene || {};
  return { plate: o.plate || "none", time: o.time || S(i).time_of_day, layer: o.layer || null };
}
const effImg = (i, c) => { const e = eff(i, c); return e.refImg || lookOf(c, e.look)?.img || D.images[c]; };
const badge = (layer) => layer ? `<span class="ovb ${layer}">${LAYER_ZH[layer]}</span>` : "";
function partsChanged(i, c) {
  const e = eff(i, c), base = R[c].current;
  return PSLOTS.filter((k) => (e.parts[k] || null) !== (base[k] || null)).map((k) => `${SLOT_ZH[k]}：${partOf(c, e.parts[k])?.name || "—"}`);
}

// ---------- 参考条（精修）与行内小卡（审片） ----------
H.refbar = (i) => {
  const s = S(i);
  const cards = s.characters.map((c) => {
    const e = eff(i, c), lk = lookOf(c, e.look);
    const sub = [lk.placeholder ? "占位形象" : lk.name, ...partsChanged(i, c), e.refFrom ? "参考图取自 " + e.refFrom : ""].filter(Boolean).join(" · ");
    return `<button class="rcard" data-rcard="${c}" title="点开切换参考（整套形象 / 单件 / 借用）"><img src="${effImg(i, c)}" alt=""><div><div class="t">${P.CHAR_NAMES[c]}<span class="lt">${lk.letter}</span>${badge(e.layer)}</div><div class="s">${esc(sub)}</div></div></button>`;
  }).join("");
  const es = effScene(i), sc = D.scenes[s.scene_id] || {};
  const scard = `<button class="rcard" data-rcard="scene" title="点开切换场景参考"><div class="sc">场景</div><div><div class="t">${esc(sc.place || s.place)}${badge(es.layer)}</div><div class="s">${es.plate === "none" ? "不用底图" : "底图"} · ${TIME_ZH[es.time] || es.time || "—"}</div></div></button>`;
  return `<div class="refbar"><span class="rbl">本镜参考</span>${cards}${scard}</div>`;
};
H.bindRefbar = () => { document.querySelectorAll("[data-rcard]").forEach((b) => b.onclick = () => openRef(st.cur, b.dataset.rcard)); };
H.castHTML = (i) => {
  const s = S(i);
  return s.characters.map((c) => {
    const e = eff(i, c), lk = lookOf(c, e.look);
    return `<div class="lookc" data-x="ref:${c}" title="${P.CHAR_NAMES[c]} · 形象 ${lk.letter}${e.layer ? " · " + LAYER_ZH[e.layer] : ""}（点开切换参考）"><img src="${effImg(i, c)}" alt="">${e.layer ? `<span class="ovd"></span>` : ""}<b>${lk.letter}</b></div>`;
  }).join("") + (() => { const es = effScene(i); return `<div class="lookc scn" data-x="ref:scene" title="场景参考：${es.plate === "none" ? "不用底图" : "底图"}（点开切换）">${es.layer ? `<span class="ovd"></span>` : ""}${esc((D.scenes[s.scene_id]?.place || s.place || "").slice(0, 4))}</div>`; })();
};

// ---------- 切换面板 ----------
function openRef(i, key, preset, opts) {
  P.closeAll();
  const draft = key === "scene" ? { ...effScene(i) } : (() => { const e = eff(i, key); return { look: e.look, parts: { ...e.parts }, refImg: e.refImg, refFrom: e.refFrom }; })();
  Object.assign(draft, preset || {});
  st.ref = { i, key, draft, step: "pick", scope: "shot", ownerOk: false, ...(opts || {}) };
  renderRef();
  rmodal.classList.add("on");
}
H.openRef = openRef;
function closeRef() { rmodal.classList.remove("on"); st.ref = null; }
rmodal.onclick = (e) => { if (e.target === rmodal) closeRef(); };

function diffOf(r) {
  const { i, key, draft } = r, out = [];
  if (key === "scene") {
    const e = effScene(i);
    if (draft.plate !== e.plate) out.push(`底图：${draft.plate === "none" ? "不用底图" : "用底图"}`);
    if (draft.time !== e.time) out.push(`时段：${TIME_ZH[draft.time] || draft.time}`);
    return out;
  }
  const e = eff(i, key);
  if (draft.look !== e.look) out.push(`整套形象 ${lookOf(key, e.look).letter} → ${lookOf(key, draft.look).letter}`);
  PSLOTS.forEach((k) => { if ((draft.parts[k] || null) !== (e.parts[k] || null)) out.push(`${SLOT_ZH[k]} → ${partOf(key, draft.parts[k])?.name || "—"}`); });
  if ((draft.refImg || null) !== (e.refImg || null)) out.push(draft.refImg ? `参考图 → 取自 ${draft.refFrom}` : "参考图 → 恢复形象图");
  return out;
}
function scopes(r) {
  const { i, key } = r, s = S(i);
  const has = (j) => key === "scene" || S(j).characters.includes(key);
  const same = shotsOf().map((_, j) => j).filter((j) => S(j).scene_id === s.scene_id && has(j));
  const after = same.filter((j) => j >= i);
  const all = key === "scene" ? same : shotsOf().map((_, j) => j).filter(has);
  const rng = (a) => a.length > 1 ? `S${S(a[0]).index}–S${S(a[a.length - 1]).index}` : `S${S(a[0]).index}`;
  return [
    { k: "shot", label: "只这一镜", list: [i], layer: "shot", hint: `S${s.index}` },
    { k: "after", label: `本场景后续 ${after.length} 镜`, list: after, layer: "scene", hint: rng(after) },
    key === "scene" ? { k: "all", label: `本场景全部 ${all.length} 镜`, list: all, layer: "scene", hint: rng(all) } : { k: "all", label: `本集全部 ${all.length} 镜（不改集默认）`, list: all, layer: "ep", hint: rng(all) },
  ];
}
function sigOf(j, key) {
  if (key === "scene") { const e = effScene(j); return e.plate + "|" + e.time; }
  const e = eff(j, key); return [e.look, JSON.stringify(e.parts), e.refImg || ""].join("|");
}
function newSig(r) {
  const d = r.draft;
  return r.key === "scene" ? d.plate + "|" + d.time : [d.look, JSON.stringify(d.parts), d.refImg || ""].join("|");
}
function impactOf(r) {
  const sc = scopes(r).find((x) => x.k === r.scope), list = sc.list;
  const rows = list.map((j) => {
    const sh = st.shots[j], has = sh.cands.first.length > 0;
    return { j, has, adult: sh.src.adult, now: P.nextOf(sh) };
  });
  // 衔接风险：同场景、不在范围内的相邻镜头，应用后造型不同
  const warns = [], ns = newSig(r), s = S(r.i);
  list.forEach((j) => [j - 1, j + 1].forEach((k) => {
    if (k < 0 || k >= st.shots.length || list.includes(k)) return;
    if (S(k).scene_id !== s.scene_id) return;
    if (r.key !== "scene" && !S(k).characters.includes(r.key)) return;
    if (sigOf(k, r.key) !== ns) warns.push(`S${S(Math.min(j, k)).index} → S${S(Math.max(j, k)).index}：同在「${D.scenes[s.scene_id]?.place || s.place}」，${r.key === "scene" ? "场景设置" : P.CHAR_NAMES[r.key] + "造型"}前后不同（衔接风险）`);
  }));
  return { sc, rows, warns: [...new Set(warns)] };
}

function renderRef() {
  const r = st.ref; if (!r) return;
  const { i, key, draft } = r, s = S(i), isScene = key === "scene";
  const e = isScene ? effScene(i) : eff(i, key);
  const title = isScene ? `场景 · ${esc(D.scenes[s.scene_id]?.place || s.place)}` : `${P.CHAR_NAMES[key]} · 形象 ${lookOf(key, e.look).letter}`;
  const head = `<div class="rhead">${isScene ? `<div class="sc">场景</div>` : `<img src="${effImg(i, key)}">`}
    <div><h3>S${s.index} · ${title} ${badge(e.layer)}</h3><div class="sub">${r.step === "apply" ? "第 2 步：选范围、看影响" : r.step === "owner" ? "改集默认（项目方本人）" : r.step === "asset" ? "资产编辑：作用在资产图上" : "本镜参考：只能选资产库里已有的资产"}${s.adult ? " · 成人镜：不显示画面，切换参考可用，送 gpu3 仍需你本人确认" : ""}</div></div>
    <span class="sp"></span>
    ${e.layer && r.step === "pick" ? `<button class="btn sm" id="rReset">恢复集默认</button>` : ""}
    ${!isScene && r.step === "pick" ? `<button class="btn sm" id="rAsset" title="§7.3：在资产图上改（指令改图 / 换参考 / 上传替换）">编辑这个资产</button>` : ""}
    <button class="btn sm" id="rClose">✕</button></div>`;
  let body = "", foot = "";
  if (r.step === "pick") {
    if (isScene) {
      const sc = D.scenes[s.scene_id] || {};
      const others = shotsOf().map((_, j) => j).filter((j) => j !== i && S(j).scene_id === s.scene_id);
      body = `<div class="rsec"><h5>场景底图<span>资产库：${sc.plate_status === "missing" ? "这个场景还没有底图" : "1 张"} · 其他机位/时段的底图候选：资产库里没有</span></h5>
        <div class="ltiles">
          <button class="ltile" disabled title="资产库里还没有这张底图"><div class="ph">底图<br>（未出）<br><br>资产库里没有<br>去资产页新增</div><div class="cap">${esc(sc.place || "")} 底图</div></button>
          <button class="ltile ${draft.plate === "none" ? "pick" : ""} ${e.plate === "none" ? "cur" : ""}" data-plate="none"><div class="ph">不用底图<br><br>（本集已确认跳过底图）</div><div class="cap"><b>不用底图</b></div></button>
        </div></div>
        <div class="rsec"><h5>时段<span>来自 scenes.json 的本场景时段</span></h5><div class="chips2">${(sc.times || [s.time_of_day]).map((t) => `<button data-time="${t}" class="${draft.time === t ? "on" : ""}">${TIME_ZH[t] || t}${t === s.time_of_day ? "（剧本）" : ""}</button>`).join("")}</div></div>
        <div class="rsec"><h5>借用<span>复制另一镜的场景设置</span></h5><div class="chips2">${others.map((j) => `<button data-borrow="${j}">用 S${S(j).index} 的设置</button>`).join("") || `<span class="pnote">同场景没有别的镜头</span>`}</div></div>`;
    } else {
      const looks = R[key].looks;
      body = `<div class="rsec"><h5>① 整套形象<span>点一下整套换掉 · 绿框 = 当前生效 · 蓝框 = 你选的</span></h5><div class="ltiles">${looks.map((l) => `
          <button class="ltile ${draft.look === l.id ? "pick" : ""} ${e.look === l.id ? "cur" : ""}" data-look="${l.id}" title="${esc(l.note || l.name)}">
            ${l.img ? `<img src="${l.img}">` : `<div class="ph">${l.placeholder ? "占位<br>（演示）" : "没有上身图"}<br><br>${esc(l.note || "")}</div>`}
            ${st.epDef[key] === l.id ? `<span class="tagd">集默认</span>` : ""}${l.placeholder ? `<span class="tagp">占位</span>` : ""}
            <div class="cap"><b>${l.letter}</b>${esc(l.name)}</div></button>`).join("")}
          <div style="align-self:end;display:flex;flex-direction:column;gap:6px;font-size:12px;color:var(--fg3)">
            ${draft.look !== st.epDef[key] && !lookOf(key, draft.look).placeholder ? `<button class="alink" id="rOwner">把 ${lookOf(key, draft.look).letter} 设为本集默认…（项目方本人）</button>` : `<span>集默认 = 已确认的本集造型</span>`}
            <button class="alink" data-goasset="1">去资产页新增形象</button></div></div></div>
        <div class="rsec"><h5>② 单件替换<span>只换这一件，其余保持当前形象 · 只能选资产库里已有的</span></h5>
          ${PSLOTS.map((k) => {
            const ps = R[key].parts[k], cur = e.parts[k], pick = draft.parts[k], extra = R[key].noimg[k];
            const note = ps.length === 0 ? "资产库里没有这一类" : ps.length === 1 ? "资产库里只有这一项" : "";
            return `<div class="prow"><div class="pl">${SLOT_ZH[k]}<small>${cur ? esc(partOf(key, cur)?.name || cur) : "集默认未设"}</small></div><div class="ptiles">
              ${ps.map((p) => `<button class="ptile ${pick === p.id ? "pick" : ""} ${cur === p.id ? "cur" : ""}" data-part="${k}:${p.id}" title="${esc(p.name)}">${p.img ? `<img src="${p.img}" loading="lazy">` : `<div class="ph">无参考图</div>`}<span class="nm">${esc(p.name)}</span></button>`).join("")}
              ${pick && pick !== R[key].current[k] ? `<button class="ptile" data-part="${k}:" title="恢复集默认"><div class="ph">恢复<br>集默认</div><span class="nm">${R[key].current[k] ? "集默认" : "不指定"}</span></button>` : ""}
              ${note ? `<span class="pnote">${note}</span>` : ""}${extra ? `<span class="pnote">另有 ${extra} 项没有参考图</span>` : ""}
              <button class="alink pnote" data-goasset="1">去资产页新增</button></div></div>`;
          }).join("")}</div>
        <div class="rsec"><h5>④ 借用<span>复制另一镜的整套参考，或把本镜某张候选 / 定稿图设为参考</span></h5>
          <div class="chips2">${shotsOf().map((_, j) => j).filter((j) => j !== i && S(j).characters.includes(key)).map((j) => `<button data-borrow="${j}" class="${eff(j, key).layer ? "on" : ""}">用 S${S(j).index} 的设置${eff(j, key).layer ? " *" : ""}</button>`).join("")}</div>
          <div style="margin-top:8px;display:flex;gap:6px;align-items:center;flex-wrap:wrap">${s.adult ? `<span class="pnote">成人镜不显示候选图</span>` : (() => {
            const cs = ["first", "last"].flatMap((sl) => st.shots[i].cands[sl].filter((c) => !c.pending).map((c) => ({ c, sl })));
            return cs.length ? `<span class="pnote">设为参考：</span>` + cs.map(({ c, sl }) => `<button class="ptile ${draft.refImg === c.url ? "pick" : ""}" data-asref="${sl}:${c.id}" style="width:44px" title="${P.SLOT_NAMES[sl]} #${c.n}"><img src="${c.url}" style="height:78px"><span class="nm">${P.SLOT_NAMES[sl]}#${c.n}</span></button>`).join("") : `<span class="pnote">本镜还没有候选图可设为参考</span>`;
          })()}${draft.refImg ? `<button class="alink" id="rUnref">取消参考图（${esc(draft.refFrom)}）</button>` : ""}</div></div>`;
    }
    const d = diffOf(r);
    foot = `<div class="rfoot"><div class="diff">${d.length ? "将修改：" + d.map((x) => `<b>${esc(x)}</b>`).join("、") : "还没有修改 · 选好后点“下一步”看影响面"}</div>
      <button class="btn sm" id="rCancel">取消</button><button class="btn sm primary" id="rNext" ${d.length ? "" : "disabled"}>下一步：选范围、看影响 →</button></div>`;
  } else if (r.step === "apply") {
    const d = diffOf(r), sc = scopes(r), im = impactOf(r);
    const stale = im.rows.filter((x) => x.has).length;
    body = `<div class="rsec"><h5>改什么</h5><div style="font-size:13px">${d.map(esc).join("；")}</div></div>
      <div class="twocol"><div class="rsec"><h5>范围</h5><div class="scope">${sc.map((x) => `<label class="${r.scope === x.k ? "on" : ""}"><input type="radio" name="scope" value="${x.k}" ${r.scope === x.k ? "checked" : ""}> ${esc(x.label)}<small>${x.hint}</small></label>`).join("")}</div>
        <div style="font-size:11px;color:var(--fg3);margin-top:6px">只记“与上一层不同的部分”：镜头覆盖 → 场景覆盖 → 集默认。集默认不在这里改。</div></div>
      <div class="rsec"><h5>影响面<span>按 inputs_sha：已出图的镜头会过期</span></h5>
        <table class="imp"><tr><th>镜头</th><th>现在</th><th>应用后</th></tr>${im.rows.map((x) => `<tr><td>S${S(x.j).index}</td><td>${P.dotHTML(x.now.stt)} ${P.STATUS[x.now.stt]}</td><td>${x.adult ? (x.has ? "过期 · 成人镜待你本人送 gpu3" : "成人镜 · 未出，无需重出") : x.has ? `<b style="color:var(--amber)">过期</b> → 重出首帧` : "未出 · 无需重出"}</td></tr>`).join("")}</table>
        ${im.warns.length ? `<div class="warnbox"><b>衔接风险</b><ul>${im.warns.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></div>` : `<div class="okbox">同场景相邻镜头造型一致，没有衔接风险</div>`}
      </div></div>`;
    foot = `<div class="rfoot"><div class="diff">${stale} 镜会过期${r.fromLoop ? " · 应用后回到“换参考再改”" : ""}</div><button class="btn sm" id="rBack">← 返回</button>
      <button class="btn sm" id="rApplyOnly">只应用，稍后重出</button>${r.fromLoop ? "" : `<span class="gearwrap"><button class="btn sm primary" id="rApplyRegen">应用并重出首帧</button>${gear("首帧生成")}</span>`}</div>`;
  } else if (r.step === "owner") {
    const L = lookOf(key, draft.look), O = lookOf(key, st.epDef[key]);
    const affected = shotsOf().filter((sh) => sh.src.characters.includes(key));
    const st2 = affected.filter((sh) => sh.cands.first.length).length;
    body = `<div class="rsec"><div class="ownerbox"><b>改集默认 = 改造型确认</b>
      <p>把 ${P.CHAR_NAMES[key]} 的第 ${D.episode.number} 集默认形象从 <b>${O.letter} ${esc(O.name)}</b> 改成 <b>${L.letter} ${esc(L.name)}</b>。</p>
      <ul><li>本集造型确认（look_confirmed，“${esc(D.episode.confirmed_ref || "")}”）会失效，需要你重新确认；</li><li>本集 ${affected.length} 镜用到 ${P.CHAR_NAMES[key]}，其中 ${st2} 镜已出图，会标过期；</li><li>记录 by=owner。镜头 / 场景层的覆盖保持不变。</li></ul>
      <label><input type="checkbox" id="rOwnerOk" ${r.ownerOk ? "checked" : ""}> 我是项目方（by=owner）</label></div></div>`;
    foot = `<div class="rfoot"><div class="diff"></div><button class="btn sm" id="rBack">← 返回</button><button class="btn sm primary" id="rOwnerGo" ${r.ownerOk ? "" : "disabled"}>改集默认</button></div>`;
  } else if (r.step === "asset") {
    ({ body, foot } = assetEditorHTML(r));
  }
  rbox.innerHTML = head + `<div class="rbody">${body}</div>` + foot;
  bindRef();
}
function bindRef() {
  const r = st.ref, { i, key, draft } = r;
  const on = (sel, fn) => rbox.querySelectorAll(sel).forEach((b) => b.onclick = (e) => fn(b, e));
  on("#rClose", closeRef); on("#rCancel", closeRef);
  on("[data-goasset]", () => P.toast("资产页（第 4 节角色卡）：新资产在那里生成 / 上传（Image 2.1 / Klein），原型略"));
  on("[data-look]", (b) => { draft.look = b.dataset.look; renderRef(); });
  on("[data-part]", (b) => { const [k, id] = b.dataset.part.split(":"); if (id) draft.parts[k] = id; else { if (R[key].current[k]) draft.parts[k] = R[key].current[k]; else delete draft.parts[k]; } renderRef(); });
  on("[data-plate]", (b) => { draft.plate = b.dataset.plate; renderRef(); });
  on("[data-time]", (b) => { draft.time = b.dataset.time; renderRef(); });
  on("[data-borrow]", (b) => { const j = +b.dataset.borrow; if (key === "scene") Object.assign(draft, { plate: effScene(j).plate, time: effScene(j).time }); else { const e = eff(j, key); Object.assign(draft, { look: e.look, parts: { ...e.parts }, refImg: e.refImg, refFrom: e.refFrom }); } P.toast(`已复制 S${S(j).index} 的设置（还没应用）`); renderRef(); });
  on("[data-asref]", (b) => { const [sl, id] = b.dataset.asref.split(":"); const c = st.shots[i].cands[sl].find((x) => x.id === +id); draft.refImg = c.url; draft.refFrom = `S${S(i).index} ${P.SLOT_NAMES[sl]} #${c.n}`; renderRef(); });
  on("#rUnref", () => { draft.refImg = null; draft.refFrom = null; renderRef(); });
  on("#rNext", () => { r.step = "apply"; renderRef(); });
  on("#rBack", () => { r.step = "pick"; renderRef(); });
  on("#rOwner", () => { r.step = "owner"; r.ownerOk = false; renderRef(); });
  on("#rReset", () => {
    if (key === "scene") Object.assign(draft, { plate: "none", time: S(i).time_of_day });
    else Object.assign(draft, { look: st.epDef[key], parts: { ...R[key].current }, refImg: null, refFrom: null });
    r.step = "apply"; r.scope = "shot"; renderRef();
  });
  on("#rAsset", () => { r.step = "asset"; r.asset = { mode: "instr", strength: "中", instr: "", base: null, save: "shot", ownerOk: false }; renderRef(); });
  rbox.querySelectorAll("input[name=scope]").forEach((x) => x.onchange = () => { r.scope = x.value; renderRef(); });
  const ok = $("#rOwnerOk"); if (ok) ok.onchange = () => { r.ownerOk = ok.checked; renderRef(); };
  on("#rOwnerGo", () => changeEpDefault(key, draft.look));
  on("#rApplyOnly", () => applyRef(false));
  on("#rApplyRegen", () => applyRef(true));
  if (r.step === "asset") bindAsset(r);
}
function snapshot() {
  return { ov: JSON.parse(JSON.stringify(st.ov)), epDef: { ...st.epDef }, lc: D.episode.look_confirmed,
    shots: st.shots.map((sh) => ({ stale: sh.stale, staleDown: sh.staleDown, lock: { ...sh.lock }, gen: { ...sh.gen } })) };
}
function restore(sn) {
  st.ov = sn.ov; st.epDef = sn.epDef; D.episode.look_confirmed = sn.lc;
  st.shots.forEach((sh, j) => { const x = sn.shots[j]; sh.stale = x.stale; sh.staleDown = x.staleDown; sh.lock = x.lock; Object.keys(sh.gen).forEach((k) => { if (!x.gen[k]) delete sh.gen[k]; }); });
  P.render(); P.toast("已撤销");
}
function toastUndo(msg, sn) {
  const t = $("#toast");
  t.innerHTML = `<span>${esc(msg)}</span><button>撤销</button>`;
  t.classList.add("on", "act");
  t.querySelector("button").onclick = () => { t.classList.remove("on", "act"); restore(sn); };
  clearTimeout(toastUndo.t); toastUndo.t = setTimeout(() => t.classList.remove("on", "act"), 7000);
}
function writeOv(j, r, layer) {
  const { key, draft } = r;
  st.ov[j] = st.ov[j] || {};
  if (key === "scene") {
    const o = { plate: draft.plate, time: draft.time, layer };
    if (o.plate === "none" && o.time === S(j).time_of_day) delete st.ov[j].scene; else st.ov[j].scene = o;
    return;
  }
  const o = { layer };
  if (draft.look !== st.epDef[key]) o.look = draft.look;
  const parts = {}; PSLOTS.forEach((k) => { if ((draft.parts[k] || null) !== (R[key].current[k] || null)) parts[k] = draft.parts[k]; });
  if (Object.keys(parts).length) o.parts = parts;
  if (draft.refImg) { o.refImg = draft.refImg; o.refFrom = draft.refFrom; }
  if (Object.keys(o).length === 1) delete st.ov[j][key]; else st.ov[j][key] = o;
}
function markAffected(list, regen) {
  let n = 0;
  list.forEach((j) => {
    const sh = st.shots[j];
    if (!sh.cands.first.length) return;
    n++;
    if (regen && !sh.src.adult) { P.unlockFirst(sh); P.startGen(sh, ["first"], 0, true); sh.stale = true; }
    else sh.stale = true;
  });
  return n;
}
function applyRef(regen) {
  const r = st.ref, sc = scopes(r).find((x) => x.k === r.scope), sn = snapshot();
  sc.list.forEach((j) => writeOv(j, r, sc.layer));
  const n = markAffected(sc.list, regen);
  const fromLoop = r.fromLoop;
  closeRef(); P.render();
  toastUndo(`已应用到 ${sc.label}（${sc.hint}）· ${n} 镜${regen ? "开始重出首帧" : "标为过期"}`, sn);
  if (fromLoop) setTimeout(() => openLoop(document.querySelector("#bAsk"), { mode: "refs" }), 50);
}
function changeEpDefault(key, look) {
  const sn = snapshot();
  st.epDef[key] = look; D.episode.look_confirmed = false;
  Object.values(st.ov).forEach((o) => { if (o[key] && o[key].look === look) { delete o[key].look; if (!o[key].parts && !o[key].refImg) delete o[key]; } });
  const list = shotsOf().map((_, j) => j).filter((j) => S(j).characters.includes(key));
  const n = markAffected(list, false);
  closeRef(); P.render();
  toastUndo(`已改集默认（by=owner）· 本集造型确认需要重做 · ${n} 镜过期`, sn);
}

// ---------- “设为参考”入口（版本标签 / 对比框） ----------
H.setAsRef = (anchor, i, cand, slot) => {
  const s = S(i);
  const items = [`设为参考 · ${P.SLOT_NAMES[slot]} #${cand.n}`, ...s.characters.map((c) => [`给 ${P.CHAR_NAMES[c]} 用`, () => { P.closeCompare(); openRef(i, c, { refImg: cand.url, refFrom: `S${s.index} ${P.SLOT_NAMES[slot]} #${cand.n}` }); }])];
  P.showMenu(items, anchor, false);
};

// ================= §7 图片精修循环 =================
const MODES = { prompt: "改提示词重出", instr: "指令改图", refs: "换参考再改", mask: "局部重绘" };
const STRENGTH = { 小: 0.35, 中: 0.55, 大: 0.75 };
function gpuFor(mode, strength) {
  const q = st.queue.length;
  const base = { prompt: ["gpu3", "qwen_t2i（现有首帧流程）", 60], instr: ["gpu3", `Image 2.1 · qwen_edit（底图 = 当前图，denoise ${STRENGTH[strength] ?? 0.55}）`, 40], refs: ["gpu3", "Image 2.1 · qwen_edit 多参考（图1 = 当前图，图2… = 新参考）", 55], mask: ["gpu3", "蒙版重绘（还没有这个流程）", 0], asset: ["gpu3", "Image 2.1 · qwen_edit（底图 = 资产图）", 40] }[mode];
  return { card: base[0], flow: base[1], eta: base[2] + q * 45, q };
}
const gpuLine = (g) => `将用 <b>${g.card}</b> · ${esc(g.flow)} · 预计约 <b>${g.eta} 秒</b>${g.q ? `（前面排队 ${g.q} 个）` : ""} · 排队中可取消`;
function refsSummary(i) {
  const s = S(i);
  return s.characters.map((c) => { const e = eff(i, c), lk = lookOf(c, e.look); return `${P.CHAR_NAMES[c]} · 形象 ${lk.letter}${partsChanged(i, c).length ? " · " + partsChanged(i, c).join(" · ") : ""}${e.refFrom ? " · 参考图 " + e.refFrom : ""}`; })
    .concat([`场景 · ${effScene(i).plate === "none" ? "不用底图" : "底图"}`]);
}
function openLoop(anchor, preset) {
  const sh = P.cur(), slot = P.st.slot;
  if (slot === "video") return P.toast("视频不在这里改图");
  const base = sh.cands[slot].find((c) => c.id === (st.loopBase || sh.sel[slot]));
  if (!base) return P.toast(`还没有${P.SLOT_NAMES[slot]}可改`);
  st.loop = { mode: "instr", strength: "中", instr: "", prompt: sh.edits.img_prompt ?? sh.src.img_prompt ?? "", ...(st.loop || {}), ...(preset || {}), base: base.id };
  renderLoop(anchor || $("#bAsk"));
}
H.openLoop = (a) => openLoop(a);
function renderLoop(anchor) {
  const sh = P.cur(), slot = st.slot, L = st.loop, base = sh.cands[slot].find((c) => c.id === L.base);
  const g = gpuFor(L.mode, L.strength);
  let body = "";
  if (L.mode === "prompt") body = `<div style="font-size:12px;color:var(--fg3);margin-bottom:4px">${slot === "first" ? "首帧" : "尾帧"}提示词（原样发给 Image 2.1，画布不改写）· 整张重新生成</div><textarea id="lPrompt" rows="6">${esc(L.prompt)}</textarea>`;
  if (L.mode === "instr") body = `<div style="font-size:12px;color:var(--fg3);margin-bottom:4px">在当前图上写一句修改要求（你的原话，原样传）；保留构图，只改指定内容</div>
    <input type="text" id="lInstr" value="${esc(L.instr)}" placeholder="例如：把鞋换成黑色漆皮那双，其他不动">
    <div style="margin-top:8px;display:flex;gap:10px;align-items:center;font-size:12px">改动幅度 <span class="lseg">${Object.keys(STRENGTH).map((k) => `<button data-str="${k}" class="${L.strength === k ? "on" : ""}">${k}</button>`).join("")}</span><span style="color:var(--fg3)">denoise ${STRENGTH[L.strength]}</span></div>`;
  if (L.mode === "refs") body = `<div style="font-size:12px;color:var(--fg3)">用第 6 节换好的参考，连同当前图一起送 Image 2.1 编辑。现在生效的参考：</div>
    <ul class="reflist">${refsSummary(st.cur).map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
    <div class="chips2">${S(st.cur).characters.map((c) => `<button data-lref="${c}">换 ${P.CHAR_NAMES[c]} 的参考…</button>`).join("")}<button data-lref="scene">换场景…</button></div>
    <input type="text" id="lInstr" value="${esc(L.instr)}" placeholder="（可选）补一句要求，原样传" style="margin-top:8px">`;
  if (L.mode === "mask") body = `<div style="font-size:12px;color:var(--fg3)">在图上涂一块区域 + 一句要求，只改这块</div>
    <div class="maskwrap"><img src="${base.url}"><canvas id="lMask" width="270" height="480"></canvas></div>
    <input type="text" placeholder="只改涂过的地方：…" disabled>
    <div class="lerr">需要新增蒙版流程，暂不可用（封板后做：gpu3 需新增 ComfyUI 蒙版工作流）</div>`;
  pop.className = "pop loop";
  pop.innerHTML = `<h4>改图 · S${sh.src.index} ${P.SLOT_NAMES[slot]}</h4>
    <div class="lbase"><img src="${base.url}"><div>基于 <b>#${base.n}</b>（${esc(base.mode)}）<br><span style="color:var(--fg3)">新版本会挂在 #${base.n} 下面；可随时回退</span></div></div>
    <div class="lmodes">${Object.entries(MODES).map(([k, t]) => `<button data-lm="${k}" class="${L.mode === k ? "on" : ""}">${t}</button>`).join("")}</div>
    ${body}
    ${slot === "first" && sh.lock.first ? `<div class="lwarn">这张首帧已定稿：改了以后尾帧和视频会标“过期”</div>` : ""}
    <div class="gpuline">${L.mode === "mask" ? "局部重绘：没有可用的卡和流程" : gpuLine(g)}</div>
    <div class="row"><button class="btn sm" id="lCancel">取消</button><span class="gearwrap">${gear(L.mode === "prompt" ? "首帧生成" : "指令改图")}<button class="btn sm primary" id="lGo" ${L.mode === "mask" ? "disabled" : ""}>${L.mode === "prompt" ? "重新生成" : "开始改图"}</button></span></div>`;
  P.place(pop, anchor, false);
  const on = (sel, fn) => pop.querySelectorAll(sel).forEach((b) => b.onclick = () => fn(b));
  on("[data-lm]", (b) => { keepInputs(); L.mode = b.dataset.lm; renderLoop(anchor); });
  on("[data-str]", (b) => { keepInputs(); L.strength = b.dataset.str; renderLoop(anchor); });
  on("[data-lref]", (b) => { keepInputs(); P.closeAll(); openRef(st.cur, b.dataset.lref, null, { fromLoop: true }); });
  on("#lCancel", () => { P.closeAll(); });
  on("#lGo", () => { keepInputs(); runPass(); });
  const cv = $("#lMask"); if (cv) { const x = cv.getContext("2d"); let d = false; x.fillStyle = "rgba(239,91,91,.45)"; cv.onmousedown = () => d = true; window.addEventListener("mouseup", () => d = false); cv.onmousemove = (e) => { if (!d) return; const r = cv.getBoundingClientRect(); x.beginPath(); x.arc((e.clientX - r.left) * 270 / r.width, (e.clientY - r.top) * 480 / r.height, 14, 0, 7); x.fill(); }; }
}
function keepInputs() { const L = st.loop; const a = $("#lInstr"), b = $("#lPrompt"); if (a) L.instr = a.value; if (b) L.prompt = b.value; }
function runPass() {
  const sh = P.cur(), i = st.cur, slot = st.slot, L = st.loop;
  if (L.mode === "instr" && !L.instr.trim()) return P.toast("先写一句修改要求");
  const g = gpuFor(L.mode, L.strength);
  if (slot === "first" && P.unlockFirst(sh)) P.toast("首帧改了：尾帧和视频标为过期");
  const node = P.addCand(sh, slot, false, { parent: L.base, mode: MODES[L.mode], instr: L.mode === "prompt" ? L.prompt : L.instr, strength: L.mode === "instr" ? `${L.strength}（denoise ${STRENGTH[L.strength]}）` : "",
    refs: L.mode === "refs" ? refsSummary(i) : [], gpu: `${g.card} · ${g.flow}`, label: `${MODES[L.mode]}${L.mode === "instr" ? " · 幅度 " + L.strength : ""}（占位）` });
  node.pending = "queued";
  st.queue.push({ sh, i, slot, node, dur: 3200 });
  st.loopBase = null;
  P.closeAll();
  P.toast(`已排队：S${sh.src.index} ${P.SLOT_NAMES[slot]} · ${MODES[L.mode]} · ${g.card}，预计约 ${g.eta} 秒（原型 3 秒）`);
  st.rtab = "ver"; st.vslot = slot; st.vpick = node.id;
  pump(); P.render();
}
function pump() {
  const job = st.queue[0];
  if (!job || job.running) return;
  job.running = true; job.node.pending = "running";
  const rec = job.sh.gen[job.slot] = { t0: performance.now(), dur: job.dur };
  job.timer = setTimeout(() => {
    if (job.sh.gen[job.slot] === rec) delete job.sh.gen[job.slot];
    job.node.pending = false; job.node.isNew = true;
    job.sh.sel[job.slot] = job.node.id;
    st.queue.shift();
    P.toast(`S${job.sh.src.index} ${P.SLOT_NAMES[job.slot]} #${job.node.n}（${job.node.mode}）出来了，和上一版并排看看`);
    P.render(); pump();
  }, job.dur);
  P.render();
}
function cancelJob(nodeId) {
  const k = st.queue.findIndex((j) => j.node.id === nodeId); if (k < 0) return;
  const job = st.queue[k];
  clearTimeout(job.timer);
  if (job.running) delete job.sh.gen[job.slot];
  st.queue.splice(k, 1);
  const cs = job.sh.cands[job.slot]; cs.splice(cs.indexOf(job.node), 1);
  if (st.vpick === nodeId) st.vpick = null;
  P.toast(`已取消 #${job.node.n}`); P.render(); pump();
}
P.qsig = (sh) => st.queue.map((j) => j.node.id + ":" + j.node.pending).join() + ":" + st.ovSig;

// ---------- 版本标签：修改链 ----------
function chainOf(cs, node) { const out = []; let x = node; while (x) { out.unshift(x); x = cs.find((c) => c.id === x.parent); } return out; }
H.verBody = (sh) => {
  const slot = st.vslot || st.slot, cs = sh.cands[slot], sel = P.selCand(sh, slot);
  const gate = slot === "last" && !sh.lock.first ? "先定稿首帧，才能做尾帧" : slot === "video" && !(sh.lock.first && sh.lock.last) ? "首尾帧都定稿后才能出视频" : "";
  const seg = `<div class="vseg">${["first", "last", "video"].map((k) => `<button data-vslot="${k}" class="${slot === k ? "on" : ""}">${sh.lock[k] ? "🔒" : ""}${P.SLOT_NAMES[k]} ${sh.cands[k].length}</button>`).join("")}</div>`;
  if (!cs.length) return seg + `<div class="ro dash">${gate || "这一组还没有版本。点中间「重新生成」出第一张。"}</div>`;
  const view = cs.find((c) => c.id === st.vpick) || sel || cs[cs.length - 1];
  const parent = cs.find((c) => c.id === view.parent);
  const kids = {}; cs.forEach((c) => (kids[c.parent ?? 0] = kids[c.parent ?? 0] || []).push(c));
  const rows = []; const walk = (pid, d) => (kids[pid] || []).forEach((c) => { rows.push([c, d]); walk(c.id, d + 1); }); walk(0, 0);
  cs.filter((c) => c.parent && !cs.find((x) => x.id === c.parent)).forEach((c) => rows.push([c, 0]));
  const tree = rows.map(([c, d]) => `<div class="vnode ${c.id === view.id ? "view" : ""}" data-vn="${c.id}" style="padding-left:${8 + d * 14}px">
      <span class="br">${d ? "└" : "•"}</span><img src="${c.url}" style="${c.pending ? "opacity:.35" : ""}"><b>#${c.n}</b><span class="md">${esc(c.mode)}</span><span class="ins" title="${esc(c.instr)}">${esc(c.instr || "")}</span>
      ${c.pending ? `<span class="bd q">${c.pending === "running" ? "生成中" : "排队中"}</span><button class="x" data-cancel="${c.id}">取消</button>` : ""}
      ${sh.lock[slot] === c.id ? `<span class="bd lock">定稿</span>` : ""}${sel && sel.id === c.id ? `<span class="bd cur">当前</span>` : ""}${c.isNew ? `<span class="bd new">新</span>` : ""}</div>`).join("");
  const crumb = chainOf(cs, view).map((c) => c.id === view.id ? `<b>#${c.n} ${esc(c.mode)}</b>` : `#${c.n} ${esc(c.mode)}`).join(" › ");
  const older = sel && view.n < sel.n;
  return seg + `<div class="vgrp">${P.groupLabel(sh, slot)}<span>${sh.lock[slot] ? `已定稿 #${cs.find((c) => c.id === sh.lock[slot])?.n}` : "未定稿"}${gate ? " · " + gate : ""}</span></div>
    <div class="vtree">${tree}</div>
    <div class="crumb">修改链：${crumb}</div>
    <div class="vcmp">
      <figure>${parent ? `<img src="${parent.url}"><figcaption>上一版 #${parent.n}</figcaption>` : `<div class="ph">第一版<br>没有上一版</div><figcaption>&nbsp;</figcaption>`}</figure>
      <figure class="${sel && sel.id === view.id ? "chosen" : ""}">${view.pending ? `<div class="ph">${view.pending === "running" ? "生成中…" : "排队中…"}</div>` : `<img src="${view.url}">`}<figcaption>这一版 #${view.n}${sel && sel.id === view.id ? " · 当前" : ""}</figcaption></figure>
    </div>
    <dl class="vdl"><dt>改法</dt><dd>${esc(view.mode)}</dd><dt>原话</dt><dd>${view.instr ? esc(view.instr) : "—"}</dd><dt>幅度</dt><dd>${esc(view.strength || "—")}</dd><dt>参考</dt><dd>${view.refs.length ? view.refs.map(esc).join("<br>") : "—"}</dd><dt>卡</dt><dd>${esc(view.gpu)} · ${view.at}</dd></dl>
    ${view.pending ? "" : `<div class="vbtns wrap">
      ${sel && sel.id === view.id ? `<button class="btn sm" disabled>当前就是这版</button>` : `<button class="btn sm primary" id="vSet">${older ? `回退到 #${view.n}` : `选定 #${view.n}`}</button>`}
      ${slot !== "video" ? `<button class="btn sm" id="vCont">从这版继续改…</button>` : ""}
      ${slot !== "video" ? `<button class="btn sm ${sh.lock[slot] === view.id ? "locked-ok" : ""}" id="vLock" ${sh.lock[slot] === view.id || (slot === "last" && !sh.lock.first) ? "disabled" : ""}>${sh.lock[slot] === view.id ? "✓ 已定稿" : `定稿这版${P.SLOT_NAMES[slot]}`}</button>` : ""}
      ${slot !== "video" ? `<button class="btn sm" id="vRef">设为参考…</button>` : ""}
      <button class="btn sm" id="vFull">全屏对比</button></div>`}`;
};
H.verBind = (sh) => {
  const slot = st.vslot || st.slot, cs = sh.cands[slot];
  const root = $("#right");
  root.querySelectorAll("[data-vslot]").forEach((b) => b.onclick = () => { st.vslot = b.dataset.vslot; st.slot = b.dataset.vslot; st.vpick = null; P.render(); });
  root.querySelectorAll("[data-vn]").forEach((b) => b.onclick = (e) => { if (e.target.dataset.cancel) return; st.vpick = +b.dataset.vn; const x = cs.find((c) => c.id === st.vpick); if (x) x.isNew = false; P.render(); });
  root.querySelectorAll("[data-cancel]").forEach((b) => b.onclick = () => cancelJob(+b.dataset.cancel));
  const view = () => cs.find((c) => c.id === st.vpick) || P.selCand(sh, slot) || cs[cs.length - 1];
  const g = (id, fn) => { const b = root.querySelector(id); if (b) b.onclick = (e) => fn(e); };
  g("#vSet", () => {
    const v = view(), was = P.selCand(sh, slot);
    if (slot === "first" && sh.lock.first && sh.lock.first !== v.id && P.unlockFirst(sh)) P.toast("换了已定稿的首帧：尾帧和视频标为过期");
    sh.sel[slot] = v.id; v.isNew = false;
    P.toast(`S${sh.src.index} ${P.SLOT_NAMES[slot]}${was && v.n < was.n ? "已回退到" : "已选定"} #${v.n}`); P.render();
  });
  g("#vCont", () => { const v = view(); st.loopBase = v.id; st.slot = slot; P.render(); openLoop($("#bAsk")); });
  g("#vLock", () => { const v = view(); sh.sel[slot] = v.id; P.lockSlot(sh, slot); });
  g("#vRef", (e) => H.setAsRef(e.currentTarget, st.cur, view(), slot));
  g("#vFull", () => { st.slot = slot; P.openCompare(view().id); });
  const tr = root.querySelector(".vtree"), vn = root.querySelector(".vnode.view"); if (tr && vn) tr.scrollTop = Math.max(0, vn.offsetTop - tr.clientHeight + vn.offsetHeight + 40);
};

// ---------- §7.3 资产编辑（同一个循环，作用在资产图上） ----------
function assetEditorHTML(r) {
  const { i, key } = r, A = r.asset, e = eff(i, key), lk = lookOf(key, e.look);
  const vk = key + ":" + e.look; const vers = st.assetVers[vk] = st.assetVers[vk] || [{ id: 1, n: 1, mode: "原图", instr: "", url: effImg(i, key) }];
  const view = vers.find((v) => v.id === A.base) || vers[vers.length - 1];
  const g = gpuFor("asset");
  const body = `<div class="aed"><div><div class="aimg ${view.n > 1 ? "edited" : ""}">${lk.img || e.refImg ? `<img src="${view.url}">` : `<div class="ph" style="height:100%;display:grid;place-items:center;color:var(--fg3)">${esc(lk.name)}<br>没有图</div>`}${view.n > 1 ? `<span class="al">v${view.n} · ${esc(view.mode)}（占位：原型不真改图）</span>` : ""}</div>
      <div class="vtree" style="margin-top:8px">${vers.map((v) => `<div class="vnode ${v.id === view.id ? "view" : ""}" data-av="${v.id}" style="padding-left:${8 + (v.n > 1 ? 14 : 0)}px"><b>v${v.n}</b><span class="md">${esc(v.mode)}</span><span class="ins">${esc(v.instr)}</span>${v.pending ? `<span class="bd q">生成中</span>` : ""}</div>`).join("")}</div></div>
    <div><div class="rsec"><h5>改资产：${P.CHAR_NAMES[key]} · 形象 ${lk.letter} ${esc(lk.name)}<span>作用在资产图上，不是镜头图</span></h5>
      <div class="lmodes" style="grid-template-columns:repeat(3,1fr)">${[["instr", "指令改图"], ["refs", "换参考"], ["upload", "上传替换"]].map(([k, t]) => `<button data-am="${k}" class="${A.mode === k ? "on" : ""}">${t}</button>`).join("")}</div>
      ${A.mode === "upload" ? `<input type="file" id="aFile" accept="image/*"><div style="font-size:11px;color:var(--fg3);margin-top:4px">原型不上传文件，只演示流程</div>` : `<input type="text" id="aInstr" value="${esc(A.instr)}" placeholder="${A.mode === "refs" ? "选好参考后补一句要求（可选）" : "例如：鞋跟再细一点"}">${A.mode === "instr" ? `<div style="margin-top:8px;font-size:12px">改动幅度 <span class="lseg">${Object.keys(STRENGTH).map((k) => `<button data-ast="${k}" class="${A.strength === k ? "on" : ""}">${k}</button>`).join("")}</span></div>` : `<div style="font-size:12px;color:var(--fg3);margin-top:6px">参考从资产库选（第 6 节面板的单件替换）</div>`}`}
      <div class="gpuline">${gpuLine(g)}</div>
      <div style="margin-top:8px"><span class="gearwrap"><button class="btn sm primary" id="aGo">${A.mode === "upload" ? "替换" : "开始改"}</button>${gear("指令改图")}</span></div></div>
      <div class="rsec"><h5>改完存到哪里</h5><div class="scope">
        ${[["shot", "只这一镜用", "存为本镜覆盖，不动资产库"], ["asset", "存为资产新版本", `资产库新增，${P.CHAR_NAMES[key]} 形象数 +1`], ["ep", "设为本集默认", "项目方本人确认，造型确认需重做"]].map(([k, t, h]) => `<label class="${A.save === k ? "on" : ""}"><input type="radio" name="asave" value="${k}" ${A.save === k ? "checked" : ""}> ${t}<small>${h}</small></label>`).join("")}</div>
        ${A.save === "ep" ? `<div class="ownerbox" style="margin-top:8px"><label style="margin:0"><input type="checkbox" id="aOwner" ${A.ownerOk ? "checked" : ""}> 我是项目方（by=owner）</label></div>` : ""}</div></div></div>`;
  const foot = `<div class="rfoot"><div class="diff">${vers.length > 1 ? `有 ${vers.length - 1} 个修改版本 · 当前看 v${view.n}` : "还没改过"}</div><button class="btn sm" id="rBack">← 返回参考面板</button><button class="btn sm primary" id="aSave" ${view.n > 1 && !view.pending && (A.save !== "ep" || A.ownerOk) ? "" : "disabled"}>保存</button></div>`;
  return { body, foot };
}
function bindAsset(r) {
  const A = r.asset, { i, key } = r, e = eff(i, key), vk = key + ":" + e.look, vers = st.assetVers[vk];
  const on = (sel, fn) => rbox.querySelectorAll(sel).forEach((b) => b.onclick = () => fn(b));
  const keep = () => { const x = $("#aInstr"); if (x) A.instr = x.value; };
  on("[data-am]", (b) => { keep(); A.mode = b.dataset.am; renderRef(); });
  on("[data-ast]", (b) => { keep(); A.strength = b.dataset.ast; renderRef(); });
  on("[data-av]", (b) => { A.base = +b.dataset.av; renderRef(); });
  rbox.querySelectorAll("input[name=asave]").forEach((x) => x.onchange = () => { A.save = x.value; renderRef(); });
  const ow = $("#aOwner"); if (ow) ow.onchange = () => { A.ownerOk = ow.checked; renderRef(); };
  on("#aGo", () => {
    keep();
    if (A.mode !== "upload" && A.mode === "instr" && !A.instr.trim()) return P.toast("先写一句修改要求");
    const base = vers.find((v) => v.id === A.base) || vers[vers.length - 1];
    const v = { id: vers.length + 1, n: vers.length + 1, mode: { instr: "指令改图", refs: "换参考", upload: "上传替换" }[A.mode], instr: A.instr, url: base.url, pending: true, parent: base.id };
    vers.push(v); A.base = v.id; renderRef();
    setTimeout(() => { v.pending = false; if (st.ref === r) renderRef(); P.toast(`资产 v${v.n} 出来了（占位）`); }, 2200);
  });
  on("#aSave", () => {
    const view = vers.find((v) => v.id === A.base) || vers[vers.length - 1];
    const sn = snapshot();
    if (A.save === "shot") { r.draft.refImg = view.url; r.draft.refFrom = `资产编辑 v${view.n}`; r.step = "apply"; r.scope = "shot"; renderRef(); return; }
    if (A.save === "asset") {
      const lks = R[key].looks, ph = lks.find((l) => l.placeholder);
      const nl = { id: `${e.look}-v${view.n}`, letter: ph ? ph.letter : String.fromCharCode(65 + lks.length), name: `${lookOf(key, e.look).name} v${view.n}（原型新增）`, img: view.url, note: "资产编辑存的新版本" };
      if (ph) lks.splice(lks.indexOf(ph), 1, nl); else lks.push(nl);
      r.draft.look = nl.id; r.step = "pick"; renderRef();
      return toastUndo(`已存为资产新版本：${P.CHAR_NAMES[key]} 形象 ${nl.letter}（资产库 +1，原型内存）`, sn);
    }
    const lks = R[key].looks, nl = { id: `${e.look}-v${view.n}`, letter: String.fromCharCode(65 + lks.filter((l) => !l.placeholder).length), name: `${lookOf(key, e.look).name} v${view.n}`, img: view.url };
    const ph = lks.find((l) => l.placeholder); if (ph) lks.splice(lks.indexOf(ph), 1, nl); else lks.push(nl);
    changeEpDefault(key, nl.id);
  });
}

// ================= §8 ⚙ 每处就地覆盖 =================
const PROVIDERS = {
  qwen: { name: "Qwen（gpu3 本地）", base_url: "http://127.0.0.1:18098/v1", models: ["qwen"], key: "na", cost: "免费（自有 GPU）", timeout: 3600, note: "gpu3 GPU1 llama-server :8098，经隧道 18098；不需要密钥", src: "config/script_chat.json · director_boost_llm.json" },
  deepseek: { name: "DeepSeek", base_url: "", models: [], key: "no", cost: "按 token 计费", timeout: 600, note: "OpenAI 兼容接口；地址和模型名以官方文档为准，配置时核对，不在代码里写死", src: "—（新增）" },
  minimax: { name: "MiniMax", base_url: "", models: [], key: "no", cost: "按 token 计费", timeout: 600, note: "OpenAI 兼容接口；地址和模型名以官方文档为准，配置时核对，不在代码里写死", src: "—（新增）" },
  abliteration: { name: "abliteration", base_url: "https://api.abliteration.ai/v1", models: ["abliterated-model"], key: "ok", cost: "较贵（项目方：太贵，仅备选）", timeout: 3600, note: "备选；密钥在 *.local.json，接口只回“已配置”", src: "config/abliteration.local.json · director_boost_llm.local.json" },
};
const IMG_EP = [
  { k: "img21", name: "Image 2.1（ComfyUI / qwen_edit）", url: "http://127.0.0.1:8188（GPU0）· 8189 · 8191", use: "首帧 / 尾帧 / 指令改图" },
  { k: "bridge", name: "gpu3 渲染桥（Image 2.1 + H3）", url: "http://127.0.0.1:15180 → gpu3 :5180", use: "gpu3 出图 / 出视频" },
  { k: "h3", name: "H3 视频", url: "经 gpu3 渲染桥", use: "出视频" },
  { k: "lora", name: "LoRA 训练节点", url: "gpu3（由 Qwen / 调度器排卡）", use: "LoRA 训练" },
  { k: "mailbox", name: "Qwen 信箱", url: "http://127.0.0.1:18099 → gpu3 :8099", use: "Qwen 信箱任务" },
];
const PURPOSES = [
  { k: "剧本写作", p: "qwen", src: "config/script_chat.json" }, { k: "格式返修", p: "qwen", src: "config/script_chat.json" },
  { k: "导演加强", p: "qwen", src: "config/director_boost_llm.json" }, { k: "Qwen 信箱任务", p: "qwen", src: "NS_QWEN_MAILBOX" },
  { k: "首帧提示词改写", p: "qwen", src: "—（新增）" },
];
const IMG_PURPOSES = { "首帧生成": "img21", "指令改图": "img21", "出视频": "h3" };
st.purposeDef = Object.fromEntries(PURPOSES.map((x) => [x.k, { p: x.p, model: PROVIDERS[x.p].models[0] || "", temp: 0.7 }]));
function gear(purpose) { return `<button class="gear ${st.gearOv[purpose] ? "on" : ""}" data-gear="${esc(purpose)}" title="⚙ ${esc(purpose)}：只改这一次的模型设置">⚙</button>`; }
P.gear = gear;
document.addEventListener("click", (e) => {
  const g = e.target.closest("[data-gear]"); if (!g) return;
  e.preventDefault(); e.stopPropagation();
  const k = g.dataset.gear, isImg = IMG_PURPOSES[k];
  const cur = st.gearOv[k] || (isImg ? { ep: IMG_PURPOSES[k], steps: 30 } : { ...(st.purposeDef[k] || st.purposeDef["剧本写作"]) });
  pop.className = "pop gearpop";
  pop.innerHTML = `<h4>⚙ ${esc(k)}</h4><div style="font-size:11px;color:var(--fg3);margin-bottom:8px">只改这一次；或“记为此处默认”。全局默认在 工具 → 模型与 API 配置</div>
    <div class="frm">${isImg ? `<label>端点</label><select id="gEp">${IMG_EP.map((x) => `<option value="${x.k}" ${cur.ep === x.k ? "selected" : ""}>${esc(x.name)}</option>`).join("")}</select><label>卡</label><select id="gCard"><option>gpu3（默认）</option><option>GPU0（笔记本 ComfyUI）</option></select>`
      : `<label>服务商</label><select id="gP">${Object.entries(PROVIDERS).map(([pk, v]) => `<option value="${pk}" ${cur.p === pk ? "selected" : ""}>${esc(v.name)}${v.key === "no" ? "（未配置）" : ""}</option>`).join("")}</select>
      <label>模型</label><select id="gM">${(PROVIDERS[cur.p].models.length ? PROVIDERS[cur.p].models : ["（先在配置页填模型名）"]).map((m) => `<option>${esc(m)}</option>`).join("")}</select>
      <label>温度</label><input type="number" id="gT" step="0.1" min="0" max="2" value="${cur.temp}">`}</div>
    <div class="row"><button class="btn sm" id="gReset">恢复默认</button><button class="btn sm" id="gSaveDef">记为此处默认</button><button class="btn sm primary" id="gOnce">只这一次</button></div>`;
  P.place(pop, g, true);
  const read = () => isImg ? { ep: $("#gEp").value, card: $("#gCard").value } : { p: $("#gP").value, model: $("#gM").value, temp: +$("#gT").value };
  const gp = $("#gP"); if (gp) gp.onchange = () => { st.gearOv[k] = read(); g.click(); };
  $("#gOnce").onclick = () => { st.gearOv[k] = read(); P.closeAll(); P.toast(`⚙ ${k}：下一次调用用这个设置（原型）`); document.querySelectorAll(`[data-gear="${k}"]`).forEach((b) => b.classList.add("on")); };
  $("#gSaveDef").onclick = () => { st.gearOv[k] = read(); P.closeAll(); P.toast(`⚙ ${k}：已记为此处默认（原型内存）`); document.querySelectorAll(`[data-gear="${k}"]`).forEach((b) => b.classList.add("on")); };
  $("#gReset").onclick = () => { delete st.gearOv[k]; P.closeAll(); document.querySelectorAll(`[data-gear="${k}"]`).forEach((b) => b.classList.remove("on")); };
}, true);

// ================= §8.1 剧本创作页 / §8.2 模型与 API 配置页 =================
const SC = st.script = { outline: "", from: 3, to: 5, shots: 6, dur: 60, rules: "rules_v2（现行）", p: "qwen", model: "qwen", temp: 0.8, max: 8192, think: false, ab: false, p2: "deepseek", drafts: {}, tab: 3, running: false, valid: {} };
function scriptPage() {
  const pv = PROVIDERS[SC.p];
  const eps = []; for (let n = SC.from; n <= SC.to; n++) eps.push(n);
  if (!eps.includes(SC.tab)) SC.tab = eps[0];
  const d = SC.drafts[SC.tab] || "", v = SC.valid[SC.tab];
  return `<div class="page"><h2>① 剧本创作 <span class="kst na">原型 · 不写真实剧本内容</span></h2>
    <div class="lead">系统只收发和校验格式，不读不改剧本内容。写完仍由项目方在“剧本导入”页确认。</div>
    <div class="scgrid"><div>
      <div class="card"><h4>1 · 提纲<span>粘贴或上传</span></h4>
        <textarea id="scOutline" rows="7" placeholder="在这里粘贴提纲（原型不保存、不发送）">${esc(SC.outline)}</textarea>
        <div style="margin:8px 0 12px"><input type="file" id="scFile" accept=".txt,.md,.docx"></div>
        <div class="frm"><label>集数范围</label><div class="inl">第 <input type="number" id="scFrom" min="1" max="60" value="${SC.from}"> – <input type="number" id="scTo" min="1" max="60" value="${SC.to}"> 集</div>
          <label>每集目标</label><div class="inl"><input type="number" id="scShots" value="${SC.shots}"> 镜 · <input type="number" id="scDur" value="${SC.dur}"> 秒</div>
          <label>写作规则</label><select id="scRules"><option>rules_v2（现行）</option><option>rules_v1（旧）</option></select></div></div>
      <div class="card"><h4>2 · 模型设置<span>默认 Qwen（gpu3 :8098，免费）</span></h4>
        <div class="frm"><label>服务商</label><div class="inl"><select id="scP">${Object.entries(PROVIDERS).map(([k, x]) => `<option value="${k}" ${SC.p === k ? "selected" : ""}>${esc(x.name)}</option>`).join("")}</select>${keyPill(pv)}</div>
          <label>模型</label><select id="scM">${(pv.models.length ? pv.models : ["（未配置模型名）"]).map((m) => `<option ${SC.model === m ? "selected" : ""}>${esc(m)}</option>`).join("")}</select>
          <label>温度</label><div class="inl"><input type="range" id="scT" min="0" max="1.5" step="0.1" value="${SC.temp}" style="width:160px"><span id="scTv">${SC.temp}</span></div>
          <label>最大输出</label><div class="inl"><input type="number" id="scMax" value="${SC.max}" style="width:96px"> token</div>
          <label>推理</label><label style="display:flex;gap:6px;align-items:center"><input type="checkbox" id="scThink" ${SC.think ? "checked" : ""}> 开启推理（Qwen 默认关，思考 token 会吃上下文）</label>
          <label>费用档</label><span style="color:var(--fg2)">${esc(pv.cost)}</span></div>
        <div style="margin-top:10px;font-size:12px"><label style="display:flex;gap:6px;align-items:center"><input type="checkbox" id="scAB" ${SC.ab ? "checked" : ""}> 同一提纲交给两个模型</label>
          ${SC.ab ? `<div class="inl" style="margin-top:6px;display:flex;gap:6px;align-items:center">第二个：<select id="scP2">${Object.entries(PROVIDERS).filter(([k]) => k !== SC.p).map(([k, x]) => `<option value="${k}" ${SC.p2 === k ? "selected" : ""}>${esc(x.name)}</option>`).join("")}</select>${keyPill(PROVIDERS[SC.p2])} <button class="alink" id="scABLink">结果进 A/B 剧本对比页 →</button></div>` : ""}</div>
        <div style="margin-top:12px;display:flex;gap:8px;align-items:center"><span class="gearwrap"><button class="btn primary" id="scGo" ${SC.running ? "disabled" : ""}>${SC.running ? "写作中…" : `写作 ▶（第 ${SC.from}–${SC.to} 集）`}</button>${gear("剧本写作")}</span>${SC.running ? `<button class="btn sm" id="scStop">停止</button>` : ""}</div></div>
    </div><div>
      <div class="card"><h4>3 · 草稿（按集）<span>流式输出 → 按集落草稿 → 自动格式校验</span></h4>
        <div class="etabs">${eps.map((n) => `<button data-ep="${n}" class="${SC.tab === n ? "on" : ""}">第 ${n} 集${SC.valid[n] ? `<i style="color:var(--green)">✓</i>` : SC.drafts[n] ? "<i>…</i>" : ""}</button>`).join("")}</div>
        <div class="draft" id="scDraft">${esc(d) || `<span style="color:var(--fg3)">还没开始写。点左边“写作”。</span>`}</div>
        ${v ? `<div class="vres ok">格式校验（原型假结果）：${v.shots} 镜 · 字段齐全（画面 / 动作 / 对白 / H3 / 时长）· 时长合计 ${v.dur}s · 1 条提醒：第 ${v.warnShot} 镜时长与目标差 2s</div>
          <div style="margin-top:10px;display:flex;gap:8px"><button class="btn primary" id="scSend">送到剧本导入</button><button class="btn" id="scAB2">和另一个模型的版本 A/B 对比</button></div>` : ""}
      </div></div></div></div>`;
}
const keyPill = (pv) => pv.key === "ok" ? `<span class="kst ok">key 已配置</span>` : pv.key === "na" ? `<span class="kst na">本地 · 无需 key</span>` : `<span class="kst no">key 未配置</span>`;
function bindScript() {
  const c = $("#center"), v = (id) => c.querySelector(id);
  const keep = () => { SC.outline = v("#scOutline").value; SC.from = +v("#scFrom").value; SC.to = Math.max(SC.from, +v("#scTo").value); SC.shots = +v("#scShots").value; SC.dur = +v("#scDur").value; SC.temp = +v("#scT").value; SC.max = +v("#scMax").value; SC.think = v("#scThink").checked; };
  ["#scFrom", "#scTo"].forEach((id) => v(id).onchange = () => { keep(); P.render(); });
  v("#scT").oninput = () => { v("#scTv").textContent = v("#scT").value; };
  v("#scP").onchange = () => { keep(); SC.p = v("#scP").value; SC.model = PROVIDERS[SC.p].models[0] || ""; if (SC.p2 === SC.p) SC.p2 = Object.keys(PROVIDERS).find((k) => k !== SC.p); P.render(); };
  v("#scAB").onchange = () => { keep(); SC.ab = v("#scAB").checked; P.render(); };
  const p2 = v("#scP2"); if (p2) p2.onchange = () => { keep(); SC.p2 = p2.value; P.render(); };
  const ab = v("#scABLink"); if (ab) ab.onclick = () => P.toast("A/B 剧本对比页：两份草稿并排（现有页面，原型略）");
  const ab2 = v("#scAB2"); if (ab2) ab2.onclick = () => P.toast("A/B 剧本对比页：两份草稿并排（现有页面，原型略）");
  c.querySelectorAll("[data-ep]").forEach((b) => b.onclick = () => { keep(); SC.tab = +b.dataset.ep; P.render(); });
  const send = v("#scSend"); if (send) send.onclick = () => P.toast(`第 ${SC.tab} 集草稿已送到“剧本导入”，仍需你在导入页确认（原型）`);
  const stop = v("#scStop"); if (stop) stop.onclick = () => { SC.running = false; clearInterval(SC.timer); P.render(); };
  v("#scGo").onclick = () => {
    keep();
    const pv = PROVIDERS[SC.p];
    if (pv.key === "no") return P.toast(`${pv.name} 还没配置 key：工具 → 模型与 API 配置`);
    SC.running = true; SC.drafts = {}; SC.valid = {};
    const eps = []; for (let n = SC.from; n <= SC.to; n++) eps.push(n);
    let ei = 0, line = 0; SC.tab = eps[0];
    SC.timer = setInterval(() => {
      const n = eps[ei];
      if (n === undefined) { SC.running = false; clearInterval(SC.timer); P.render(); return; }
      SC.drafts[n] = SC.drafts[n] || `# 第 ${n} 集（${pv.name} · ${SC.model} · 温度 ${SC.temp}）\n`;
      if (line < SC.shots) { line++; SC.drafts[n] += `\n【示例输出占位】第 ${n} 集 · 镜 ${line}\n  画面：【占位】\n  动作 / 运镜：【占位】\n  对白：【占位】\n  H3：【占位】\n  时长：${Math.round(SC.dur / SC.shots)}s\n`; }
      else { SC.valid[n] = { shots: SC.shots, dur: Math.round(SC.dur / SC.shots) * SC.shots, warnShot: Math.min(2, SC.shots) }; ei++; line = 0; SC.tab = eps[ei] ?? n; }
      if (st.mode === "script") { P.render(); const dr = $("#scDraft"); if (dr) dr.scrollTop = dr.scrollHeight; }
    }, 260);
    P.render();
  };
}
const API = st.api = { test: {}, keys: Object.fromEntries(Object.entries(PROVIDERS).map(([k, v]) => [k, v.key])) };
function apiPage() {
  return `<div class="page"><h2>模型与 API 配置 <span class="kst na">原型 · 不读写任何文件</span></h2>
    <div class="lead">服务商清单存 config/llm_providers.json（不含密钥）；密钥只写 config/llm_providers.local.json 或环境变量，接口只返回“已配置 / 未配置”，永远不回传密钥。旧的 script_chat.json / director_boost_llm*.json / abliteration.local.json 迁移进来（保留读兼容）。下面的地址取自现有 config/ 与 services/ 默认值。</div>
    <div class="card"><h4>服务商<span>文本模型</span></h4><div class="prov">${Object.entries(PROVIDERS).map(([k, v]) => `
      <div class="card"><h4>${esc(v.name)} ${API.keys[k] === "ok" ? `<span class="kst ok">key 已配置</span>` : API.keys[k] === "na" ? `<span class="kst na">本地 · 无需 key</span>` : `<span class="kst no">key 未配置</span>`}</h4>
        <div class="frm"><label>base_url</label><input type="text" data-pf="${k}:base_url" value="${esc(v.base_url)}" placeholder="按官方文档填写"><label>模型</label><input type="text" data-pf="${k}:models" value="${esc(v.models.join(", "))}" placeholder="按官方文档填写，逗号分隔">
          <label>超时（秒）</label><input type="number" data-pf="${k}:timeout" value="${v.timeout}">
          ${v.key !== "na" ? `<label>密钥</label><div class="inl" style="flex-wrap:nowrap"><input type="password" data-key="${k}" autocomplete="off" placeholder="${API.keys[k] === "ok" ? "已配置（不回显）· 输入新值可覆盖" : "未配置 · 只写不读"}"><button class="btn sm" data-savekey="${k}">保存</button></div>` : ""}
          <label>费用档</label><span style="color:var(--fg2)">${esc(v.cost)}</span><label>来源</label><code style="font-size:11px;color:var(--fg3)">${esc(v.src)}</code></div>
        <div style="font-size:11px;color:var(--fg3);margin-top:6px">${esc(v.note)}</div>
        <div style="margin-top:8px;display:flex;gap:8px;align-items:center"><button class="btn sm" data-test="${k}">测试连接</button>${testRes(k)}</div></div>`).join("")}</div></div>
    <div class="card"><h4>按用途的默认<span>每个用途一行；画布里每个 ⚙ 可以只改一次或记为此处默认</span></h4>
      <table class="tbl"><tr><th>用途</th><th>服务商</th><th>模型</th><th>温度</th><th>现在的来源</th></tr>${PURPOSES.map((x) => { const d = st.purposeDef[x.k]; return `<tr><td>${esc(x.k)}</td><td><select data-pp="${esc(x.k)}">${Object.entries(PROVIDERS).map(([k, v]) => `<option value="${k}" ${d.p === k ? "selected" : ""}>${esc(v.name)}</option>`).join("")}</select></td><td><select>${(PROVIDERS[d.p].models.length ? PROVIDERS[d.p].models : ["（未配置）"]).map((m) => `<option>${esc(m)}</option>`).join("")}</select></td><td><input type="number" step="0.1" value="${d.temp}" style="width:64px"></td><td><code>${esc(x.src)}</code></td></tr>`; }).join("")}</table></div>
    <div class="card"><h4>图像 / 视频 / 训练<span>连通状态</span></h4>
      <table class="tbl"><tr><th>端点</th><th>地址</th><th>用在</th><th>状态</th><th></th></tr>${IMG_EP.map((x) => `<tr><td>${esc(x.name)}</td><td><code>${esc(x.url)}</code></td><td>${esc(x.use)}</td><td>${testRes(x.k) || `<span class="cdot"></span>未测`}</td><td><button class="btn sm" data-test="${x.k}">测试连接</button></td></tr>`).join("")}</table></div></div>`;
}
const testRes = (k) => { const t = API.test[k]; if (!t) return ""; return t === "run" ? `<span><span class="cdot run"></span>测试中…</span>` : t === "nokey" ? `<span><span class="cdot bad"></span>未配置密钥</span>` : `<span><span class="cdot ok"></span>连通（原型假结果）</span>`; };
function bindApi() {
  const c = $("#center");
  c.querySelectorAll("[data-test]").forEach((b) => b.onclick = () => {
    const k = b.dataset.test;
    API.test[k] = "run"; P.render();
    setTimeout(() => { API.test[k] = API.keys[k] === "no" ? "nokey" : "ok"; if (st.mode === "api") P.render(); }, 900);
  });
  c.querySelectorAll("[data-savekey]").forEach((b) => b.onclick = () => {
    const k = b.dataset.savekey, inp = c.querySelector(`[data-key="${k}"]`);
    if (!inp.value) return P.toast("先输入密钥");
    inp.value = ""; API.keys[k] = "ok"; PROVIDERS[k].key = "ok";
    P.toast(`${PROVIDERS[k].name} 密钥已写入（原型不保存；正式版只写 *.local.json，读回只显示“已配置”）`); P.render();
  });
  c.querySelectorAll("[data-pf]").forEach((x) => x.onchange = () => { const [k, f] = x.dataset.pf.split(":"); PROVIDERS[k][f] = f === "models" ? x.value.split(",").map((s) => s.trim()).filter(Boolean) : f === "timeout" ? +x.value : x.value; });
  c.querySelectorAll("[data-pp]").forEach((x) => x.onchange = () => { const d = st.purposeDef[x.dataset.pp]; d.p = x.value; d.model = PROVIDERS[x.value].models[0] || ""; P.render(); });
}
H.page = (mode) => {
  const c = $("#center");
  const keepScroll = c.querySelector(".page")?.scrollTop || 0;
  c.innerHTML = mode === "script" ? scriptPage() : apiPage();
  const pg = c.querySelector(".page"); if (pg) pg.scrollTop = keepScroll;
  if (mode === "script") bindScript(); else bindApi();
};

// ---------- 键盘：参考面板优先 ----------
H.keydown = (e) => {
  if (rmodal.classList.contains("on")) { if (e.key === "Escape") closeRef(); return true; }
  return false;
};
H.after = () => {
  // 出视频按钮旁的 ⚙（H3）
  const bv = $("#bVideo"); if (bv && !bv.parentElement.classList.contains("gearwrap")) { const w = document.createElement("span"); w.className = "gearwrap"; bv.replaceWith(w); w.appendChild(bv); w.insertAdjacentHTML("beforeend", gear("出视频")); bv.style.flex = "1"; }
  const q = P.q;
  if (q.get("refpanel")) { const [i, k, step] = q.get("refpanel").split(":"); openRef(+i - 1, k); if (k !== "scene") { const r = st.ref; if (step === "apply") { r.draft.parts.shoes = R[k].parts.shoes[1]?.id || R[k].parts.shoes[0]?.id; r.draft.look = R[k].looks[1].id; r.scope = "after"; r.step = "apply"; } else { r.draft.parts.shoes = R[k].parts.shoes[1]?.id; } renderRef(); } }
  if (q.get("loopdemo")) {
    const sh = P.cur(); const c = P.selCand(sh, "first");
    P.unlockFirst(sh);
    const n1 = P.addCand(sh, "first", false, { parent: c.id, mode: "指令改图", instr: "（原型演示：项目方原话原样记录在这里）", strength: "中（denoise 0.55）", label: "指令改图 · 幅度 中（占位）", gpu: "gpu3 · Image 2.1 · qwen_edit" });
    const n2 = P.addCand(sh, "first", false, { parent: n1.id, mode: "换参考再改", instr: "", refs: refsSummary(st.cur), label: "换参考再改（占位）", gpu: "gpu3 · Image 2.1 · qwen_edit 多参考" });
    sh.sel.first = n2.id; st.rtab = "ver"; st.vslot = "first"; st.vpick = n2.id;
    st.loop = { mode: "instr", strength: "中", instr: "（原型演示）", base: n2.id };
    const n3 = P.addCand(sh, "first", false, { parent: n2.id, mode: "指令改图", instr: "（原型演示：第二句修改要求）", strength: "小（denoise 0.35）", label: "指令改图 · 幅度 小（占位）" });
    n3.pending = "queued"; st.queue.push({ sh, i: st.cur, slot: "first", node: n3, dur: 1e9 });
    pump();
    P.render();
    if (q.get("loopdemo") === "pop") setTimeout(() => openLoop($("#bAsk")), 50);
  }
};
})();
