/**
 * NYAYA dashboard: 4 tabs over the live LinuxONE API (CONTRACTS.md §7).
 * Every number on screen comes from an API response. When the API is unreachable, the same responses recorded
 * from the LinuxONE server (dashboard/fixtures/, see fixtures/README.md) are shown and labelled "recorded".
 * Nothing is computed or invented here (AGENTS.md rule 3).
 */

// Helper to escape untrusted strings before HTML insertion (XSS prevention)
function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// Global Application State (Default to relative same-origin if hosted by FastAPI)
let API_BASE_URL = safeGet('NYAYA_API_URL') || (window.location.protocol === 'file:' ? 'http://localhost:8000' : '');
let isLiveBackend = false;
let currentLanguage = 'ta';
let activeScenarioId = 1;
let replayTimer = null;
let replayStepIndex = 0;

let shapChart = null;
let paretoChart = null;

let systemInfo = null;        // GET /system
let policy = null;            // GET /policy (api/policy_defaults.json)
let scenarioList = [];        // GET /scenarios
let replayData = null;        // POST /replay
let paretoData = null;        // GET /pareto
let current = null;           // {tx, result, expected, source} shown in the X-Ray tab
let activeQueueItems = [];

function safeGet(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
function safeSet(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } }

// =========================================================================================
// FORMATTING (display only)
// =========================================================================================
const DASH = '—';
function isNum(x) { return typeof x === 'number' && Number.isFinite(x); }
function inr(x) { return isNum(x) ? '₹' + Math.round(x).toLocaleString('en-IN') : DASH; }
function pct(x, d = 1) { return isNum(x) ? (100 * x).toFixed(d) + '%' : DASH; }
function num(x, d = 3) { return isNum(x) ? x.toFixed(d) : DASH; }
function setText(id, text) { const el = document.getElementById(id); if (el) el.textContent = text; }
function srcLabel(src) { return src === 'live' ? 'live' : src === 'recorded' ? 'recorded on LinuxONE' : 'no data'; }

// =========================================================================================
// APPLICATION INITIALIZATION
// =========================================================================================
window.addEventListener('DOMContentLoaded', async () => {
  initAllCharts();
  setupEventListeners();
  await probeBackend();
  await loadPolicy();
  await loadScenarioList();
  loadScenario(1);
});

/**
 * Safe API fetcher. Returns the parsed JSON body, or null on any error (network, timeout, non-2xx).
 * Non-GET requests are never retried. `apiFetchRaw` also returns the HTTP status.
 */
