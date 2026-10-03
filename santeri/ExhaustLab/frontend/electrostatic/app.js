"use strict";

const API = "http://127.0.0.1:8003";
const $ = (id) => document.getElementById(id);
const state = { study: null, selected: "gap4", busy: false, error: null, parameters: null, request: 0, controller: null };
let debounceTimer;
const integer = new Intl.NumberFormat("en", { maximumFractionDigits: 0 });
const decimal = new Intl.NumberFormat("en", { maximumFractionDigits: 3 });
const money = new Intl.NumberFormat("en", { style: "currency", currency: "EUR", maximumFractionDigits: 2 });
const finite = (value) => typeof value === "number" && Number.isFinite(value);
const percent = (value) => finite(value) ? `${(value * 100).toFixed(1)}%` : "—";
const text = (tag, value, className) => { const element = document.createElement(tag); element.textContent = value; if (className) element.className = className; return element; };

function caseId(item) { return String(item.case ?? `gap${item.gap_mm}`); }
function selectedCase() { return state.study?.cases?.find((item) => caseId(item) === state.selected) ?? null; }
function validationHealth(value) {
  if (!value || typeof value !== "object") return "unknown";
  const strings = [];
  const flags = [];
  function visit(item, key) {
    if (item && typeof item === "object") Object.entries(item).forEach(([name, child]) => visit(child, name));
    else if (typeof item === "string" && ["status", "overall", "overall_status"].includes(key)) strings.push(item.toLowerCase());
    else if (typeof item === "boolean" && ["pass", "passed"].includes(key)) flags.push(item);
  }
  visit(value, "validation");
  if (strings.some((item) => /^(fail|failed|error|blocked)$/.test(item)) || flags.includes(false)) return "review";
  if (strings.some((item) => /^(pass|passed|success)$/.test(item)) || flags.includes(true)) return "pass";
  return "unknown";
}

function budgetStatus(item) {
  const value = item.within_budget;
  if (value === true) return "Within entered budgets";
  if (value === false) return "Exceeds entered budget";
  if (value && typeof value === "object") {
    const flags = Object.values(value).filter((entry) => typeof entry === "boolean");
    if (flags.includes(false)) return "Exceeds entered budget";
    if (flags.length && flags.every(Boolean)) return "Within entered budgets";
  }
  return "Budgets not fully entered";
}

function setConnection(label, kind) {
  const element = $("connection-status");
  element.className = `status-pill ${kind || ""}`;
  element.lastElementChild.textContent = label;
}

function setBusy(busy) {
  state.busy = busy;
  $("evaluate-button").disabled = busy;
  $("evaluate-button").firstElementChild.textContent = busy ? "Evaluating trajectories…" : "Evaluate scenario";
  $("layout-cards").setAttribute("aria-busy", String(busy));
  if (busy) {
    setConnection("Updating scenario", "");
    $("evaluation-label").textContent = state.study ? "Previous evaluation · update in progress" : "Reading recorded simulation fields";
    $("form-status").textContent = "Calculating from Allsolve fields…";
  }
}

function showError(error, initial) {
  state.error = error;
  $("error-banner").hidden = false;
  $("error-title").textContent = initial ? "Study connection unavailable" : "Scenario evaluation failed";
  $("error-message").textContent = `${error.message || String(error)}${initial ? " Start the local API at 127.0.0.1:8003 and retry." : " Previous results remain visible and do not reflect changed inputs."}`;
  setConnection("Connection needs attention", "error");
  $("evaluation-label").textContent = state.study ? "Previous evaluation · update failed" : "No simulation data loaded";
  $("form-status").textContent = "Evaluation failed. Adjust inputs or retry.";
  if (!state.study) {
    $("layout-cards").replaceChildren(text("div", "Comparison unavailable until the study API responds.", "empty-cards"));
    $("chart-empty").textContent = "No trajectory results loaded.";
  }
}

async function request(path, options = {}) {
  const response = await fetch(`${API}${path}`, options);
  if (!response.ok) {
    let detail = "";
    try { const body = await response.json(); detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body.error ?? ""); } catch (_) { /* The status still gives an actionable error. */ }
    throw new Error(`API ${response.status}${detail ? `: ${detail}` : ` ${response.statusText}`}`);
  }
  const data = await response.json();
  if (!data || !Array.isArray(data.cases)) throw new Error("The study API returned an invalid result: cases are missing.");
  return data;
}

