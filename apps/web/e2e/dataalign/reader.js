(async () => {
  const tab = [...document.querySelectorAll('.ns-viewsw button')].find((b) => b.innerText.includes('阅读模式'));
  if (tab) tab.click();
  await new Promise((r) => setTimeout(r, 6000));
  const rows = [...document.querySelectorAll('.er-shot')].map((r) => ({
    id: r.querySelector('.er-no')?.innerText,
    img: r.querySelector('.er-pic img')?.getAttribute('src') || null,
    title: r.querySelector('.er-pic')?.getAttribute('title'),
    cast: r.querySelector('.er-cast')?.innerText || '',
  }));
  return { hash: location.hash, rows };
})()
