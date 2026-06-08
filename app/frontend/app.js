// GAMIT-Agent frontend: Leaflet station map + click-to-detail + Agent chat (POST-SSE streaming)
const $ = (id) => document.getElementById(id);
const STATUS = $("status");
let map, markerLayer, stnFeatures = {}, running = false, abortCtrl = null;

// palette: sage ok / brick danger / copper warm / grey muted
const COLOR = { ok: "#4F6B54", antenna_mismatch: "#8A3A2E", high_std: "#9E5A2B", unsolved: "#8A8679" };

function initMap() {
  map = L.map("map", { center: [36.5, 127.8], zoom: 7, zoomControl: true });
  L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
    { attribution: "© OpenStreetMap © CARTO", subdomains: "abcd", maxZoom: 19 }).addTo(map);
  markerLayer = L.layerGroup().addTo(map);
}

async function loadStations() {
  const dir = $("proj-dir").value.trim();
  const expt = $("proj-expt").value.trim();
  const audit = $("opt-audit").checked;
  setStatus("Loading…", "run");
  try {
    const pj = await (await fetch(`/api/project?dir=${encodeURIComponent(dir)}` +
      (expt ? `&expt=${expt}` : ""))).json();
    if (pj.error) { setStatus(pj.error, "err"); return; }
    if (pj.expt && !expt) $("proj-expt").value = pj.expt;
    renderDays(pj.days || []);
    const url = `/api/stations?dir=${encodeURIComponent(dir)}` +
      (pj.expt ? `&expt=${pj.expt}` : "") + (audit ? "&audit=true" : "");
    const gj = await (await fetch(url)).json();
    renderStations(gj);
    setStatus(`Loaded ${gj.features.length} stations`, "done");
  } catch (e) { setStatus("Load failed: " + e, "err"); }
}

function renderDays(days) {
  $("days").innerHTML = days.map(d =>
    `<span class="day" onclick="pickDay('${d}')" title="Click for this day's QC">${d}</span>`).join("") || "";
}

// click a day chip -> fill doy and run the QC verdict
window.pickDay = function (d) {
  $("tool-doy").value = parseInt(d, 10);
  runTool("qc");
};

function renderStations(gj) {
  markerLayer.clearLayers();
  stnFeatures = {};
  const pts = [];
  (gj.features || []).forEach(f => {
    const [lon, lat] = f.geometry.coordinates;
    const p = f.properties;
    stnFeatures[p.station] = f;
    const m = L.circleMarker([lat, lon], {
      radius: 7, color: "#FBF8F1", weight: 2,
      fillColor: COLOR[p.status] || COLOR.ok, fillOpacity: .95,
    }).addTo(markerLayer);
    m.bindTooltip(p.station, { permanent: false });
    m.on("click", () => showDetail(p.station));
    pts.push([lat, lon]);
  });
  $("stn-count").textContent = gj.features ? `(${gj.features.length})` : "";
  $("stn-list").innerHTML = (gj.features || []).map(f => {
    const p = f.properties;
    return `<div class="stn-row" onclick="showDetail('${p.station}')">
      <i class="dot ${p.status.replace('antenna_mismatch','bad').replace('high_std','warn')}"></i>
      ${p.station}</div>`;
  }).join("");
  if (pts.length) map.fitBounds(pts, { padding: [40, 40], maxZoom: 9 });
}

window.showDetail = function (stn) {
  const f = stnFeatures[stn]; if (!f) return;
  const p = f.properties, [lon, lat] = f.geometry.coordinates;
  let html = `<span class="close" onclick="document.getElementById('detail').classList.add('hidden')">&times;</span>
    <h4>${stn}</h4>
    <div class="kv"><span>Status</span><span>${p.status}</span></div>
    <div class="kv"><span>Latitude</span><span>${lat.toFixed(5)}</span></div>
    <div class="kv"><span>Longitude</span><span>${lon.toFixed(5)}</span></div>
    <div class="kv"><span>Ellipsoidal height</span><span>${p.height_m != null ? p.height_m + " m" : "—"}</span></div>
    <div class="kv"><span>Height std</span><span>${p.std_u_mm != null ? p.std_u_mm + " mm" : "—"}</span></div>`;
  (p.audit_findings || []).forEach(fd => {
    html += `<div class="finding"><b>${fd.type}</b><br>${fd.detail || ""}</div>`;
  });
  if (!(p.audit_findings || []).length) html += `<p class="ok-note">Metadata matches the RINEX header, no anomaly</p>`;
  const d = $("detail"); d.innerHTML = html; d.classList.remove("hidden");
};