function optionalNumber(id) {
  const element = $(id);
  if (!element.value.trim()) return null;
  const value = Number(element.value);
  if (!Number.isFinite(value) || value < 0) throw new Error("Costs and budgets must be nonnegative numbers.");
  return value;
}

function readParameters() {
  if (!$("study-form").reportValidity()) return null;
  return {
    charge_e: Number($("charge_e").value), diameter_um: Number($("diameter_um").value), voltage_v: Number($("voltage_v").value),
    costs: { gap4: optionalNumber("cost-gap4"), gap6: optionalNumber("cost-gap6"), gap8: optionalNumber("cost-gap8") },
    budget_eur: optionalNumber("budget_eur"), supply_power_w: optionalNumber("supply_power_w"), power_budget_w: optionalNumber("power_budget_w"),
  };
}

function scenarioLabel(parameters) {
  return parameters ? `${integer.format(parameters.charge_e)} e · ${parameters.diameter_um.toFixed(1)} µm · ${integer.format(parameters.voltage_v)} V` : "Recorded nominal scenario";
}

async function loadStudy() {
  const token = ++state.request;
  state.controller?.abort();
  state.controller = new AbortController();
  setBusy(true);
  try {
    const data = await request("/api/study", { signal: state.controller.signal });
    if (token !== state.request) return;
    state.study = data;
    state.error = null;
    $("error-banner").hidden = true;
    // The recorded study uses the displayed nominal particle inputs.
    state.parameters = { charge_e: 30, diameter_um: 1, voltage_v: 200 };
    applyReturnedParameters(data);
    render();
  } catch (error) {
    if (error.name !== "AbortError" && token === state.request) showError(error, true);
  } finally { if (token === state.request) { setBusy(false); if (!state.error && state.study) updateStatus(); } }
}

function applyReturnedParameters(data) {
  const values = data.parameters ?? data.inputs ?? data.conditions?.particle ?? data.conditions ?? {};
  const pairs = [["charge_e", "charge-range"], ["diameter_um", "diameter-range"], ["voltage_v", "voltage-range"]];
  pairs.forEach(([id, range]) => {
    if (finite(values[id])) {
      $(id).value = values[id];
      $(range).value = values[id];
      state.parameters[id] = values[id];
    }
    paintRange($(range));
  });
}

async function evaluate(event) {
  event?.preventDefault();
  clearTimeout(debounceTimer);
  let parameters;
  try { parameters = readParameters(); } catch (error) { showError(error, false); return; }
  if (!parameters) return;
  const token = ++state.request;
  state.controller?.abort();
  state.controller = new AbortController();
  setBusy(true);
  try {
    const data = await request("/api/evaluate", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(parameters), signal: state.controller.signal,
    });
    if (token !== state.request) return;
    state.study = data;
    state.parameters = parameters;
    state.error = null;
    $("error-banner").hidden = true;
    render();
  } catch (error) {
    if (error.name !== "AbortError" && token === state.request) showError(error, false);
  } finally { if (token === state.request) { setBusy(false); if (!state.error && state.study) updateStatus(); } }
}

function updateStatus() {
  const cases = state.study?.cases ?? [];
  const review = cases.some((item) => validationHealth(item.validation) === "review");
  setConnection(review ? "Fields loaded · validation review" : "Recorded study connected", review ? "warning" : "connected");
  $("evaluation-label").textContent = scenarioLabel(state.parameters);
  $("form-status").textContent = `Results: ${scenarioLabel(state.parameters)}`;
}

function render() {
  const cases = state.study.cases;
  if (!cases.some((item) => caseId(item) === state.selected)) state.selected = cases.length ? caseId(cases[0]) : "gap4";
  renderCards();
  renderRanking();
  renderAssumptions();
  renderSelected();
  updateStatus();
}

