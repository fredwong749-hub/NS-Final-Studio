(() => { const d = document.querySelector('section.drawer'); return { text: d ? d.innerText.slice(0, 3000) : null, top: (document.querySelector('.v3-top-r')||{}).innerText }; })()