// ---------- Agent chat (POST + SSE streaming) ----------
function addEvt(type, html) {
  const div = document.createElement("div");
  div.className = "evt " + type;
  div.innerHTML = html;
  $("log").appendChild(div);
  $("log").scrollTop = $("log").scrollHeight;
  return div;
}

async function runAgent() {
  if (running) return;
  const instruction = $("instruction").value.trim();
  if (!instruction) return;
  running = true; $("btn-run").disabled = true; $("btn-stop").disabled = false;
  setStatus("Running…", "run");
  addEvt("thought", `<span class="tag">you</span><div>${esc(instruction)}</div>`);
  abortCtrl = new AbortController();
  try {
    const resp = await fetch("/api/run", {
      method: "POST", headers: { "Content-Type": "application/json" },
      signal: abortCtrl.signal,
      body: JSON.stringify({ instruction, dir: $("proj-dir").value.trim() }),
    });
    const reader = resp.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      // SSE event-block separator: sse_starlette default \r\n\r\n; also tolerate \n\n
      const parts = buf.split(/\r\n\r\n|\n\n/);
      buf = parts.pop();
      for (const block of parts) handleSSE(block);
    }
  } catch (e) {
    if (e.name !== "AbortError") addEvt("error", `<span class="tag">error</span><div>${esc("" + e)}</div>`);
  } finally {
    running = false; $("btn-run").disabled = false; $("btn-stop").disabled = true;
  }
}

function handleSSE(block) {
  let event = "message", data = "";
  block.split(/\r?\n/).forEach(l => {
    if (l.startsWith("event:")) event = l.slice(6).trim();
    else if (l.startsWith("data:")) data += l.slice(5).trim();
  });
  if (!data) return;
  let obj = {}; try { obj = JSON.parse(data); } catch { return; }
  if (event === "thought") {
    const a = obj.action ? `<span class="act">${obj.action}</span>(${esc(JSON.stringify(obj.args || {}).slice(0, 80))})` : "";
    addEvt("thought", `<span class="tag">round ${obj.round} · thinking</span><div>${esc(obj.thought || "")}</div><div>${a}</div>`);
  } else if (event === "observation" && obj.action !== "_guard") {
    addEvt("observation", `<span class="tag">observation · ${obj.action}</span><pre>${esc(obj.observation || "")}</pre>`);
  } else if (event === "final") {
    const r = obj.report || {};
    addEvt("final", `<span class="tag">done · ${r.status || ""}</span><div>${esc(r.summary || JSON.stringify(r))}</div>`);
    setStatus("Done", "done");
    refreshOverlay();
  } else if (event === "error") {
    addEvt("error", `<span class="tag">error</span><div>${esc(obj.message || data)}</div>`);
    setStatus("Error", "err");
  }
}

// refresh the map overlay after a run (a new solution / audit may have changed things)
function refreshOverlay() { loadStations(); }

// ---------- Analysis tools (QC / dropped sites / network geometry) ----------
async function runTool(kind) {
  const dir = $("proj-dir").value.trim();
  const doy = parseInt($("tool-doy").value, 10);
  const out = $("tool-result");
  if (!dir) { out.innerHTML = '<span class="err">Set the project directory first</span>'; return; }
  if ((kind === "qc" || kind === "drops") && !doy) {
    out.innerHTML = '<span class="err">QC / dropped-sites need a doy (click a day chip above or type one)</span>'; return;
  }
  out.innerHTML = "Querying…";
  try {
    let url, r;
    if (kind === "qc") url = `/api/qc?dir=${encodeURIComponent(dir)}&doy=${doy}`;
    else if (kind === "drops") url = `/api/drops?dir=${encodeURIComponent(dir)}&doy=${doy}`;
    else url = `/api/geometry?dir=${encodeURIComponent(dir)}`;
    r = await (await fetch(url)).json();
    if (r.error) { out.innerHTML = '<span class="err">' + esc(r.error) + "</span>"; return; }
    out.innerHTML = (kind === "qc") ? fmtQC(r, doy)
      : (kind === "drops") ? fmtDrops(r) : fmtGeom(r);
  } catch (e) { out.innerHTML = '<span class="err">Failed: ' + esc("" + e) + "</span>"; }
}

