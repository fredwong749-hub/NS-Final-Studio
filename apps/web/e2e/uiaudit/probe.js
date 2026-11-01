// UIAUDIT probe：当前可见界面的“能力清单”（只读）。对应 UI_CONTRACT 的操作列。
(() => {
  const vis = (e) => {
    const r = e.getBoundingClientRect();
    const s = getComputedStyle(e);
    return r.width > 1 && r.height > 1 && r.bottom > 0 && r.top < innerHeight * 3 && s.visibility !== "hidden" && s.display !== "none" && +s.opacity > 0.05;
  };
  const ctrls = [...document.querySelectorAll("button, a[href], [role=button], [role=tab], summary, input, select, textarea")].filter(vis);
  const label = (e) => (e.innerText || e.getAttribute("aria-label") || e.getAttribute("title") || e.getAttribute("placeholder") || e.value || "").replace(/\s+/g, " ").trim().slice(0, 30);
  const labels = ctrls.map(label).filter(Boolean);
  const has = (re) => labels.filter((t) => re.test(t));
  const imgs = [...document.querySelectorAll("img")].filter(vis);
  const vids = [...document.querySelectorAll("video")].filter(vis);
  const auds = [...document.querySelectorAll("audio")];
  const text = document.body.innerText;
  const fsz = {};
  for (const e of [...document.querySelectorAll("body *")].filter(vis).slice(0, 4000)) {
    if (![...e.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())) continue;
    const k = Math.round(parseFloat(getComputedStyle(e).fontSize));
    fsz[k] = (fsz[k] ?? 0) + 1;
  }
  return {
    url: location.hash,
    title: document.querySelector("h1, h2, .v3-page h3")?.innerText?.slice(0, 60) ?? null,
    nCtrl: ctrls.length,
    img: imgs.length,
    imgBig: imgs.filter((i) => i.getBoundingClientRect().width >= 320).length,
    imgTiny: imgs.filter((i) => i.getBoundingClientRect().width < 96).length,
    video: vids.length,
    videoControls: vids.filter((v) => v.controls).length,
    audio: auds.length,
    fileInput: document.querySelectorAll("input[type=file]").length,
    textarea: document.querySelectorAll("textarea").length,
    play: has(/播放|试听|▶|►|play/i),
    edit: has(/编辑|修改|改这|改原文|返修|重写|提议/),
    del: has(/删除|移除|作废|回收站|🗑/),
    trash: has(/回收站/),
    history: has(/版本|历史|回滚|v\d|#\d/),
    compare: has(/对比|AB|A\/B|并排/),
    pick: has(/选定|采用|设为当前|用这|定稿|确认|接受|通过/),
    undo: has(/撤销|还原|恢复/),
    upload: has(/上传|导入|拖|粘贴/),
    create: has(/新建|新增|＋|\+ /),
    batch: has(/批量|全选|全部/),
    techLeak: (text.match(/\b(sid|cid|rev|seq|zf_\d+|zm_\d+|S\d+t\d|take|lora|json|api\/)\b/gi) || []).length,
    errorsShown: (text.match(/读不到|失败|出错|404|Not Found|接口.*重启/g) || []).length,
    fontSizes: fsz,
    sampleCtrls: labels.slice(0, 80),
  };
})();
