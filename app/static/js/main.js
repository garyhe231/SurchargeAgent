/* SurchargeAgent — main dashboard JS */

let _dashboardData = null;
let _allNotices = [];
let _charts = {};
let _activeBunkerGrade = 'VLSFO';

// ── Init ─────────────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', async () => {
  updateFooterTime();
  setInterval(updateFooterTime, 60000);
  await loadDashboard();
  await loadBrief();
});

function updateFooterTime() {
  const el = document.getElementById('footerTime');
  if (el) el.textContent = new Date().toLocaleString();
}

// ── Load Dashboard ────────────────────────────────────────────────────────────
async function loadDashboard() {
  try {
    const resp = await fetch('/api/dashboard');
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    _dashboardData = data;
    _allNotices = data.recent_notices || [];

    renderKPIs(data);
    renderAlertBanner(data);
    renderLaneRisks(data.lane_risks || []);
    renderBunkerCharts(data);
    renderSurchargeTypeChart(data);
    renderCarrierExposure(data.carrier_exposure || []);
    renderBunkerTable(data);
    renderNoticesTable(_allNotices, data.surcharge_type_labels || {});
    renderRiskZones(data.risk_zones || {}, data.lane_risks || []);
    populateFilters(data);

    document.getElementById('asOf').textContent = `Data as of ${data.as_of}`;
  } catch (err) {
    console.error('Dashboard load failed:', err);
  }
}

// ── KPIs ──────────────────────────────────────────────────────────────────────
function renderKPIs(data) {
  document.getElementById('kpiCritical').textContent = data.critical_alerts ?? '—';
  document.getElementById('kpiNotices').textContent  = data.total_notices ?? '—';
  document.getElementById('kpiCarriers').textContent = data.carriers_active ?? '—';

  const sgBunker = data.bunker_summary?.Singapore;
  const vlsfo = sgBunker?.VLSFO;
  document.getElementById('kpiVlsfo').textContent = vlsfo ? `$${vlsfo}` : '—';

  const vol = data.bunker_volatility;
  document.getElementById('kpiBunkerVol').textContent = vol != null ? (vol * 100).toFixed(1) + '%' : '—';
}

// ── Alert Banner ──────────────────────────────────────────────────────────────
function renderAlertBanner(data) {
  const banner = document.getElementById('alertBanner');
  const textEl = document.getElementById('alertText');
  const critical = data.critical_notices || [];
  if (critical.length > 0) {
    banner.style.display = 'flex';
    const carriers = [...new Set(critical.map(n => n.carrier).filter(Boolean))].slice(0, 3);
    textEl.textContent = `${critical.length} CRITICAL surcharge alerts active — ${carriers.join(', ')} issuing emergency notices`;
  }
}

// ── Trade Lane Risk ───────────────────────────────────────────────────────────
function renderLaneRisks(risks) {
  const container = document.getElementById('laneRiskList');
  if (!risks.length) {
    container.innerHTML = '<p class="muted">No risk data yet. Click Refresh Data.</p>';
    return;
  }
  container.innerHTML = risks.map(r => {
    const lanePath = encodeURIComponent(r.lane);
    return `
    <a class="lane-item" href="/lane/${lanePath}">
      <div>
        <div class="lane-name">${r.lane}</div>
        <div class="lane-zones">${(r.affected_zones || []).join(' • ') || 'No active zones'}</div>
      </div>
      <div class="score-bar-container">
        <div class="score-bar-bg">
          <div class="score-bar-fill" style="width:${r.composite_score}%;background:${r.tier_color}"></div>
        </div>
        <div style="font-size:0.68rem;color:var(--text-muted);margin-top:3px">
          ${r.notice_count} notice${r.notice_count !== 1 ? 's' : ''}
          • ${(r.active_surcharge_types || []).slice(0, 3).join(' ')}
        </div>
      </div>
      <div>
        <span class="risk-pill" style="background:${r.tier_color}">${r.tier}</span>
        <div style="font-size:0.78rem;font-weight:700;text-align:center;margin-top:4px">${r.composite_score}</div>
      </div>
    </a>`;
  }).join('');
}