const VCOLOR = { pass: "#4F6B54", warn: "#9E5A2B", fail: "#8A3A2E" };
function fmtQC(r, doy) {
  const m = r.metrics || {};
  let h = `<div class="tr-head">QC · doy ${doy} · <b style="color:${VCOLOR[r.verdict] || "#000"}">${r.verdict}</b></div>` +
    `<div class="kv"><span>postfit nrms</span><span>${m.postfit_nrms ?? "—"}</span></div>` +
    `<div class="kv"><span>WL / NL fixed</span><span>${m.wl_fixed_pct ?? "—"}% / ${m.nl_fixed_pct ?? "—"}%</span></div>` +
    `<div class="kv"><span>stations / dropped</span><span>${m.n_stations ?? "—"} / ${m.n_dropped ?? 0}</span></div>`;
  if ((r.warnings || []).length) h += `<div class="tr-sec">Warnings</div>` + r.warnings.map(w => `<div class="warn-li">⚠ ${esc(w)}</div>`).join("");
  if ((r.suggest || []).length) h += `<div class="tr-sec">Suggested</div>` + r.suggest.map(s => `<div class="sug-li">→ ${esc(s)}</div>`).join("");
  return h;
}
function fmtDrops(r) {
  if (!r.n_dropped) return `<div class="tr-head">Dropped sites</div><p class="ok-note">No station was silently dropped</p>`;
  let h = `<div class="tr-head">Dropped sites · ${r.n_dropped} dropped (${r.n_stations_kept} kept)</div>`;
  (r.dropped || []).forEach(d => {
    h += `<div class="finding"><b>${esc(d.site)}</b> <small>${esc(d.receiver || "")}</small>` +
      (d.reasons || []).map(x => `<br>· ${esc(x)}`).join("") + `</div>`;
  });
  return h;
}
function fmtGeom(r) {
  const b = r.baselines_km || {}, s = r.span_km || {};
  let h = `<div class="tr-head">Network geometry · ${r.n_stations} stations</div>` +
    `<div class="kv"><span>baseline min/mean/max</span><span>${b.min}/${b.mean}/${b.max} km</span></div>` +
    `<div class="kv"><span>span NS×EW</span><span>${s.ns}×${s.ew} km</span></div>` +
    `<div class="kv"><span>aspect ratio</span><span>${s.aspect}</span></div>`;
  (r.flags || []).forEach(f => h += `<div class="${/healthy/i.test(f) ? "sug-li" : "warn-li"}">${esc(f)}</div>`);
  return h;
}

// ---------- Local folder browser ----------
let brPath = "";
async function browse(path) {
  try {
    const r = await (await fetch(`/api/browse?path=${encodeURIComponent(path || "")}`)).json();
    if (r.error) { $("br-list").innerHTML = '<span class="err">' + esc(r.error) + "</span>"; return; }
    brPath = r.path;
    $("br-path").textContent = r.path + (r.rinex_count ? `  ·  ${r.rinex_count} RINEX here` : "");
    $("br-up").disabled = !r.parent;
    $("br-up").dataset.parent = r.parent || "";
    $("br-list").innerHTML = (r.dirs || []).map(d =>
      `<div class="br-row" onclick="browse('${d.path.replace(/'/g, "\\'")}')">
        <span>📁 ${esc(d.name)}</span>
        <span class="br-rc">${d.rinex_count ? d.rinex_count + " RINEX" : ""}</span></div>`).join("")
      || '<p class="hint">(no sub-directories)</p>';
  } catch (e) { $("br-list").innerHTML = '<span class="err">Browse failed: ' + esc("" + e) + "</span>"; }
}
window.browse = browse;

