(() => {
  const d = document.querySelector('section.drawer');
  if (!d) return { ok: false, why: 'no drawer' };
  const head = d.querySelector('.drawer-tabs [role=tab]');
  const tabs = [...d.querySelectorAll('.rt-tools [role=tab]')].map((b) => b.innerText.replace(/\s+/g, ''));
  const failTab = tabs.find((t) => t.startsWith('失败')) || '';
  const runTab = tabs.find((t) => t.startsWith('渲染中')) || '';
  const badge = head ? head.innerText.replace(/\s+/g, '') : '';
  const n = (s) => Number((s.match(/(\d+)$/) || [0, 0])[1]);
  const m = /失败(\d+)$/.exec(badge) || /渲染中(\d+)$/.exec(badge);
  const ok = !m ? n(failTab) === 0 : badge.includes('失败') ? Number(m[1]) === n(failTab) : Number(m[1]) === n(runTab);
  return { ok, badge, failTab, runTab, ep: (d.querySelector('.rt-tools select') || {}).value };
})()