function renderCards() {
  const list = $("layout-cards");
  list.replaceChildren();
  const cases = [...(state.study?.cases ?? [])].sort((a, b) => a.gap_mm - b.gap_mm);
  if (!cases.length) { list.append(text("div", "No completed case results are available in this study.", "empty-cards")); return; }
  cases.forEach((item) => {
    const selected = caseId(item) === state.selected;
    const card = document.createElement("button");
    card.type = "button";
    card.className = `layout-card${selected ? " selected" : ""}`;
    card.setAttribute("aria-pressed", String(selected));
    card.setAttribute("aria-label", `${item.gap_mm} millimeter gap, modeled capture ${percent(item.capture_fraction)}. Select trajectory preview.`);
    const top = text("div", "", "card-top");
    const title = text("span", `${item.gap_mm} mm`, "card-label");
    title.append(text("small", "plate gap"));
    const health = validationHealth(item.validation);
    const badge = text("span", health === "pass" ? "BENCHMARK CHECKED" : health === "review" ? "VALIDATION REVIEW" : "CHECKS RECORDED", `validation-badge ${health}`);
    top.append(title, badge);
    const capture = text("div", "", "capture-row");
    const amount = text("div", "", "capture-value");
    amount.append(document.createTextNode(finite(item.capture_fraction) ? (item.capture_fraction * 100).toFixed(1) : "—"));
    if (finite(item.capture_fraction)) amount.append(text("small", "%"));
    const metric = text("div", ""); metric.append(amount, text("div", "modeled single-pass capture", "capture-label"));
    const icon = text("div", "", "plate-icon"); icon.setAttribute("aria-hidden", "true"); icon.append(text("span", "↓"));
    capture.append(metric, icon);
    const track = text("div", "", "capture-track");
    const fill = document.createElement("i"); fill.style.width = `${finite(item.capture_fraction) ? Math.min(100, Math.max(0, item.capture_fraction * 100)) : 0}%`; track.append(fill);
    const metrics = text("dl", "", "card-metrics");
    const pressure = text("div", ""); const pressureValue = text("dd", finite(item.pressure_drop_pa) ? decimal.format(item.pressure_drop_pa) : "—"); pressureValue.append(text("small", " Pa")); pressure.append(text("dt", "PRESSURE PENALTY"), pressureValue);
    const cost = text("div", ""); cost.append(text("dt", "ENTERED BUILD COST"), text("dd", finite(item.entered_cost_eur) ? money.format(item.entered_cost_eur) : "Not entered", finite(item.entered_cost_eur) ? "" : "missing-cost"));
    metrics.append(pressure, cost);
    const bottom = text("div", "", "card-bottom"); bottom.append(text("span", budgetStatus(item)), text("span", selected ? "Viewing ↗" : "View paths ↗"));
    card.append(top, capture, track, metrics, bottom);
    card.addEventListener("click", () => { state.selected = caseId(item); renderCards(); renderSelected(); });
    list.append(card);
  });
}

function renderRanking() {
  const cases = (state.study?.cases ?? []).filter((item) => finite(item.capture_fraction));
  if (!cases.length) { $("ranking-note").textContent = "Capture is unavailable until the recorded fields pass the required checks."; return; }
  const ranked = [...cases].sort((a, b) => b.capture_fraction - a.capture_fraction);
  const best = ranked[0];
  const cheapestPressure = [...cases].filter((item) => finite(item.pressure_drop_pa)).sort((a, b) => a.pressure_drop_pa - b.pressure_drop_pa)[0];
  const tie = ranked.length > 1 && Math.abs(best.capture_fraction - ranked[1].capture_fraction) < 0.0005;
  const captureText = tie ? "Leading capture values are effectively tied at the displayed precision." : `${best.gap_mm} mm leads modeled capture for this scenario.`;
  const pressureText = cheapestPressure ? ` ${cheapestPressure.gap_mm} mm has the smallest simulated pressure penalty.` : "";
  const eligible = cases.filter((item) => item.within_budget === true).sort((a, b) => b.capture_fraction - a.capture_fraction);
  $("ranking-note").textContent = `${captureText}${pressureText}${eligible.length ? ` ${eligible[0].gap_mm} mm leads capture among cases within entered budgets.` : " Enter costs and power to assess prototype feasibility."}`;
}

function renderAssumptions() {
  const list = $("assumptions-list");
  list.replaceChildren();
  const assumptions = state.study?.assumptions;
  if (Array.isArray(assumptions)) assumptions.forEach((item) => list.append(text("li", typeof item === "string" ? item : JSON.stringify(item))));
  else if (assumptions && typeof assumptions === "object") Object.entries(assumptions).forEach(([key, value]) => list.append(text("li", `${key.replaceAll("_", " ")}: ${typeof value === "string" ? value : JSON.stringify(value)}`)));
  else list.append(text("li", "No additional assumptions were returned by the study API. Review the recorded evidence before using the result."));
}

