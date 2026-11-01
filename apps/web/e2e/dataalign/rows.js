(() => {
  const rows = [...document.querySelectorAll('.sf-fullrows > *')].map((r) => ({
    head: (r.querySelector('h3, .v3-row-h, b')?.innerText || '').slice(0, 20),
    people: [...r.querySelectorAll('.v3-people .v3-look:not(.scene)')].map((b) => ({ name: b.querySelector('.v3-look-name')?.innerText, letter: b.querySelector('i')?.innerText, img: b.querySelector('img')?.getAttribute('src') || null, title: b.getAttribute('title') })),
    scene: r.querySelector('.v3-look.scene .v3-look-name')?.innerText,
    text: (r.innerText || '').replace(/\s+/g, ' ').slice(0, 200),
  }));
  return { hash: location.hash, rows };
})()