async function apiFetchRaw(endpoint, options = {}) {
  const timeoutMs = options.timeout || 5000;
  const cleanEndpoint = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
  const v1Path = cleanEndpoint.startsWith('/api/v1') || cleanEndpoint === '/health' ? cleanEndpoint : `/api/v1${cleanEndpoint}`;
  const headers = { ...(options.headers || {}) };
  if (options.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
  const token = safeGet('NYAYA_ANALYST_TOKEN');
  if (token) headers['X-Analyst-Token'] = token;
  try {
    const res = await fetch(`${API_BASE_URL}${v1Path}`, {
      method: options.method || 'GET', body: options.body, headers, signal: AbortSignal.timeout(timeoutMs)
    });
    let body = null;
    try { body = await res.json(); } catch (e) { body = null; }
    return { status: res.status, ok: res.ok, body };
  } catch (err) {
    return { status: 0, ok: false, body: null };
  }
}

async function apiFetch(endpoint, options = {}) {
  const r = await apiFetchRaw(endpoint, options);
  return r.ok ? r.body : null;
}

// Recorded responses from the LinuxONE server (dashboard/fixtures/<name>.json)
async function fixture(name) {
  try {
    const res = await fetch(`fixtures/${name}.json`);
    return res.ok ? await res.json() : null;
  } catch (e) {
    return null;
  }
}

// Live when connected, else the recorded response. Returns {v, src}.
async function getData(name, liveFn) {
  if (isLiveBackend && liveFn) {
    const v = await liveFn();
    if (v) return { v, src: 'live' };
  }
  const f = await fixture(name);
  return f ? { v: f, src: 'recorded' } : { v: null, src: 'none' };
}

// Probe Live LinuxONE Backend (/api/v1/system)
async function probeBackend() {
  const pill = document.getElementById('connectionStatusPill');
  const btnEvaluate = document.getElementById('btnRunCustomEvaluate');

  const data = await apiFetch('/system');
  isLiveBackend = !!data;
  if (data) {
    if (pill) pill.className = "flex items-center space-x-1.5 px-3 py-1 rounded-full text-xs font-mono font-bold bg-emerald-950/80 text-emerald-300 border border-emerald-700/60 shadow-sm";
    setText('connectionStatusText', `LIVE: ${data.platform?.machine || '?'} · ${data.models?.model_version || '?'} (${data.models?.kind || '?'})`);
    if (btnEvaluate) {
      btnEvaluate.disabled = false;
      btnEvaluate.className = "w-full py-2 bg-blue-600 hover:bg-blue-500 text-white rounded text-xs font-mono font-bold tracking-wider uppercase shadow";
      btnEvaluate.textContent = "Run Real-Time LinuxONE Decision";
    }
    systemInfo = data;
  } else {
    if (pill) pill.className = "flex items-center space-x-1.5 px-3 py-1 rounded-full text-xs font-mono font-bold bg-amber-950/70 text-amber-300 border border-amber-700/60";
    setText('connectionStatusText', "OFFLINE: showing responses recorded on LinuxONE");
    if (btnEvaluate) {
      btnEvaluate.disabled = true;
      btnEvaluate.className = "w-full py-2 bg-slate-800 text-slate-500 rounded text-xs font-mono font-bold tracking-wider uppercase cursor-not-allowed";
      btnEvaluate.textContent = "Live API offline: pick a scenario above";
    }
    systemInfo = await fixture('system');
  }
  populateHardwareStrip(systemInfo, isLiveBackend ? 'live' : (systemInfo ? 'recorded' : 'none'));
}

// Header strip from GET /api/v1/system (api/service.py Nyaya.system)
function populateHardwareStrip(info, src) {
  const p = info?.platform || {};
  const m = info?.models || {};
  setText('hwArch', p.machine ? `${p.machine} · ${p.byteorder}-endian · kernel ${p.kernel}` : DASH);
  setText('hwTelum', p.cpu_features_nnpa === undefined ? DASH :
    `nnpa: ${p.cpu_features_nnpa} · Model B on ${m.mule_device || '?'}`);
  setText('hwCrypto', p.cpu_features_msa === undefined ? DASH :
    `CPACF (msa: ${p.cpu_features_msa}) · ${p.openssl || 'OpenSSL ?'}`);
  setText('hwSecurity', p.uid === undefined ? DASH :
    `${p.in_container ? 'container' : 'host'} uid ${p.uid} · SELinux in container: ${p.selinux}`);
  const lat = info?.latency_ms;
  setText('hwLatency', lat ? `p50 ${lat.p50} ms · p95 ${lat.p95} ms (n=${lat.n}, ${srcLabel(src)})` : DASH);
  setText('footerVersions', info ? `${m.model_version || '?'} · ${info.engine_version || '?'} · policy ${info.explainer?.policy_source || '?'} · notices ${info.explainer?.notices_source || '?'}` : DASH);
}

async function loadPolicy() {
  const d = await getData('policy', () => apiFetch('/policy'));
  policy = d.v;
  // Category options come from the policy's urgency table (api/policy_defaults.json)
  const sel = document.getElementById('inputCategory');
  if (sel && policy?.urgency_by_category) {
    sel.innerHTML = Object.keys(policy.urgency_by_category)
      .map(c => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join('');
  }
  resetPolicySliders(false);
}

// Tab Switching
function switchTab(tabId) {
  document.querySelectorAll('main > section').forEach(sec => sec.classList.add('hidden'));
  document.querySelectorAll('nav button').forEach(btn => btn.classList.remove('tab-active'));

  const activeSec = document.getElementById(tabId);
  if (activeSec) activeSec.classList.remove('hidden');

  const activeBtn = document.getElementById('btn-' + tabId);
  if (activeBtn) activeBtn.classList.add('tab-active');

  if (tabId === 'tab-xray' && shapChart) {
    shapChart.resize();
  }
  if (tabId === 'tab-policy') {
    if (paretoChart) paretoChart.resize();
    loadPareto();
    loadSimulate();
  }
  if (tabId === 'tab-analyst') {
    fetchAnalystQueue();
    fetchRedTeamEvaluation();
    loadThroughput();
  }
}

// Setup Event Listeners
function setupEventListeners() {
  const urlInput = document.getElementById('inputApiUrl');
  if (urlInput) urlInput.value = API_BASE_URL;

  const scrubber = document.getElementById('replayScrubber');
  if (scrubber) {
    scrubber.addEventListener('input', (e) => {
      jumpReplayToHour(parseInt(e.target.value, 10));
    });
  }

  // Delegated click event listener for analyst queue action buttons (XSS prevention)
  const queueContainer = document.getElementById('analystQueueContainer');
  if (queueContainer) {
    queueContainer.addEventListener('click', (e) => {
      const btn = e.target.closest('.queue-action-btn');
      if (btn) {
        const id = btn.getAttribute('data-explain-id');
        const action = btn.getAttribute('data-action');
        if (id && action) adjudicateQueue(id, action);
      }
    });
  }
}

// Save API Base URL
function saveApiUrl() {
  const input = document.getElementById('inputApiUrl');
  const url = input ? input.value.trim() : '';
  API_BASE_URL = url;
  safeSet('NYAYA_API_URL', url);
  probeBackend().then(loadPolicy);
  toggleConfigModal();
}

function toggleConfigModal() {
  const modal = document.getElementById('configModal');
  if (modal) modal.classList.toggle('hidden');
}

/* =========================================================================================
 * TAB 1: CYCLONE REPLAY (POST /api/v1/replay, api/replay.py)
 * ========================================================================================= */
async function ensureReplay() {
  if (replayData) return replayData;
  setText('replayHeadlineSource', 'running replay on LinuxONE…');
  const d = await getData('replay', () => apiFetch('/replay', { method: 'POST', body: '{}', timeout: 180000 }));
  replayData = d.v;
  if (!replayData) {
    setText('replayHeadlineSource', 'replay unavailable (API offline and no recorded response)');
    return null;
  }
  const hours = replayData.hours || [];
  const scrubber = document.getElementById('replayScrubber');
  if (scrubber) { scrubber.max = Math.max(0, hours.length - 1); scrubber.value = 0; }
  if (hours.length) {
    setText('replayAxisStart', `H${hours[0].hour}`);
    setText('replayAxisMid', `H${hours[Math.floor(hours.length / 2)].hour}`);
    setText('replayAxisEnd', `H${hours[hours.length - 1].hour}`);
  }
  const t = replayData.totals || {};
  const L = t.legacy || {}, N = t.nyaya || {};
  setText('replayScenarioName', `${replayData.scenario} · ${replayData.config?.rows ?? DASH} payments · ${hours.length} hours`);
  setText('headlineLegacy', `Legacy ${pct(L.victims_left_zero_pct / 100, 2)} (${L.victims_left_zero ?? DASH} of ${L.victim_payments ?? DASH})`);
  setText('headlineNyaya', `NYAYA ${pct(N.victims_left_zero_pct / 100, 2)} (${N.victims_left_zero ?? DASH})`);
  setText('replayHeadlineSource',
    `Full replay totals (${srcLabel(d.src)}, ${replayData.model_version}). Fraud leaked: legacy ${inr(L.fraud_leaked_inr)}, ` +
    `NYAYA ${inr(N.fraud_leaked_inr)}. Legacy = ${replayData.legacy?.definition || DASH}.`);
  return replayData;
}

async function toggleReplay() {
  if (replayTimer) {
    pauseReplay();
  } else {
    await startReplay();
  }
}

async function startReplay() {
  const data = await ensureReplay();
  if (!data) return;
  setText('replayBtnText', "Pause Replay");
  const btnIcon = document.getElementById('replayBtnIcon');
  if (btnIcon) btnIcon.innerHTML = `<path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zM7 8a1 1 0 012 0v4a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v4a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd"></path>`;
  if (replayStepIndex === 0) { clearFeeds(); updateReplayUI(0); }
  replayTimer = setInterval(stepReplay, 700);
}

function pauseReplay() {
  clearInterval(replayTimer);
  replayTimer = null;
  setText('replayBtnText', "Resume Replay");
  const btnIcon = document.getElementById('replayBtnIcon');
  if (btnIcon) btnIcon.innerHTML = `<path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM9.555 7.168A1 1 0 008 8v4a1 1 0 001.555.832l3-2a1 1 0 000-1.664l-3-2z" clip-rule="evenodd"></path>`;
}

async function stepReplay() {
  const data = await ensureReplay();
  if (!data) return;
  const n = (data.hours || []).length;
  if (replayStepIndex + 1 >= n) {
    pauseReplay();
    setText('replayBtnText', "Restart Replay");
    replayStepIndex = 0;
    return;
  }
  replayStepIndex++;
  updateReplayUI(replayStepIndex);
}

function jumpReplayToHour(index) {
  if (!replayData) return;
  replayStepIndex = Math.min(Math.max(0, index), (replayData.hours || []).length - 1);
  clearFeeds();
  updateReplayUI(replayStepIndex, true);
}

function resetReplay() {
  pauseReplay();
  replayStepIndex = 0;
  setText('replayBtnText', "Start Replay");
  const scrubber = document.getElementById('replayScrubber');
  if (scrubber) scrubber.value = 0;
  clearFeeds(true);
  if (replayData) updateReplayUI(0);
}

function clearFeeds(withHint = false) {
  const hint = `<div class="p-3 rounded bg-slate-950 border border-slate-800 text-slate-500 italic text-center text-xs font-mono">Press "Start Replay" to stream the replay hour by hour...</div>`;
  ['legacyFeedList', 'nyayaFeedList'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.innerHTML = withHint ? hint : '';
  });
}

// Counters are sums of the API's per-hour counters up to the shown hour
function cumulative(hours, idx, side) {
  const keys = ['payments', 'holds', 'reviews', 'victim_payments', 'victims_left_zero', 'victims_frozen_full',
    'emergency_cash_inr', 'fraud_leaked_inr', 'fraud_payments'];
  const out = Object.fromEntries(keys.map(k => [k, 0]));
  for (let i = 0; i <= idx && i < hours.length; i++) {
    keys.forEach(k => { out[k] += Number(hours[i][side]?.[k] || 0); });
  }
  return out;
}

function updateReplayUI(idx, rebuildFeed = false) {
  if (!replayData) return;
  const hours = replayData.hours || [];
  const h = hours[idx];
  if (!h) return;

  setText('replayHourText', `Hour ${h.hour}`);
  setText('replayPhaseText', h.severity > 0 ? `Declared disaster zone, severity ${h.severity}` : 'No declared zone (severity 0)');
  setText('replaySeverityBadge', `Severity Tier ${h.severity}`);
  const scrubber = document.getElementById('replayScrubber');
  if (scrubber) scrubber.value = idx;

  const L = cumulative(hours, idx, 'legacy');
  const N = cumulative(hours, idx, 'nyaya');
  setText('legacyFreezeCount', L.victims_frozen_full.toLocaleString('en-IN'));
  setText('legacyFreezePct', `${L.victims_left_zero} of ${L.victim_payments} victim payments at ₹0`);
  setText('legacyCashAvailable', inr(L.emergency_cash_inr));
  setText('legacyBleedAmount', inr(L.fraud_leaked_inr));

  setText('nyayaZeroVictims', L.victim_payments ? pct(N.victims_left_zero / Math.max(1, N.victim_payments), 2) : DASH);
  setText('nyayaZeroVictimsSub', `${N.victims_left_zero} of ${N.victim_payments} victim payments at ₹0`);
  setText('nyayaCashAvailable', inr(N.emergency_cash_inr));
  setText('nyayaStipendsDisbursed', `${N.reviews} REVIEWs (stipend now + escrow)`);
  setText('nyayaBlockedCount', `${N.holds} HOLDs`);
  setText('nyayaLeakSub', `fraud leaked ${inr(N.fraud_leaked_inr)}`);

  if (rebuildFeed) {
    for (let i = Math.max(0, idx - 11); i <= idx; i++) appendReplayRows(hours[i]);
  } else {
    appendReplayRows(h);
  }
}

function appendReplayRows(h) {
  const legacyFeed = document.getElementById('legacyFeedList');
  const nyayaFeed = document.getElementById('nyayaFeedList');
  if (!legacyFeed || !nyayaFeed || !h) return;
  const row = (c, tone) => `
      <div class="p-2.5 rounded bg-slate-950 border ${tone} flex justify-between items-center text-xs">
        <div>
          <span class="text-slate-200 font-mono font-bold">H${h.hour} · severity ${h.severity} · ${c.payments} payments</span>
          <div class="text-[10px] text-slate-400">victims at ₹0: ${c.victims_left_zero} of ${c.victim_payments} · fraud leaked ${inr(c.fraud_leaked_inr)}</div>
        </div>
        <span class="px-2 py-0.5 rounded bg-slate-900 text-slate-300 border border-slate-700 text-[10px] font-bold">${c.holds} HOLD · ${c.reviews} REVIEW</span>
      </div>`;
  legacyFeed.insertAdjacentHTML('afterbegin', row(h.legacy || {}, (h.legacy?.victims_left_zero || 0) > 0 ? 'border-rose-900/60' : 'border-slate-800'));
  nyayaFeed.insertAdjacentHTML('afterbegin', row(h.nyaya || {}, (h.nyaya?.victims_left_zero || 0) > 0 ? 'border-rose-900/60' : 'border-emerald-900/60'));
}

/* =========================================================================================
 * TAB 2: TRANSACTION X-RAY & NOTICE (POST /scenarios/{n}/run, POST /evaluate, GET /explain/{id})
 * ========================================================================================= */
async function loadScenarioList() {
  const d = await getData('scenarios', () => apiFetch('/scenarios'));
  scenarioList = d.v?.scenarios || [];
  scenarioList.forEach(s => {
    const btn = document.getElementById(`btnFixture${s.n}`);
    if (btn) { btn.textContent = `${s.n}. ${s.name}`; btn.title = s.name; }
  });
}

async function loadScenario(num) {
  activeScenarioId = num;
  for (let i = 1; i <= 6; i++) {
    const btn = document.getElementById(`btnFixture${i}`);
    if (btn) {
      btn.className = i === num
        ? "px-2.5 py-1.5 bg-blue-600 text-white font-bold rounded text-xs border border-blue-500 text-left truncate"
        : "px-2.5 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded text-xs border border-slate-700 text-left truncate";
    }
  }
  const sc = scenarioList.find(s => s.n === num);
  const d = await getData(`scenario_${num}`, () => apiFetch(`/scenarios/${num}/run`, { method: 'POST', timeout: 30000 }));
  if (!d.v || !d.v.result) {
    setText('xrayExpected', `Scenario ${num}: no result (API offline and nothing recorded)`);
    return;
  }
  current = { tx: sc?.tx || null, result: d.v.result, expected: d.v.expected_by_design, source: d.src };
  if (sc?.tx) populateEvaluatorInputs(sc.tx);
  setText('xrayExpected', `Designed outcome: ${d.v.expected_by_design} · ${srcLabel(d.src)} result: ${d.v.result.decision}` +
    (d.v.preloaded_events ? ` · ${d.v.preloaded_events} preloaded events` : ''));
  if (d.v.notice_lang) currentLanguage = d.v.notice_lang;
  renderXRayResults(current);
  setLanguage(currentLanguage);
  fetchGraniteExplanation(d.v.result);
}

function populateEvaluatorInputs(tx) {
  const set = (id, v) => { const el = document.getElementById(id); if (el && v !== undefined && v !== null) el.value = v; };
  set('inputAmount', tx.amount);
  set('inputCategory', tx.merchant_category);
  set('inputSeverity', tx.in_disaster_zone ? (tx.severity_tier ?? 0) : 0);
  set('inputHour', tx.hour);
  set('inputGeoShift', tx.geo_shift_km ?? 0);
}

// GET /api/v1/explain/{explain_id}: Granite card (or the template when Granite times out) + masked facts
async function fetchGraniteExplanation(result) {
  const graniteElem = document.getElementById('valGraniteOutput');
  const promptElem = document.getElementById('valMaskedPrompt');
  if (!isLiveBackend || !result?.explain_id) {
    if (graniteElem) graniteElem.textContent = result?.card_template
      ? `[template card, recorded; Granite runs only against the live API] ${result.card_template}` : DASH;
    if (promptElem) promptElem.textContent = 'Connect to the live API to see the masked facts sent to Granite.';
    return;
  }
  if (graniteElem) graniteElem.textContent = 'Asking Granite on LinuxONE…';
  const explainData = await apiFetch(`/explain/${encodeURIComponent(result.explain_id)}`, { timeout: 20000 });
  if (!explainData) {
    if (graniteElem) graniteElem.textContent = `[explain unavailable] ${result.card_template || ''}`;
    return;
  }
  const g = explainData.granite || {};
  if (graniteElem) graniteElem.textContent = `[${g.source || '?'}${g.reason ? ': ' + g.reason : ''}] ${g.card || explainData.card_template || DASH}`;
  if (promptElem) promptElem.textContent = JSON.stringify(explainData.masked_facts || {}, null, 1);
}

function renderXRayResults(cur) {
  const data = cur?.result;
  if (!data) return;
  const hours = policy?.escrow_hours ?? DASH;

  setText('xrayTxId', data.tx_id || DASH);
  setText('xrayLatency', isNum(data.latency_ms) ? `${data.latency_ms} ms (${srcLabel(cur.source)})` : DASH);
  setText('xrayModelVersion', `${data.model_version || DASH} · ${data.engine_version || DASH} · Model B on ${data.mule_device || DASH}`);

  const badge = document.getElementById('xrayDecisionBadge');
  if (badge) {
    const base = "p-3 rounded-lg text-center font-mono font-bold text-sm uppercase tracking-wider border shadow ";
    if (data.decision === 'RELEASE') {
      badge.className = base + "bg-emerald-950 text-emerald-300 border-emerald-600";
      badge.textContent = "RELEASE · paid in full";
    } else if (data.decision === 'REVIEW') {
      badge.className = base + "bg-amber-950 text-amber-300 border-amber-600";
      badge.textContent = `REVIEW · ${inr(data.release_now)} now + ${inr(data.escrow)} escrow (${hours}h)`;
    } else if (data.decision === 'HOLD') {
      badge.className = base + "bg-rose-950 text-rose-300 border-rose-600";
      badge.textContent = data.mule_flag ? "HOLD · mule override" : "HOLD";
    } else {
      badge.className = base + "bg-slate-900 text-slate-300 border-slate-700";
      badge.textContent = DASH;
    }
  }
  setText('xrayAmountDisbursed', inr(data.release_now));
  setText('xrayEscrowHeld', inr(data.escrow));

  setText('valPFraud', num(data.p_fraud));
  setText('valPMule', num(data.p_mule));
  const barPFraud = document.getElementById('barPFraud');
  const barPMule = document.getElementById('barPMule');
  if (barPFraud) barPFraud.style.width = isNum(data.p_fraud) ? `${Math.min(data.p_fraud * 100, 100)}%` : "0%";
  if (barPMule) barPMule.style.width = isNum(data.p_mule) ? `${Math.min(data.p_mule * 100, 100)}%` : "0%";

  const cs = Array.isArray(data.conformal_set) ? data.conformal_set : null;
  setText('valConformalSet', cs ? `{${cs.join(', ')}}${cs.length === 1 ? '' : ' uncertain'}` : DASH);

  const valHarmDelta = document.getElementById('valHarmDelta');
  if (valHarmDelta) {
    if (isNum(data.harm_delta)) {
      valHarmDelta.textContent = `${data.harm_delta > 0 ? '+' : '−'}${inr(Math.abs(data.harm_delta))}`;
      valHarmDelta.className = data.harm_delta <= 0 ? "font-bold text-emerald-400" : "font-bold text-rose-400";
    } else {
      valHarmDelta.textContent = DASH;
      valHarmDelta.className = "font-bold text-slate-400";
    }
  }

  const cf = data.counterfactual;
  setText('valCounterfactual', !cf ? 'None: the engine found no single-feature change that flips this decision.'
    : (cf.text || (cf.error ? `counterfactual error: ${cf.error}` : JSON.stringify(cf))));

  const c = data.policy_clause || {};
  setText('valPolicyId', c.id ? `${c.id} · ${c.title} (BM25 ${c.score}, ${c.source})` : DASH);
  setText('valPolicyText', c.text ? `"${c.text}"` : DASH);

  setText('valLedgerHash', data.ledger_hash || DASH);
  updateShapChart(data.reasons || []);
  updateNoticePhone(data);
}

function updateShapChart(reasons) {
  if (!shapChart) return;
  const safe = Array.isArray(reasons) ? reasons : [];
  shapChart.data.labels = safe.map(r => `${r.feature} = ${isNum(r.value) ? +r.value.toFixed(3) : r.value}`);
  shapChart.data.datasets[0].data = safe.map(r => r.contribution || 0);
  shapChart.data.datasets[0].backgroundColor = safe.map(r => (r.contribution || 0) < 0 ? '#10b981' : '#f43f5e');
  shapChart.update();
}

// Beneficiary notice: the API renders it from docs/notices.json (result.notice), never the browser
function updateNoticePhone(data) {
  const n = data?.notice || {};
  const text = n[currentLanguage];
  setText('phoneNoticeBody', text || (data ? `(no ${currentLanguage} text in the notices file; source: ${n.source || '?'})` : DASH));
  const headers = { ta: "வங்கி உடனடி அறிவிப்பு (Tamil)", hi: "बैंक आपातकालीन सूचना (Hindi)", en: "Emergency Banking Alert (English)" };
  setText('phoneNoticeHeader', `${headers[currentLanguage] || headers.en} · ${n.source || '?'}`);
  const appealButtons = { ta: "மேல்முறையீடு (Appeal) செய்க →", hi: "अपील (Appeal) करें →", en: "One-Tap Urgent Appeal →" };
  setText('phoneAppealBtn', appealButtons[currentLanguage] || appealButtons.en);
}

function setLanguage(lang) {
  currentLanguage = lang;
  ['ta', 'hi', 'en'].forEach(l => {
    const b = document.getElementById(`btnLang_${l}`);
    if (b) b.className = l === lang ? "px-3 py-1 rounded bg-blue-600 text-white font-bold text-xs" : "px-3 py-1 rounded text-slate-400 hover:text-white text-xs";
  });
  if (current?.result) updateNoticePhone(current.result);
}

function toggleMaskedPrompt() {
  const panel = document.getElementById('maskedPromptPanel');
  if (panel) panel.classList.toggle('hidden');
}

function evaluatorPayload() {
  const numOr = (val, def) => { const n = Number(val); return Number.isFinite(n) ? n : def; };
  const severity = numOr(document.getElementById('inputSeverity')?.value, 0);
  return {
    sender_id: "P_DASHBOARD",
    recipient_id: "M_DASHBOARD_" + Math.floor(Math.random() * 90000 + 10000),
    amount: numOr(document.getElementById('inputAmount')?.value, 0),
    merchant_category: document.getElementById('inputCategory')?.value || "p2p",
    in_disaster_zone: severity > 0 ? 1 : 0,   // the API ignores severity outside a declared zone
    severity_tier: severity,
    hour: numOr(document.getElementById('inputHour')?.value, 12),
    geo_shift_km: numOr(document.getElementById('inputGeoShift')?.value, 0)
  };
}

// POST /api/v1/evaluate with the form values (live only)
async function evaluateCustomForm() {
  if (!isLiveBackend) {
    alert("Live LinuxONE API unavailable. Pick one of the 6 scenarios to see recorded results, or connect the API.");
    return;
  }
  const payload = evaluatorPayload();
  const r = await apiFetchRaw('/evaluate', { method: 'POST', body: JSON.stringify(payload), timeout: 15000 });
  if (!r.ok) {
    alert(`Evaluation failed (HTTP ${r.status || 'network'}): ${JSON.stringify(r.body?.detail || '')}`);
    return;
  }
  current = { tx: payload, result: r.body, expected: null, source: 'live' };
  setText('xrayExpected', `Custom payment · live result: ${r.body.decision}`);
  renderXRayResults(current);
  fetchGraniteExplanation(r.body);
}

// POST /api/v1/appeal/{explain_id} (only REVIEW and HOLD decisions are in the queue)
async function fileAppeal() {
  if (!isLiveBackend) {
    alert("Cannot submit appeal: the LinuxONE API is unreachable.");
    return;
  }
  const id = current?.result?.explain_id;
  if (!id) return;
  const r = await apiFetchRaw(`/appeal/${encodeURIComponent(id)}`, {
    method: 'POST', body: JSON.stringify({ note: "Filed from the beneficiary notice (dashboard demo)." })
  });
  if (!r.ok) {
    alert(r.status === 404 ? "Only REVIEW and HOLD decisions can be appealed (this one was released)." : `Appeal failed (HTTP ${r.status || 'network'}).`);
    return;
  }
  alert(`Appeal recorded for ${id} (ledger ${String(r.body.ledger_hash || '').slice(0, 12)}…).`);
  switchTab('tab-analyst');
}

/* =========================================================================================
 * TAB 3: POLICY CONSOLE (GET /pareto, POST /simulate, POST /evaluate with policy overrides)
 * ========================================================================================= */
const SLIDERS = { alpha: 'sliderAlpha', beta: 'sliderBeta', tau: 'sliderTau', stipend_cap: 'sliderCap' };

function sliderValues() {
  const out = {};
  Object.entries(SLIDERS).forEach(([k, id]) => { const el = document.getElementById(id); if (el) out[k] = parseFloat(el.value); });
  return out;
}

function showSliderValues(v) {
  setText('valAlpha', isNum(v.alpha) ? v.alpha.toFixed(2) : DASH);
  setText('valBeta', inr(v.beta));
  setText('valTau', inr(v.tau));
  setText('valCap', inr(v.stipend_cap));
}

async function updatePolicySliders() {
  const v = sliderValues();
  showSliderValues(v);
  highlightParetoPoint(v);
}

function resetPolicySliders(rerun = true) {
  if (!policy) return;
  Object.entries(SLIDERS).forEach(([k, id]) => { const el = document.getElementById(id); if (el && isNum(policy[k])) el.value = policy[k]; });
  showSliderValues(sliderValues());
  if (rerun) highlightParetoPoint(sliderValues());
}

// Re-run the payment shown in the X-Ray tab with the slider values as policy overrides (live only)
async function whatIfEvaluate() {
  if (!isLiveBackend || !current?.tx) {
    setText('whatIfResult', isLiveBackend ? 'Load a scenario in the X-Ray tab first.' : 'Needs the live API.');
    return;
  }
  const v = sliderValues();
  const body = { ...current.tx, policy: v };
  delete body.ts;
  const res = await apiFetch('/evaluate', { method: 'POST', body: JSON.stringify(body), timeout: 15000 });
  setText('whatIfResult', res
    ? `${res.decision}: ${inr(res.release_now)} now, ${inr(res.escrow)} escrow, ΔH ${inr(res.harm_delta)} (default policy gave ${current.result.decision})`
    : 'Evaluation failed.');
}

async function loadPareto() {
  if (paretoData) return;
  const d = await getData('pareto', () => apiFetch('/pareto', { timeout: 30000 }));
  paretoData = d.v;
  if (!paretoData || !paretoChart) {
    setText('paretoMeta', 'no Pareto result (run sim.run pareto on the server)');
    return;
  }
  setText('paretoMeta', `${paretoData.suite_rows} payments · ${paretoData.suite_source} · ${srcLabel(d.src)}${paretoData._source ? ' · ' + paretoData._source : ''}`);
  const colors = { alpha: '#3b82f6', beta: '#10b981', tau: '#a855f7', tau_review: '#f59e0b', theta_mule: '#ec4899' };
  const byParam = {};
  (paretoData.points || []).forEach(p => {
    (byParam[p.parameter] = byParam[p.parameter] || []).push({
      x: p.metrics.fraud_leakage_rupees, y: p.metrics.total_expected_harm_rupees, value: p.value, loses: p.loses_to
    });
  });
  const datasets = Object.entries(byParam).map(([param, pts]) => ({
    label: `NYAYA, sweep ${param}`, data: pts, backgroundColor: colors[param] || '#94a3b8', pointRadius: 5
  }));
  const b = paretoData.baselines || {};
  if (b.legacy) datasets.push({ label: 'Legacy (1% FPR, no disaster context)', data: [{ x: b.legacy.fraud_leakage_rupees, y: b.legacy.total_expected_harm_rupees }], backgroundColor: '#f43f5e', pointRadius: 9 });
  if (b.naive_relaxed) datasets.push({ label: 'Naive relaxed (legacy + amount cap)', data: [{ x: b.naive_relaxed.fraud_leakage_rupees, y: b.naive_relaxed.total_expected_harm_rupees }], backgroundColor: '#f59e0b', pointRadius: 9, pointStyle: 'triangle' });
  datasets.push({ label: 'Nearest swept point to the sliders', data: [], backgroundColor: 'rgba(0,0,0,0)', borderColor: '#ffffff', borderWidth: 2, pointRadius: 12 });
  paretoChart.data.datasets = datasets;
  paretoChart.update();
  highlightParetoPoint(sliderValues());
}

// Marks the swept point closest to the slider that moved away from the base policy (no interpolation)
function highlightParetoPoint(v) {
  if (!paretoData || !paretoChart) return;
  const base = paretoData.base_policy || {};
  const moved = ['alpha', 'beta', 'tau'].filter(k => isNum(v[k]) && isNum(base[k]) && Math.abs(v[k] - base[k]) > 1e-9);
  const param = moved[0] || 'alpha';
  const pts = (paretoData.points || []).filter(p => p.parameter === param);
  if (!pts.length) return;
  const target = isNum(v[param]) ? v[param] : base[param];
  const best = pts.reduce((a, p) => Math.abs(p.value - target) < Math.abs(a.value - target) ? p : a, pts[0]);
  const ds = paretoChart.data.datasets[paretoChart.data.datasets.length - 1];
  ds.data = [{ x: best.metrics.fraud_leakage_rupees, y: best.metrics.total_expected_harm_rupees }];
  paretoChart.update();
  const capNote = isNum(v.stipend_cap) && isNum(base.stipend_cap) && v.stipend_cap !== base.stipend_cap ? ' (stipend cap is not swept; use "Re-run" to see its effect on one payment)' : '';
  setText('paretoPointText',
    `Nearest swept point: ${param} = ${best.value} → victims at ₹0 ${pct(best.metrics.victims_left_with_zero_rate, 2)}, ` +
    `fraud leakage ${inr(best.metrics.fraud_leakage_rupees)}, expected harm ${inr(best.metrics.total_expected_harm_rupees)}` +
    `${best.loses_to?.length ? ', loses to ' + best.loses_to.join(', ') : ''}${capNote}`);
}

async function loadSimulate() {
  const body = document.getElementById('simulateTableBody');
  if (!body || body.dataset.loaded) return;
  const d = await getData('simulate', () => apiFetch('/simulate', { method: 'POST', body: '{}', timeout: 30000 }));
  const s = d.v;
  if (!s?.metrics) { body.innerHTML = `<tr><td class="p-3" colspan="4">No /simulate result.</td></tr>`; return; }
  body.dataset.loaded = '1';
  setText('simulateMeta', `${s.suite?.rows ?? DASH} payments, ${s.suite?.source || DASH} · ${srcLabel(d.src)}`);
  const m = s.metrics;
  const cols = ['nyaya', 'legacy', 'naive_relaxed'].filter(k => m[k]);
  const rows = [
    ['Victims left with ₹0', k => pct(m[k].victims_left_with_zero_rate, 2) + ` (${m[k].victims_left_with_zero})`],
    ['Victims frozen (HOLD)', k => pct(m[k].victim_freeze_rate, 2)],
    ["Share of victims' money available now", k => pct(m[k].emergency_cash_availability)],
    ['Fraud leakage', k => inr(m[k].fraud_leakage_rupees)],
    ['Total expected harm (engine terms)', k => inr(m[k].total_expected_harm_rupees)],
  ];
  body.innerHTML = rows.map(([label, f]) => `<tr class="hover:bg-slate-850"><td class="p-2 font-bold text-white">${escapeHtml(label)}</td>${cols.map(k => `<td class="p-2">${escapeHtml(f(k))}</td>`).join('')}</tr>`).join('');
  setText('simulateModelLine', `Model A PR-AUC ${num(m.nyaya.pr_auc_model_a)} · Model B PR-AUC ${num(m.nyaya.pr_auc_model_b)} · conformal coverage ${pct(m.nyaya.conformal_coverage)}`);
  renderFairness(s.fairness, d.src);
}

function renderFairness(f, src) {
  const body = document.getElementById('fairnessTableBody');
  if (!body) return;
  if (!f) { body.innerHTML = `<tr><td class="p-3" colspan="5">No fairness audit in /simulate.</td></tr>`; return; }
  const views = [['Legitimate payments only', f.legitimate_only], ['All payments', f]].filter(v => v[1]);
  const labels = { low: 'Low income', mid: 'Middle income', high: 'High income' };
  body.innerHTML = views.map(([name, v]) =>
    Object.entries(v.by_sender_income_band || {}).map(([band, r]) => `
      <tr class="hover:bg-slate-850">
        <td class="p-3 text-slate-400">${escapeHtml(name)}</td>
        <td class="p-3 font-bold text-white">${escapeHtml(labels[band] || band)}</td>
        <td class="p-3">${escapeHtml(r.n.toLocaleString('en-IN'))}</td>
        <td class="p-3">${escapeHtml(pct(r.freeze_rate, 2))}</td>
        <td class="p-3">${escapeHtml(pct(r.review_rate, 2))}</td>
      </tr>`).join('') + `
      <tr class="bg-slate-950/60"><td class="p-3 text-slate-400" colspan="3">${escapeHtml(name)}: max/min ratio (target ≤ ${v.target_max_ratio}×)</td>
        <td class="p-3 font-bold ${v.max_min_freeze_ratio <= v.target_max_ratio ? 'text-emerald-400' : 'text-rose-400'}">${escapeHtml(num(v.max_min_freeze_ratio, 2))}×</td>
        <td class="p-3 font-bold ${v.max_min_review_ratio <= v.target_max_ratio ? 'text-emerald-400' : 'text-rose-400'}">${escapeHtml(num(v.max_min_review_ratio, 2))}×</td></tr>`).join('');
  const legit = f.legitimate_only || f;
  const badge = document.getElementById('fairnessBadge');
  if (badge) {
    badge.textContent = `Target ≤ ${legit.target_max_ratio}×: ${legit.target_met ? 'met' : 'not met'} (${srcLabel(src)})`;
    badge.className = `text-xs font-mono px-3 py-1 rounded border font-bold ${legit.target_met ? 'bg-emerald-950 text-emerald-300 border-emerald-700' : 'bg-rose-950 text-rose-300 border-rose-700'}`;
  }
}

/* =========================================================================================
 * TAB 4: ANALYST QUEUE, LEDGER, RED TEAM, NNPA BENCHMARK
 * ========================================================================================= */
async function fetchAnalystQueue() {
  const d = await getData('queue', () => apiFetch('/queue'));
  activeQueueItems = d.v?.items || [];
  renderAnalystQueueItems(d.src);
}

function renderAnalystQueueItems(src) {
  const container = document.getElementById('analystQueueContainer');
  const pending = activeQueueItems.filter(i => i.status === 'pending').length;
  setText('queueCountBadge', `${pending} pending · ${activeQueueItems.length} total (${srcLabel(src)})`);
  if (!container) return;

  if (activeQueueItems.length === 0) {
    container.innerHTML = `
      <div class="p-6 text-center text-slate-500 font-mono text-xs bg-slate-950 rounded-lg border border-slate-800">
        Queue empty. REVIEW and HOLD decisions appear here (run a scenario in the X-Ray tab).
      </div>`;
    return;
  }
  const nowS = Date.now() / 1000;
  container.innerHTML = activeQueueItems.map(item => {
    const id = escapeHtml(item.explain_id);
    const left = isNum(item.release_at) ? Math.max(0, (item.release_at - nowS) / 3600) : null;
    const live = isLiveBackend && src === 'live' && item.status === 'pending';
    return `
      <div class="bg-slate-950 p-4 rounded-lg border border-slate-800 space-y-2">
        <div class="flex justify-between items-start text-xs font-mono">
          <div>
            <span class="font-bold text-white">${id} · ${escapeHtml(item.decision)} · ${escapeHtml(item.merchant_category)} · severity ${escapeHtml(item.severity_tier)}</span>
            <div class="text-[11px] text-slate-400">Total: ${inr(item.amount)} · Paid now: ${inr(item.release_now)} · Escrowed: ${inr(item.escrow)}</div>
            <div class="text-[10px] text-indigo-400">P(fraud) ${num(item.p_fraud)} · P(mule) ${num(item.p_mule)}${item.mule_flag ? ' (mule flag)' : ''} · clause ${escapeHtml(item.policy_clause)} · ledger #${escapeHtml(item.ledger_seq)}</div>
          </div>
          <span class="px-2 py-0.5 rounded ${item.appealed ? 'bg-amber-950 text-amber-300 border border-amber-800' : 'bg-blue-950 text-blue-300 border border-blue-800'} text-[10px] font-bold">
            ${item.appealed ? 'APPEALED · ' : ''}${escapeHtml(String(item.status).toUpperCase())}
          </span>
        </div>
        <div class="pt-2 flex justify-between items-center text-xs font-mono">
          <span class="text-slate-400">${item.release_at ? `Auto-release in <strong class="text-emerald-400">${left === null ? DASH : left.toFixed(1) + 'h'}</strong> unless fraud is confirmed` : 'HOLD: no automatic release'}</span>
          <div class="flex gap-2">
            <button data-action="approve" data-explain-id="${id}" ${live ? '' : 'disabled'} class="queue-action-btn px-3 py-1 ${live ? 'bg-emerald-600 hover:bg-emerald-500' : 'bg-slate-800 text-slate-500'} text-white font-bold rounded">Release</button>
            <button data-action="deny" data-explain-id="${id}" ${live ? '' : 'disabled'} class="queue-action-btn px-3 py-1 ${live ? 'bg-rose-600 hover:bg-rose-500' : 'bg-slate-800 text-slate-500'} text-white font-bold rounded">Confirm Fraud</button>
          </div>
        </div>
      </div>`;
  }).join('');
}

// POST /api/v1/queue/{explain_id} {"action": "approve"|"deny", "analyst": str}
async function adjudicateQueue(explainId, action) {
  if (!isLiveBackend) return;
  const analystId = safeGet('NYAYA_ANALYST_ID') || 'analyst_demo';
  const send = () => apiFetchRaw(`/queue/${encodeURIComponent(explainId)}`, {
    method: 'POST', body: JSON.stringify({ action: action === 'approve' ? 'approve' : 'deny', analyst: analystId })
  });
  let r = await send();
  if (r.status === 401) {
    const t = prompt('Analyst token (NYAYA_ANALYST_TOKEN on the server):');
    if (!t) return;
    safeSet('NYAYA_ANALYST_TOKEN', t);
    r = await send();
  }
  if (!r.ok) {
    alert(`Action failed (HTTP ${r.status || 'network'}): ${JSON.stringify(r.body?.detail || '')}`);
    return;
  }
  await fetchAnalystQueue();
}

// Demo control: POST /api/v1/queue/advance-clock?hours=48 shows default-to-release
async function advanceEscrowClock() {
  if (!isLiveBackend) return;
  const r = await apiFetchRaw('/queue/advance-clock?hours=48', { method: 'POST' });
  if (!r.ok) { alert(`Advance clock failed (HTTP ${r.status || 'network'}).`); return; }
  alert(`Escrow clock moved +48h. Auto-released: ${(r.body.released || []).length}.`);
  fetchAnalystQueue();
}

async function fetchRedTeamEvaluation() {
  const tbody = document.getElementById('redteamTableBody');
  if (!tbody || tbody.dataset.loaded) return;
  const d = await getData('redteam', () => apiFetch('/redteam', { timeout: 30000 }));
  const r = d.v;
  if (!r?.variants) { tbody.innerHTML = `<tr><td class="p-3" colspan="7">No red-team result.</td></tr>`; return; }
  tbody.dataset.loaded = '1';
  const strategy = {
    base: 'Original syndicate (no adaptation)',
    smurf: 'Spreads transfers over 3× more mule accounts',
    device_spoof: 'Fresh device fingerprints and subnets per mule',
    slow_drip: 'Forwards money after 12–40 min instead of within 10'
  };
  const rows = [{ ...r.base, detection_change_vs_base: null }, ...r.variants];
  tbody.innerHTML = rows.map(v => `
        <tr class="hover:bg-slate-850">
          <td class="p-3 font-bold text-white">${escapeHtml(v.variant)}</td>
          <td class="p-3">${escapeHtml(strategy[v.variant] || '')}</td>
          <td class="p-3">${escapeHtml(v.rows.toLocaleString('en-IN'))}</td>
          <td class="p-3 font-bold ${v.nyaya_weakens ? 'text-amber-300' : 'text-emerald-400'}">${escapeHtml(pct(v.detection_rate))}${v.detection_change_vs_base === null ? '' : ` (${v.detection_change_vs_base >= 0 ? '+' : ''}${(100 * v.detection_change_vs_base).toFixed(1)} pt)`}</td>
          <td class="p-3">${escapeHtml(pct(v.hold_rate))} / ${escapeHtml(pct(v.review_rate))}</td>
          <td class="p-3 text-slate-400"><code>${escapeHtml(v.strongest_remaining_feature)}</code></td>
        </tr>`).join('');
  setText('redteamMeta', `Detection = HOLD or REVIEW · ${srcLabel(d.src)}${r._source ? ' · ' + r._source : ''}`);
}

// artifacts/bench/throughput.json (recorded; the API has no endpoint for it)
async function loadThroughput() {
  const tbody = document.getElementById('benchTableBody');
  if (!tbody || tbody.dataset.loaded) return;
  const b = await fixture('throughput');   // deploy/bench_throughput.py output: results[{device, batch, p50_ms, p95_ms, decisions_per_s}]
  const byBatch = {};
  (b?.results || []).forEach(r => { (byBatch[r.batch] = byBatch[r.batch] || {})[r.device] = r; });
  const batches = Object.keys(byBatch).map(Number).sort((x, y) => x - y);
  if (!batches.length) { tbody.innerHTML = `<tr><td class="p-3" colspan="5">No benchmark recorded.</td></tr>`; return; }
  tbody.dataset.loaded = '1';
  const cell = r => r ? `${num(r.p50_ms, 3)} / ${num(r.p95_ms, 3)} ms · ${Math.round(r.decisions_per_s).toLocaleString('en-IN')}/s` : 'not measured';
  tbody.innerHTML = batches.map(batch => {
    const c = byBatch[batch].cpu, n = byBatch[batch].nnpa;
    const faster = c && n ? (n.p50_ms < c.p50_ms ? 'NNPA' : 'CPU') : null;
    return `
        <tr class="hover:bg-slate-850">
          <td class="p-3 font-bold text-white">${escapeHtml(batch.toLocaleString('en-IN'))}</td>
          <td class="p-3">${escapeHtml(cell(c))}</td>
          <td class="p-3">${escapeHtml(cell(n))}</td>
          <td class="p-3 font-bold ${faster === 'NNPA' ? 'text-emerald-400' : 'text-amber-300'}">${faster ? `${faster} faster (CPU/NNPA p50 = ${num(c.p50_ms / n.p50_ms, 2)})` : DASH}</td>
        </tr>`;
  }).join('');
  setText('benchMeta', `${b.model || ''} · ${b.machine || ''} · torch ${b.torch || ''} · ${b.cpu_threads || '?'} CPU threads · ${b.note || ''}` +
    (isNum(b.max_abs_logit_diff_cpu_vs_nnpa) ? ` · max |logit| difference CPU vs NNPA ${b.max_abs_logit_diff_cpu_vs_nnpa.toExponential(2)}` : ''));
}

// GET /api/v1/ledger/verify → {ok, records, head, algorithm, verify_ms} or {ok:false, first_bad_seq, reason}
async function verifyLedgerIntegrity() {
  const badge = document.getElementById('ledgerIntegrityBadge');
  const alertBox = document.getElementById('tamperWarningBox');
  if (alertBox) alertBox.classList.add('hidden');
  if (!isLiveBackend) {
    if (badge) {
      badge.textContent = "COULD NOT VERIFY (offline)";
      badge.className = "px-2.5 py-1 rounded bg-amber-950 text-amber-300 border border-amber-700 text-xs font-mono font-bold";
    }
    return;
  }
  const v = await apiFetch('/ledger/verify', { timeout: 30000 });
  if (v && v.ok === true) {
    if (badge) {
      badge.textContent = "CHAIN VALID ✅";
      badge.className = "px-2.5 py-1 rounded bg-emerald-950 text-emerald-300 border border-emerald-700 text-xs font-mono font-bold";
    }
    setText('valVerifiedBlocks', `${v.records.toLocaleString('en-IN')} records`);
    setText('valLedgerAlgo', v.algorithm || DASH);
    setText('valLedgerVerifyMs', isNum(v.verify_ms) ? `${v.verify_ms} ms` : DASH);
    setText('valLedgerHead', v.head || DASH);
  } else {
    if (badge) {
      badge.textContent = v ? `BROKEN at #${v.first_bad_seq} ❌` : "VERIFY FAILED (no response)";
      badge.className = "px-2.5 py-1 rounded bg-rose-950 text-rose-300 border border-rose-700 text-xs font-mono font-bold";
    }
    if (v && alertBox) {
      alertBox.textContent = `❌ /ledger/verify: record #${v.first_bad_seq} (line ${v.line}): ${v.reason}`;
      alertBox.classList.remove('hidden');
    }
  }
}

// Explains what a tampered ledger looks like; it does not touch the server's ledger
function simulateLedgerTamper() {
  const alertBox = document.getElementById('tamperWarningBox');
  if (!alertBox) return;
  alertBox.textContent = "Illustration only (nothing is changed on the server): if any byte of a ledger record is edited, " +
    "GET /api/v1/ledger/verify returns ok:false with first_bad_seq and the reason \"record content does not match its hash\" " +
    "(tested in ledger/tests/test_chain.py).";
  alertBox.classList.remove('hidden');
}

/* =========================================================================================
 * CHART.JS INITIALIZATIONS (empty until data arrives)
 * ========================================================================================= */
function initAllCharts() {
  if (typeof Chart === 'undefined') return;
  const shapElem = document.getElementById('chartShap');
  if (shapElem) {
    shapChart = new Chart(shapElem.getContext('2d'), {
      type: 'bar',
      data: { labels: [], datasets: [{ label: 'TreeSHAP contribution (log-odds)', data: [], backgroundColor: [], borderRadius: 4 }] },
      options: {
        indexAxis: 'y', responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { grid: { color: '#1e293b' }, ticks: { color: '#94a3b8', font: { family: 'monospace' } } },
          y: { grid: { display: false }, ticks: { color: '#cbd5e1', font: { family: 'monospace' } } }
        }
      }
    });
  }

  const paretoElem = document.getElementById('chartPareto');
  if (paretoElem) {
    paretoChart = new Chart(paretoElem.getContext('2d'), {
      type: 'scatter',
      data: { datasets: [] },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { position: 'top', labels: { color: '#cbd5e1', font: { family: 'monospace', size: 10 } } },
          tooltip: {
            callbacks: {
              label: (ctx) => {
                const p = ctx.raw || {};
                return `${ctx.dataset.label}${p.value !== undefined ? ' = ' + p.value : ''}: leakage ${inr(p.x)}, harm ${inr(p.y)}`;
              }
            }
          }
        },
        scales: {
          x: { title: { display: true, text: 'Fraud leakage (₹)', color: '#94a3b8' }, grid: { color: '#1e293b' }, ticks: { color: '#cbd5e1', font: { family: 'monospace' } } },
          y: { title: { display: true, text: 'Total expected harm (₹, engine terms)', color: '#94a3b8' }, grid: { color: '#1e293b' }, ticks: { color: '#cbd5e1', font: { family: 'monospace' } } }
        }
      }
    });
  }
}
