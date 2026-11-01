(() => { const z = document.querySelector('.zl-box'); return { zoom: !!z, zoomText: z ? z.innerText.slice(0,200) : null, img: z ? (z.querySelector('img')||{}).src : null }; })()