// ── Bunker Charts ─────────────────────────────────────────────────────────────
function renderBunkerCharts(data) {
  const vlsfo = data.vlsfo_series || [];
  const mgo   = data.mgo_series   || [];
  const ifo   = data.ifo_series   || [];

  if (vlsfo.length === 0 && mgo.length === 0) {
    // Show placeholder message in each canvas parent
    ['chartVlsfo','chartMgo','chartIfo'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.parentElement.innerHTML += '<p class="muted" style="padding:20px 0 10px;text-align:center">Collecting bunker data...</p>';
    });
    return;
  }

  const chartConfig = (series, color, label) => ({
    type: 'line',
    data: {
      labels: series.map(s => s.date),
      datasets: [{
        label: label,
        data: series.map(s => s.price_usd_mt),
        borderColor: color,
        backgroundColor: color + '22',
        fill: true,
        tension: 0.3,
        pointRadius: series.length > 20 ? 0 : 3,
        pointHoverRadius: 5,
        borderWidth: 2,
      }]
    },
    options: {
      responsive: true,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#1e2435',
          borderColor: '#2a3148',
          borderWidth: 1,
          titleColor: '#e2e8f0',
          bodyColor: '#94a3b8',
          callbacks: {
            label: ctx => ` $${ctx.parsed.y.toFixed(2)}/MT`
          }
        }
      },
      scales: {
        x: {
          grid: { color: '#2a3148' },
          ticks: { color: '#64748b', maxTicksLimit: 6, font: { size: 10 } }
        },
        y: {
          grid: { color: '#2a3148' },
          ticks: { color: '#64748b', font: { size: 10 }, callback: v => `$${v}` }
        }
      }
    }
  });

  destroyChart('chartVlsfo');
  destroyChart('chartMgo');
  destroyChart('chartIfo');
  _charts.vlsfo = new Chart(document.getElementById('chartVlsfo'), chartConfig(vlsfo, '#6366f1', 'VLSFO'));
  _charts.mgo   = new Chart(document.getElementById('chartMgo'),   chartConfig(mgo,   '#3b82f6', 'MGO'));
  _charts.ifo   = new Chart(document.getElementById('chartIfo'),   chartConfig(ifo,   '#eab308', 'IFO380'));
}

function destroyChart(id) {
  if (_charts[id]) { _charts[id].destroy(); delete _charts[id]; }
}

// ── Surcharge Type Distribution ───────────────────────────────────────────────
function renderSurchargeTypeChart(data) {
  const dist = data.type_distribution || {};
  const labels = Object.keys(dist);
  const labels_full = Object.keys(dist).map(k => `${k} — ${(data.surcharge_type_labels || {})[k] || k}`);
  const values = Object.values(dist);
  if (!labels.length) return;

  const colors = [
    '#ef4444','#f97316','#eab308','#22c55e','#14b8a6',
    '#3b82f6','#6366f1','#a855f7','#ec4899','#06b6d4',
    '#84cc16','#f59e0b','#10b981','#8b5cf6','#64748b',
  ];

  destroyChart('chartTypes');
  _charts.types = new Chart(document.getElementById('chartTypes'), {
    type: 'doughnut',
    data: {
      labels: labels_full,
      datasets: [{
        data: values,
        backgroundColor: colors.slice(0, labels.length),
        borderColor: '#161b27',
        borderWidth: 2,
        hoverOffset: 6,
      }]
    },
    options: {
      responsive: true,
      plugins: {
        legend: {
          position: 'right',
          labels: {
            color: '#94a3b8',
            font: { size: 11 },
            boxWidth: 12,
            padding: 10,
          }
        },
        tooltip: {
          backgroundColor: '#1e2435',
          borderColor: '#2a3148',
          borderWidth: 1,
          titleColor: '#e2e8f0',
          bodyColor: '#94a3b8',
        }
      }
    }
  });
}

// ── Carrier Exposure ──────────────────────────────────────────────────────────
function renderCarrierExposure(carriers) {
  const container = document.getElementById('carrierList');
  if (!carriers.length) {
    container.innerHTML = '<p class="muted">No carrier data yet.</p>';
    return;
  }
  const maxScore = Math.max(...carriers.map(c => c.exposure_score), 1);
  container.innerHTML = carriers.slice(0, 10).map(c => {
    const width = (c.exposure_score / maxScore * 100).toFixed(0);
    const criticalTypes = ['WRS','RSA','EBS','ECS'].filter(t => (c.surcharge_types||[]).includes(t));
    const isCritical = criticalTypes.length > 0;
    return `
    <div class="carrier-item" style="${isCritical ? 'border-left:3px solid var(--red)' : ''}">
      <div class="carrier-row">
        <span class="carrier-name">${c.carrier}</span>
        <span class="carrier-score">${c.notice_count} notices • score ${c.exposure_score}</span>
      </div>
      <div style="background:var(--bg);border-radius:3px;height:4px;margin-bottom:6px;overflow:hidden">
        <div style="width:${width}%;height:100%;background:${isCritical ? 'var(--red)':'var(--accent)'};border-radius:3px"></div>
      </div>
      <div class="carrier-types">
        ${(c.surcharge_types||[]).map(t => {
          const cls = ['WRS','RSA'].includes(t) ? ' wrs' : ['EBS','ECS'].includes(t) ? ' ebs' : ['BAF','LSS'].includes(t) ? ' baf' : '';
          return `<span class="surcharge-tag${cls}">${t}</span>`;
        }).join('')}
      </div>
      ${c.trade_lanes && c.trade_lanes.length ? `<div class="carrier-lanes">${c.trade_lanes.slice(0,2).join(' • ')}</div>` : ''}
    </div>`;
  }).join('');
}

