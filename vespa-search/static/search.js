function extractRows(data, maxSnippet = 160) {
  const root = (data && data.root) || {};
  const hits = root.children || [];
  return hits.map((h, idx) => {
    const fields = h.fields || {};
    const rawId = h.id || '';
    let dealId = fields.deal_id;
    if (!dealId && rawId.includes('::')) {
      dealId = rawId.split('::', 2)[1];
    }
    const snippet = (fields.document || '').slice(0, maxSnippet).replace(/\n/g, ' ');
    
    // Získáme informaci o zdroji pro hybrid search
    const source = fields._source || '';
    let sourceLabel = '';
    if (source === 'text') {
      sourceLabel = 'Text';
    } else if (source === 'vector') {
      sourceLabel = 'Vector';
    } else if (source === 'both') {
      sourceLabel = 'Both';
    } else if (source === 'hybrid') {
      sourceLabel = 'Hybrid';
    } else if (source === 'unknown') {
      sourceLabel = 'Unknown';
    } else {
      sourceLabel = 'None'; // Pro debug
    }
    
    return {
      rank: idx + 1,
      score: typeof h.relevance === 'number' ? h.relevance : (Number(h.relevance) || 0),
      id: dealId || rawId,
      category: fields.category_id || '',
      text: snippet,
      source: sourceLabel
    };
  });
}

function renderTable(title, rows) {
  if (!rows || rows.length === 0) {
    return `<div class="section"><h3>${title}</h3><div class="muted">Žádné výsledky.</div></div>`;
  }
  
  // Pro hybrid search přidáme sloupec source
  const isHybrid = title === 'Hybrid';
  const header = isHybrid 
    ? `<tr><th>#</th><th>score</th><th>source</th><th>id</th><th>category</th><th>text</th></tr>`
    : `<tr><th>#</th><th>score</th><th>id</th><th>category</th><th>text</th></tr>`;
  
  const body = rows.map(r => {
    if (isHybrid) {
      return `<tr><td>${r.rank}</td><td>${r.score.toFixed(6)}</td><td>${r.source || ''}</td><td>${r.id}</td><td>${r.category}</td><td>${r.text}…</td></tr>`;
    } else {
      return `<tr><td>${r.rank}</td><td>${r.score.toFixed(6)}</td><td>${r.id}</td><td>${r.category}</td><td>${r.text}…</td></tr>`;
    }
  }).join('');
  
  return `<div class="section"><h3>${title}</h3><table>${header}${body}</table></div>`;
}

            async function doSearch() {
        const q = document.getElementById('q').value.trim();
        const method = document.getElementById('method').value;
        const limit = parseInt(document.getElementById('limit').value || '10', 10);
        const k = parseInt(document.getElementById('k').value || '100', 10);
        const exact = document.getElementById('exact').checked;
        
        // GPS parametry
        const gpsLat = document.getElementById('gps_lat').value;
        const gpsLon = document.getElementById('gps_lon').value;
        const gpsRadius = document.getElementById('gps_radius').value;
        
        const out = document.getElementById('out');
        if (!q) { out.textContent = 'Zadejte dotaz.'; return; }
        out.textContent = 'Vyhledávám…';
        try {
          const params = new URLSearchParams({ q, limit: String(limit) });
          if (method !== 'fulltext') {
            params.set('k', String(k));
            if (exact) params.set('exact', 'true');
          }
          
          // Přidáme GPS parametry, pokud jsou vyplněné
          if (gpsLat && gpsLon && gpsRadius) {
            params.set('lat', gpsLat);
            params.set('lon', gpsLon);
            params.set('radius', gpsRadius);
          }
          
          const res = await fetch(`/search/${method}?` + params.toString());
          const data = await res.json();
          const rows = extractRows(data);
          out.classList.remove('muted');
          const tableTitle = method === 'fulltext' ? 'Fulltext' : (method === 'embedding' ? 'Embedding (ANN)' : 'Hybrid');
          out.innerHTML = renderTable(tableTitle, rows);
          
          // Debug info pro hybrid search
          if (method === 'hybrid') {
            console.log('Hybrid results:', rows);
            console.log('Source distribution:', rows.reduce((acc, r) => {
              acc[r.source] = (acc[r.source] || 0) + 1;
              return acc;
            }, {}));
            console.log('Raw data from server:', data);
          }
        } catch (e) {
          out.textContent = String(e);
        }
      }

// GPS funkcionalita
function getCurrentLocation() {
  if (navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(
      function(position) {
        document.getElementById('gps_lat').value = position.coords.latitude.toFixed(6);
        document.getElementById('gps_lon').value = position.coords.longitude.toFixed(6);
      },
      function(error) {
        console.error('GPS error:', error);
        alert('Nepodařilo se získat GPS pozici: ' + error.message);
      }
    );
  } else {
    alert('Prohlížeč nepodporuje GPS');
  }
}

// Add event listener when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
  document.getElementById('q').addEventListener('keydown', (e) => { 
    if (e.key === 'Enter') doSearch(); 
  });
});