function renderSelected() {
  const item = selectedCase();
  if (!item) { $("chart-empty").hidden = false; $("chart-empty").textContent = "No completed trajectory data available."; drawCanvas(); return; }
  $("selected-gap").textContent = `${item.gap_mm} mm plate gap`;
  $("evidence-subtitle").textContent = `${item.gap_mm} mm layout · fields, validation and provenance`;
  const fates = $("fate-strip").querySelectorAll("strong");
  fates[0].textContent = percent(item.capture_fraction); fates[1].textContent = percent(item.outlet_fraction); fates[2].textContent = percent(item.unresolved_fraction);
  const paths = normalizePaths(item.paths ?? item.traces);
  $("path-count").textContent = paths.length ? `${paths.length} sampled paths` : "No trajectory data returned";
  $("chart-empty").hidden = paths.length > 0;
  if (!paths.length) $("chart-empty").textContent = "This case has no trajectory paths in the API response.";
  renderEvidence(item);
  drawCanvas();
}

function normalizePaths(raw) {
  const values = Array.isArray(raw) ? raw : raw && typeof raw === "object" ? Object.values(raw) : [];
  return values.filter((path) => path && typeof path === "object").map((path) => ({ points: Array.isArray(path) ? path : path.points ?? path.path ?? [], state: path.state ?? path.outcome ?? null })).filter((path) => Array.isArray(path.points) && path.points.length >= 2 && path.points.every((point) => Array.isArray(point) && point.length >= 4 && point.slice(0, 4).every(finite)));
}

function renderEvidence(item) {
  const summary = $("validation-summary");
  summary.replaceChildren();
  const health = validationHealth(item.validation);
  summary.append(text("p", health === "review" ? "Recorded validation includes a failed check. Review the evidence before using capture or pressure to make a design decision." : health === "pass" ? "The recorded channel and field benchmark checks pass. Numerical and physical model limits still apply." : "Check details are recorded below. Solver completion alone does not establish model accuracy."));
  if (finite(item.air_power_w)) summary.append(text("p", `Ideal air power: ${item.air_power_w.toExponential(3)} W (Q × Δp).`));
  if (finite(item.total_entered_power_w)) summary.append(text("p", `Total entered power metric: ${Math.abs(item.total_entered_power_w) > 0 && Math.abs(item.total_entered_power_w) < 0.001 ? item.total_entered_power_w.toExponential(3) : decimal.format(item.total_entered_power_w)} W.`));
  const links = $("provenance-links"); links.replaceChildren();
  const added = new Set();
  function findLinks(value, key = "") {
    if (!value) return;
    if (typeof value === "string" && /^https?:\/\//i.test(value)) {
      try {
        const url = new URL(value);
        if (!["http:", "https:"].includes(url.protocol) || added.has(url.href)) return;
        added.add(url.href);
        const link = text("a", /project/i.test(key) ? "Open Allsolve project ↗" : key.replaceAll("_", " ") || "Open source ↗");
        link.href = url.href; link.target = "_blank"; link.rel = "noopener noreferrer"; links.append(link);
      } catch (_) { /* Ignore invalid provenance URLs. */ }
    } else if (typeof value === "object") Object.entries(value).forEach(([name, child]) => findLinks(child, name));
  }
  findLinks(item.provenance); findLinks(item.validation?.source);
  $("raw-evidence").textContent = JSON.stringify({ case: item.case, provenance: item.provenance, validation: item.validation, conditions: state.study.conditions }, null, 2);
}