// ── Bunker Hub Table ──────────────────────────────────────────────────────────
function renderBunkerTable(data) {
  const summary = data.bunker_summary || {};
  const tbody = document.getElementById('bunkerTableBody');
  if (!Object.keys(summary).length) {
    tbody.innerHTML = '<tr><td colspan="5" class="muted">No bunker data yet.</td></tr>';
    return;
  }

  const hubs = Object.keys(summary);
  const allVlsfo = hubs.map(h => summary[h]?.VLSFO).filter(Boolean);
  const avgVlsfo = allVlsfo.length ? allVlsfo.reduce((a,b)=>a+b,0)/allVlsfo.length : 0;

  tbody.innerHTML = hubs.map(hub => {
    const v = summary[hub]?.VLSFO;
    const m = summary[hub]?.MGO;
    const i = summary[hub]?.IFO380;
    const diff = v && avgVlsfo ? v - avgVlsfo : null;
    const diffClass = diff == null ? '' : diff > 5 ? 'price-up' : diff < -5 ? 'price-down' : 'price-neu';
    const diffText = diff == null ? '—' : `${diff > 0 ? '+' : ''}${diff.toFixed(1)}`;
    return `
    <tr>
      <td><strong>${hub}</strong></td>
      <td>${v ? `$${v.toFixed(2)}` : '—'}</td>
      <td>${m ? `$${m.toFixed(2)}` : '—'}</td>
      <td>${i ? `$${i.toFixed(2)}` : '—'}</td>
      <td class="${diffClass}">${diffText}</td>
    </tr>`;
  }).join('');
}