// ---------- New project (bare RINEX -> init_project) ----------
async function initProject() {
  const src = $("np-src").value.trim();
  const expt = $("np-expt").value.trim();
  const year = $("np-year").value.trim();
  const dir = $("np-dir").value.trim();
  const out = $("np-result");
  if (!src || !expt || !year) { out.innerHTML = '<span class="err">Path, experiment and year are required</span>'; return; }
  out.innerHTML = "Building project… (unpack / build tables / sh_setup / sh_rx2apr, may take tens of seconds)";
  $("btn-init").disabled = true;
  try {
    const r = await (await fetch("/api/init_project", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rinex_src: src, expt, year: Number(year), project_dir: dir || undefined }),
    })).json();
    if (r.error) { out.innerHTML = '<span class="err">' + esc(r.error) + '</span>'; return; }
    const ok = r.ready ? '<b style="color:#4F6B54">ready ✓</b>' : '<b style="color:#8A3A2E">not ready</b>';
    out.innerHTML = `${ok} ${(r.sites || []).length} stations · missing apr ${(r.missing_apr || []).length}` +
      (r.unresolved_apr && r.unresolved_apr.length ? ` · <span class="err">unresolved ${r.unresolved_apr.join(",")}</span>` : "") +
      '<br><small>' + (r.steps || []).map(esc).join("<br>") + "</small>" +
      (r.hint ? '<br><small class="hint">' + esc(r.hint) + "</small>" : "");
    if (r.ready && r.project) {                 // after building, fill "Project" and load stations
      $("proj-dir").value = r.project; $("proj-expt").value = r.expt || "";
      loadStations();
    }
  } catch (e) { out.innerHTML = '<span class="err">Build failed: ' + esc("" + e) + "</span>"; }
  finally { $("btn-init").disabled = false; }
}

// ---------- Backend logs ----------
let logsTimer = null;
async function loadLogs() {
  try {
    const r = await (await fetch("/api/logs?n=300")).json();
    $("logs-body").textContent = (r.lines || []).join("\n");
    $("logs-body").scrollTop = $("logs-body").scrollHeight;
  } catch (e) { $("logs-body").textContent = "Failed to load logs: " + e; }
}
function toggleLogsAuto() {
  if ($("logs-auto").checked) { loadLogs(); logsTimer = setInterval(loadLogs, 3000); }
  else if (logsTimer) { clearInterval(logsTimer); logsTimer = null; }
}

// ---------- Settings ----------
async function loadConfig() {
  const c = await (await fetch("/api/config")).json();
  $("model-pill").textContent = "model: " + (c.model || "?") + (c.has_key ? "" : " · no key");
  $("cfg-base").value = c.base_url || ""; $("cfg-model").value = c.model || "";
}
async function saveConfig() {
  await fetch("/api/config", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ api_key: $("cfg-key").value.trim() || undefined,
      base_url: $("cfg-base").value.trim(), model: $("cfg-model").value.trim() }),
  });
  $("settings").classList.add("hidden"); loadConfig();
}

// ---------- bindings ----------
window.addEventListener("DOMContentLoaded", () => {
  initMap(); loadConfig();
  $("btn-load").onclick = loadStations;
  $("btn-run").onclick = runAgent;
  $("btn-stop").onclick = () => { if (abortCtrl) abortCtrl.abort(); setStatus("Stopped", "idle"); };
  $("btn-settings").onclick = () => $("settings").classList.remove("hidden");
  $("cfg-close").onclick = () => $("settings").classList.add("hidden");
  $("cfg-save").onclick = saveConfig;
  $("btn-init").onclick = initProject;
  // analysis tools
  $("btn-qc").onclick = () => runTool("qc");
  $("btn-drops").onclick = () => runTool("drops");
  $("btn-geom").onclick = () => runTool("geom");
  // folder browser
  $("np-browse").onclick = () => {
    $("browser").classList.remove("hidden");
    browse($("np-src").value.trim() || "");
  };
  $("br-up").onclick = () => browse($("br-up").dataset.parent || "");
  $("br-close").onclick = () => $("browser").classList.add("hidden");
  $("br-use").onclick = () => {
    $("np-src").value = brPath;
    $("browser").classList.add("hidden");
  };
  // logs
  $("btn-logs").onclick = () => { $("logs").classList.remove("hidden"); loadLogs(); };
  $("logs-close").onclick = () => { $("logs").classList.add("hidden"); if (logsTimer) { clearInterval(logsTimer); logsTimer = null; } $("logs-auto").checked = false; };
  $("logs-refresh").onclick = loadLogs;
  $("logs-auto").onchange = toggleLogsAuto;
  // keyboard shortcut: Ctrl/Cmd+Enter in the instruction box -> run
  $("instruction").addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); runAgent(); }
  });
  loadStations();
});

function esc(s) { return (s + "").replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c])); }
function setStatus(t, cls) { STATUS.textContent = t; STATUS.className = "pill " + (cls || "idle"); }