function drawCanvas() {
  const canvas = $("trajectory-canvas");
  const rect = canvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.round(rect.width * dpr); canvas.height = Math.round(rect.height * dpr);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const width = rect.width, height = rect.height;
  ctx.clearRect(0, 0, width, height);
  const item = selectedCase();
  if (!item) return;
  const paths = normalizePaths(item.paths ?? item.traces);
  if (!paths.length) return;
  const length = finite(state.study.conditions?.length_m) ? state.study.conditions.length_m : 0.06;
  const gap = item.gap_mm / 1000;
  const span = finite(state.study.conditions?.span_m) ? state.study.conditions.span_m : 0.02;
  const left = 45, right = width - 24, top = 43, bottom = height - 47;
  const px = (x) => left + x / length * (right - left);
  const py = (y) => bottom - y / gap * (bottom - top);
  ctx.lineWidth = 1; ctx.strokeStyle = "#e1e9e8";
  ctx.font = "9px 'Segoe UI', sans-serif"; ctx.fillStyle = "#92a4aa";
  ctx.textAlign = "center";
  for (let i = 0; i <= 4; i++) {
    const x = left + i / 4 * (right - left);
    ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, bottom); ctx.stroke();
    ctx.fillText(`${Math.round(i / 4 * length * 1000)}`, x, bottom + 18);
  }
  ctx.textAlign = "right";
  for (let i = 0; i <= 2; i++) {
    const y = py(gap * i / 2);
    ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(right, y); ctx.stroke();
    ctx.fillText(`${(item.gap_mm * i / 2).toFixed(0)}`, left - 10, y + 3);
  }
  ctx.textAlign = "left"; ctx.fillText("y (mm)", 12, 20);
  ctx.textAlign = "center"; ctx.fillText("Channel length x (mm)", (left + right) / 2, height - 11);
  ctx.textAlign = "right"; ctx.fillStyle = "#839da2";
  const voltage = state.parameters?.voltage_v;
  ctx.fillText(`Driven plate · ${finite(voltage) ? integer.format(voltage) : "—"} V`, right, top - 12);
  ctx.fillText("Collecting plate · 0 V", right, bottom + 34);
  ctx.strokeStyle = "#628d93"; ctx.lineWidth = 3;
  [top, bottom].forEach((y) => { ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(right, y); ctx.stroke(); });
  ctx.save();
  ctx.beginPath(); ctx.rect(left - 2, top - 2, right - left + 4, bottom - top + 4); ctx.clip();
  paths.forEach((path) => {
    const end = path.points[path.points.length - 1];
    let outcome = String(path.state || "").toLowerCase();
    if (!outcome) {
      if (end[1] >= length - 1e-7) outcome = "outlet";
      else if (end[2] <= 1e-7 || end[2] >= gap - 1e-7 || end[3] <= 1e-7 || end[3] >= span - 1e-7) outcome = "captured";
      else outcome = "unresolved";
    }
    const color = /captur/.test(outcome) ? "#d88a45" : /outlet|escape/.test(outcome) ? "#208f8d" : "#8392b0";
    ctx.strokeStyle = color; ctx.lineWidth = 1.2; ctx.globalAlpha = 0.68;
    ctx.beginPath();
    path.points.forEach((point, index) => { if (index === 0) ctx.moveTo(px(point[1]), py(point[2])); else ctx.lineTo(px(point[1]), py(point[2])); });
    ctx.stroke();
    ctx.globalAlpha = 0.9; ctx.fillStyle = color; ctx.beginPath(); ctx.arc(px(end[1]), py(end[2]), 2, 0, Math.PI * 2); ctx.fill();
  });
  ctx.restore();
  ctx.globalAlpha = 1;
}

function paintRange(range) {
  const value = (Number(range.value) - Number(range.min)) / (Number(range.max) - Number(range.min)) * 100;
  range.style.background = `linear-gradient(to right, #137e83 ${value}%, #ddebea ${value}%)`;
}

function markPending() {
  if (state.study && !state.busy) {
    $("evaluation-label").textContent = "Previous evaluation · inputs changed";
    $("form-status").textContent = "Inputs changed. Evaluate to refresh results.";
  }
}

[["charge_e", "charge-range"], ["diameter_um", "diameter-range"], ["voltage_v", "voltage-range"]].forEach(([numberId, rangeId]) => {
  const number = $(numberId), range = $(rangeId);
  paintRange(range);
  range.addEventListener("input", () => { number.value = range.value; paintRange(range); markPending(); });
  range.addEventListener("change", () => { clearTimeout(debounceTimer); debounceTimer = setTimeout(() => evaluate(), 200); });
  number.addEventListener("input", () => { if (number.validity.valid) { range.value = number.value; paintRange(range); } markPending(); });
});
["cost-gap4", "cost-gap6", "cost-gap8", "budget_eur", "supply_power_w", "power_budget_w"].forEach((id) => $(id).addEventListener("input", markPending));
$("study-form").addEventListener("submit", evaluate);
$("reset-button").addEventListener("click", () => {
  $("charge_e").value = $("charge-range").value = 30;
  $("diameter_um").value = $("diameter-range").value = 1;
  $("voltage_v").value = $("voltage-range").value = 200;
  ["charge-range", "diameter-range", "voltage-range"].forEach((id) => paintRange($(id)));
  evaluate();
});
$("retry-button").addEventListener("click", () => state.study ? evaluate() : loadStudy());
document.querySelectorAll(".rail-link").forEach((link) => link.addEventListener("click", () => { document.querySelectorAll(".rail-link").forEach((item) => item.classList.remove("active")); link.classList.add("active"); }));
new ResizeObserver(() => drawCanvas()).observe($("trajectory-canvas").parentElement);
loadStudy();