function filterBunkerTable(grade, btn) {
  _activeBunkerGrade = grade;
  document.querySelectorAll('.grade-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  // Highlight column — simplistic version: bold the selected grade column
  const idx = { VLSFO: 1, MGO: 2, IFO380: 3 }[grade] || 1;
  document.querySelectorAll('#bunkerTable th, #bunkerTable td').forEach((cell, i) => {
    const colIdx = i % 5;
    cell.style.opacity = (colIdx === 0 || colIdx === idx || colIdx === 4) ? '1' : '0.3';
  });
}

// ── Notices Table ─────────────────────────────────────────────────────────────
function renderNoticesTable(notices, typeLabels) {
  const tbody = document.getElementById('noticesTableBody');
  if (!notices.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="muted" style="padding:20px">No notices collected yet. Click "Refresh Data".</td></tr>';
    return;
  }
  tbody.innerHTML = notices.map(n => {
    const types = (n.surcharge_types || []).map(t => {
      const cls = ['WRS','RSA'].includes(t) ? ' wrs' : ['EBS','ECS'].includes(t) ? ' ebs' : ['BAF','LSS'].includes(t) ? ' baf' : '';
      return `<span class="surcharge-tag${cls}" title="${typeLabels[t]||t}">${t}</span>`;
    }).join('');
    const lanes = (n.trade_lanes || []).map(l =>
      `<span style="font-size:0.7rem;color:var(--text-muted)">${l}</span>`
    ).join('<br>');
    return `
    <tr>
      <td><strong>${n.carrier || '—'}</strong></td>
      <td>
        ${n.source_url
          ? `<a href="${n.source_url}" target="_blank" class="notice-link">${n.title}</a>`
          : `<span class="notice-link">${n.title}</span>`}
      </td>
      <td>${types || '—'}</td>
      <td>${lanes || '—'}</td>
      <td>${n.amount || '—'}</td>
      <td>${n.effective_date || '—'}</td>
      <td style="font-size:0.7rem;color:var(--text-muted)">${sourceDomain(n.source_feed)}</td>
    </tr>`;
  }).join('');
}

function sourceDomain(url) {
  if (!url) return '—';
  try { return new URL(url).hostname.replace('www.',''); } catch { return url.slice(0,30); }
}

function populateFilters(data) {
  const carriers = [...new Set(_allNotices.map(n => n.carrier).filter(Boolean))].sort();
  const types = Object.keys(data.type_distribution || {}).sort();
  const lanes = [...new Set(_allNotices.flatMap(n => n.trade_lanes || []))].sort();

  const fillSelect = (id, opts) => {
    const el = document.getElementById(id);
    if (!el) return;
    opts.forEach(v => {
      const opt = document.createElement('option');
      opt.value = v; opt.textContent = v;
      el.appendChild(opt);
    });
  };
  fillSelect('filterCarrier', carriers);
  fillSelect('filterType', types);
  fillSelect('filterLane', lanes);
}

function filterNotices() {
  const carrier = document.getElementById('filterCarrier')?.value || '';
  const type    = document.getElementById('filterType')?.value || '';
  const lane    = document.getElementById('filterLane')?.value || '';
  let filtered = _allNotices;
  if (carrier) filtered = filtered.filter(n => n.carrier === carrier);
  if (type)    filtered = filtered.filter(n => (n.surcharge_types||[]).includes(type));
  if (lane)    filtered = filtered.filter(n => (n.trade_lanes||[]).includes(lane));
  renderNoticesTable(filtered, (_dashboardData?.surcharge_type_labels || {}));
}

// ── Geopolitical Risk Zones ───────────────────────────────────────────────────
function renderRiskZones(zones, laneRisks) {
  const container = document.getElementById('riskZones');
  const zoneRiskScores = {
    'Red Sea / Hormuz': 88,
    'Panama Canal': 62,
    'LatAm Ports': 48,
    'China / Taiwan Strait': 55,
    'Black Sea': 72,
  };
  container.innerHTML = Object.entries(zones).map(([name, info]) => {
    const score = zoneRiskScores[name] || 50;
    const tier = score >= 75 ? 'critical' : score >= 55 ? 'high' : 'medium';
    const color = score >= 75 ? 'var(--red)' : score >= 55 ? 'var(--orange)' : 'var(--yellow)';
    return `
    <div class="risk-zone-card ${tier}">
      <div class="rz-header">
        <span class="rz-name">${name}</span>
        <span class="rz-score" style="color:${color}">${score}</span>
      </div>
      <p class="rz-description">${info.description}</p>
      <div class="rz-lanes">
        ${(info.affected_lanes || []).map(l =>
          `<span class="rz-lane-tag">${l}</span>`
        ).join('')}
      </div>
    </div>`;
  }).join('');
}

// ── AI Brief ──────────────────────────────────────────────────────────────────
async function loadBrief() {
  const container = document.getElementById('briefContent');
  container.innerHTML = '<div class="loading-spinner"></div>';
  try {
    const resp = await fetch('/api/brief');
    const data = await resp.json();
    container.innerHTML = data.html || '<p class="muted">No brief available.</p>';
  } catch (err) {
    container.innerHTML = '<p class="muted">Could not load brief.</p>';
  }
}

// ── Refresh ───────────────────────────────────────────────────────────────────
async function refreshData() {
  const btn = document.getElementById('refreshBtn');
  btn.textContent = 'Refreshing...';
  btn.disabled = true;
  try {
    await fetch('/api/refresh', { method: 'POST' });
    // Wait for pipeline to run (5s initial delay)
    await new Promise(r => setTimeout(r, 7000));
    await loadDashboard();
    await loadBrief();
  } catch (err) {
    console.error('Refresh failed:', err);
  }
  btn.textContent = 'Refresh Data';
  btn.disabled = false;
}

// ── Q&A ───────────────────────────────────────────────────────────────────────
async function askQuestion() {
  const input = document.getElementById('qaInput');
  const question = input.value.trim();
  if (!question) return;

  const history = document.getElementById('qaHistory');
  const btn = document.getElementById('qaBtn');

  // Append user message
  history.innerHTML += `<div class="qa-message user"><strong>You:</strong> ${escHtml(question)}</div>`;
  input.value = '';
  btn.textContent = 'Thinking...';
  btn.disabled = true;

  try {
    const resp = await fetch('/api/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question }),
    });
    const data = await resp.json();
    history.innerHTML += `<div class="qa-message analyst"><strong>Analyst:</strong> ${escHtml(data.answer)}</div>`;
    history.scrollTop = history.scrollHeight;
  } catch (err) {
    history.innerHTML += `<div class="qa-message analyst muted">Error: ${err.message}</div>`;
  }

  btn.textContent = 'Ask';
  btn.disabled = false;
}

function askSuggestion(btn) {
  document.getElementById('qaInput').value = btn.textContent;
  askQuestion();
}

function escHtml(str) {
  return str
    .replace(/&/g,'&amp;')
    .replace(/</g,'&lt;')
    .replace(/>/g,'&gt;')
    .replace(/\n/g,'<br>');
}
