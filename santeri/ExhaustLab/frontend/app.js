"use strict";

const API = `${window.location.protocol}//${window.location.hostname}:8003`;
const $ = (id) => document.getElementById(id);
const state = { config: null, defaults: null, result: null, selected: null, busy: false, stale: false, revision: 0, request: 0, controller: null };
const number = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 1 });
const money = new Intl.NumberFormat("en-GB", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
const integer = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 0 });
const finite = (value) => typeof value === "number" && Number.isFinite(value);
const fmt = (value, digits = 1) => finite(value) ? value.toFixed(digits) : "—";
const pct = (value) => finite(value) ? `${fmt(value * 100)}%` : "—";
const clone = (value) => JSON.parse(JSON.stringify(value));
const fieldLabels = {
  effective_permeability_m2: ["Effective filter permeability", "m²"], spec_capture_pct: ["Specified filter capture", "%"],
  bulk_density_kg_m3: ["Filter bulk density", "kg/m³"], heat_capacity_j_kgk: ["Filter heat capacity", "J/kg·K"],
  loaded_resistance_multiplier: ["Loaded resistance multiplier", "×"], minimum_filter_volume_l: ["Minimum filter volume", "L"],
  pressure_kpa: ["Exhaust absolute pressure", "kPa"], ambient_temp_c: ["Ambient temperature", "°C"],
  external_h_w_m2k: ["External heat transfer", "W/m²·K"], insulation_k_w_mk: ["Insulation conductivity", "W/m·K"],
  hot_threshold_c: ["Filter hot threshold", "°C"], initial_temp_c: ["Initial filter temperature", "°C"],
  gas_heat_capacity_j_kgk: ["Gas heat capacity", "J/kg·K"], gas_to_filter_effectiveness: ["Gas-to-filter effectiveness", "0–1"],
  fixed_eur: ["Fixed installation cost", "€"], filter_eur_per_litre: ["Filter cost per litre", "€/L"],
  insulation_eur_per_litre: ["Insulation cost per litre", "€/L"], housing_eur_per_m2: ["Housing cost per area", "€/m²"],
  pipe_eur_per_m: ["Pipe cost per length", "€/m"], pipe_diameter_mm: ["Pipe bore diameter", "mm"],
  max_filter_temp_c: ["Maximum filter temperature", "°C"], pipe_roughness_mm: ["Pipe surface roughness", "mm"], housing_loss_coefficient: ["Housing loss coefficient", "K"],
  diameters_mm: ["Filter diameters", "mm"], lengths_mm: ["Filter lengths", "mm"],
  pipe_lengths_mm: ["Upstream pipe lengths", "mm"], insulation_mm: ["Insulation thicknesses", "mm"],
};
const constraintLabels = {
  max_backpressure_kpa: "Backpressure", max_outer_diameter_mm: "Outer diameter", max_total_length_mm: "Installation length",
  target_capture_pct: "Specified capture", budget_eur: "Installation budget", min_hot_time_fraction: "Required hot time",
  minimum_filter_volume_l: "Minimum filter volume", max_mach: "Flow model envelope", model_envelope: "Model envelope",
  cloud_geometry_not_verified: "Geometry needs a new cloud simulation", max_filter_temp_c: "Maximum filter temperature",
  backpressure: "Backpressure", outer_diameter: "Outer diameter", total_length: "Installation length", capture_specification: "Specified filter capture",
  budget: "Installation budget", hot_time_screen: "Required hot time", peak_filter_temperature: "Maximum filter temperature", minimum_filter_volume: "Minimum filter volume",
  low_compressibility_envelope: "Low-compressibility model envelope", pipe_mach_envelope: "Pipe flow model envelope",
};

function element(tag, content = "", className = "") {
  const item = document.createElement(tag); item.textContent = content; if (className) item.className = className; return item;
}
function svgElement(tag, attrs = {}, content = "") {
  const item = document.createElementNS("http://www.w3.org/2000/svg", tag);
  Object.entries(attrs).forEach(([key, value]) => item.setAttribute(key, String(value))); if (content) item.textContent = content; return item;
}
function setConnection(label, style = "") {
  $("connection-status").className = `status-pill ${style}`; $("connection-status").lastElementChild.textContent = label;
}
function setBusy(busy) {
  state.busy = busy; $("solve-button").disabled = busy || !state.defaults;
  $("solve-button").firstElementChild.textContent = busy ? "Searching candidate designs…" : "Find a feasible design";
  $("design").setAttribute("aria-busy", String(busy));
  if (busy) { setConnection("Evaluating designs", "pending"); $("form-status").textContent = "Checking the operating cycle against your constraints…"; }
}
function markPending() {
  state.revision += 1; updateCycleSummary();
  const threshold = $("advanced-thermal-hot_threshold_c");
  if (threshold && Number.isFinite(Number(threshold.value))) $("hot-threshold-note").textContent = `Hot time means filter temperature above ${fmt(Number(threshold.value),0)} °C. It supports thermal planning; it does not establish soot regeneration.`;
  if (!state.result) return;
  state.stale = true; $("result-badge").className = "result-badge stale"; $("result-badge").textContent = "INPUTS CHANGED";
  $("form-status").textContent = "Inputs changed. Run the search to refresh the design.";
  if (!state.busy) setConnection("Previous result · inputs changed", "pending");
}
function showError(error, initial = false) {
  $("error-banner").hidden = false; $("error-title").textContent = initial ? "Planner connection unavailable" : "Design search failed";
  $("error-message").textContent = `${error.message || String(error)}${state.result ? " The displayed design is the previous result." : " No design result is available."}`;
  setConnection("Needs attention", "error"); $("form-status").textContent = "Resolve the input or connection issue and retry.";
  if (state.result) { state.stale = true; $("result-badge").className = "result-badge stale"; $("result-badge").textContent = "PREVIOUS RESULT"; }
}
async function request(path, options = {}) {
  const response = await fetch(`${API}${path}`, options);
  let body; try { body = await response.json(); } catch (_) { throw new Error(`Planner API ${response.status}: response was not valid JSON.`); }
  if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : typeof body.error === "string" ? body.error : `Planner API ${response.status}`);
  return body;
}
function appendDutyRow(point, index) {
  const row = document.createElement("tr");
  const fields = [["name", "text", point.name, null, null], ["duration_s", "number", point.duration_s, 0.001, "any"], ["mass_flow_kg_s", "number", point.mass_flow_kg_s, 0.000001, "any"], ["inlet_temp_c", "number", point.inlet_temp_c, -100, "any"]];
  fields.forEach(([key, type, value, min, step]) => {
    const cell = document.createElement("td"), input = document.createElement("input"); input.type = type; input.value = value ?? ""; input.dataset.dutyKey = key; input.required = true;
    input.setAttribute("aria-label", `${fieldLabels[key]?.[0] ?? ({name:"Operating point name",duration_s:"Duration in seconds",mass_flow_kg_s:"Mass flow in kilograms per second",inlet_temp_c:"Inlet temperature in Celsius"})[key]}, row ${index + 1}`);
    if (min !== null) input.min = min; if (step) input.step = step; if (key === "name") input.maxLength = 60;
    cell.append(input); row.append(cell);
  });
  const remove = element("button", "×", "remove-point"); remove.type = "button"; remove.setAttribute("aria-label", `Remove operating point ${index + 1}`);
  remove.addEventListener("click", () => { if ($("duty-body").children.length <= 1) return; row.remove(); markPending(); });
  const cell = document.createElement("td"); cell.append(remove); row.append(cell); $("duty-body").append(row);
}
function makeAdvancedField(group, key, value, array = false) {
  const [label, unit] = fieldLabels[key] ?? [key.replaceAll("_", " "), ""];
  const wrapper = element("label", "", `field${array ? " search-field" : ""}`); wrapper.append(element("span", label));
  const input = document.createElement("input"); input.id = `advanced-${group}-${key}`; input.dataset.group = group; input.dataset.key = key; input.required = true;
  input.setAttribute("aria-label", label); input.value = array ? value.join(", ") : value; input.type = array ? "text" : "number";
  if (array) { input.dataset.array = "true"; wrapper.append(input); }
  else { input.step = "any"; const holder = element("div", "", "unit-input"); holder.append(input, element("span", unit)); wrapper.append(holder); }
  return wrapper;
}
function fillDefaults(payload) {
  state.defaults = clone(payload); $("duty-body").replaceChildren(); payload.duty_cycle.forEach(appendDutyRow);
  document.querySelectorAll("[data-group=constraints]").forEach((input) => { const value = payload.constraints[input.id]; input.value = finite(value) ? value * Number(input.dataset.displayScale || 1) : ""; });
  $("advanced-fields").replaceChildren(); $("search-fields").replaceChildren();
  ["material", "environment", "thermal", "cost"].forEach((group) => Object.entries(payload[group] ?? {}).forEach(([key, value]) => { if (finite(value)) $("advanced-fields").append(makeAdvancedField(group, key, value)); }));
  Object.entries(payload.constraints).forEach(([key,value]) => { if (!$(key) && finite(value)) $("advanced-fields").append(makeAdvancedField("constraints",key,value)); });
  Object.entries(payload.search ?? {}).forEach(([key, value]) => {
    if (Array.isArray(value)) $("search-fields").append(makeAdvancedField("search", key, value, true));
    else if (finite(value)) $("advanced-fields").append(makeAdvancedField("search", key, value));
  });
  $("objective").value = payload.search?.objective ?? "lowest_cost";
  if (!$("objective").value) $("objective").value = "lowest_cost";
  $("hot-threshold-note").textContent = `Hot time means filter temperature above ${fmt(payload.thermal.hot_threshold_c,0)} °C. It supports thermal planning; it does not establish soot regeneration.`;
  updateCycleSummary(); $("solve-button").disabled = false;
}
function updateCycleSummary() {
  const rows = [...$("duty-body").querySelectorAll("tr")]; const points = rows.map((row) => Object.fromEntries([...row.querySelectorAll("input")].map((input) => [input.dataset.dutyKey, Number(input.value)])));
  const durations = points.map((point) => point.duration_s).filter(finite), flows = points.map((point) => point.mass_flow_kg_s).filter(finite);
  $("cycle-duration").textContent = durations.length ? `${integer.format(durations.reduce((a,b) => a+b, 0))} s total duration` : "— total duration";
  $("cycle-flow").textContent = flows.length ? `${fmt(Math.min(...flows), 3)}–${fmt(Math.max(...flows), 3)} kg/s` : "— mass flow range";
}
function readInputs() {
  if (!state.defaults) throw new Error("The planner configuration has not loaded.");
  if (!$("planner-form").reportValidity()) return null;
  const payload = clone(state.defaults);
  payload.duty_cycle = [...$("duty-body").querySelectorAll("tr")].map((row) => Object.fromEntries([...row.querySelectorAll("input")].map((input) => [input.dataset.dutyKey, input.type === "number" ? Number(input.value) : input.value.trim()])));
  document.querySelectorAll("[data-group]").forEach((input) => {
    const group = input.dataset.group, key = input.dataset.key || input.id; payload[group] ??= {};
    if (input.dataset.array) {
      const pieces = input.value.split(",").map((part) => part.trim());
      if (!pieces.length || pieces.some((part) => !part || !Number.isFinite(Number(part)))) throw new Error(`${fieldLabels[key]?.[0] ?? key} must be comma-separated numbers.`);
      payload[group][key] = [...new Set(pieces.map(Number))];
    } else { const value = Number(input.value); if (!Number.isFinite(value)) throw new Error(`${fieldLabels[key]?.[0] ?? key} must be a finite number.`); payload[group][key] = value / Number(input.dataset.displayScale || 1); }
  });
  payload.search.objective = $("objective").value; return payload;
}
async function loadConfig() {
  setBusy(true);
  try {
    const config = await request("/api/planner/config"); const defaults = config.defaults ?? config;
    if (!Array.isArray(defaults.duty_cycle) || !defaults.constraints || !defaults.search) throw new Error("Planner configuration is missing required operating conditions.");
    state.config = config; fillDefaults(defaults); $("error-banner").hidden = true; renderEvidence(config); setConnection("Planning model connected", "connected");
    setBusy(false); await solve();
  } catch (error) { showError(error, true); setBusy(false); }
}
async function solve(event) {
  event?.preventDefault(); if (state.busy) return;
  let payload; try { payload = readInputs(); } catch (error) { showError(error); return; }
  if (!payload) { $("form-status").textContent = "Check the highlighted input, then run the design search."; return; }
  const requestId = ++state.request, revision = state.revision; state.controller?.abort(); state.controller = new AbortController(); setBusy(true);
  try {
    const result = await request("/api/planner/solve", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload), signal:state.controller.signal});
    if (requestId !== state.request) return;
    if (!Array.isArray(result.candidates) || !result.summary || !["feasible", "infeasible"].includes(result.status)) throw new Error("Planner returned an incomplete design search.");
    if (result.status === "feasible" && !result.recommended) throw new Error("Planner reported feasibility without a recommended design.");
    state.result = result; state.result.inputs ??= payload; state.selected = result.recommended?.id ?? null; state.stale = revision !== state.revision; $("error-banner").hidden = true; render();
  } catch (error) { if (error.name !== "AbortError" && requestId === state.request) showError(error); }
  finally { if (requestId === state.request) { setBusy(false); if ($("error-banner").hidden && state.result) updateStatus(); } }
}
function selectedCandidate() {
  const all = [...(state.result?.candidates ?? []), ...(state.result?.pareto ?? [])]; if (state.result?.recommended) all.push(state.result.recommended);
  return all.find((candidate) => candidate.id === state.selected) ?? state.result?.recommended ?? null;
}
function updateStatus() {
  const result = state.result; if (!result) return;
  const connectedLabel = result.mode === "allsolve_verified_screening" ? "Allsolve-backed screening" : "Analytical planning model";
  setConnection(state.stale ? "Previous result · inputs changed" : connectedLabel, state.stale ? "pending" : "connected");
  $("form-status").textContent = state.stale ? "Inputs changed. Run the search to refresh the design." : `${integer.format(result.summary.evaluated)} candidates checked · ${integer.format(result.summary.feasible)} feasible`;
  if (state.stale) { $("result-badge").className = "result-badge stale"; $("result-badge").textContent = "INPUTS CHANGED"; }
}
function render() {
  renderSelected(); renderTradeoffs(); renderInfeasible(); renderEvidence(state.result); updateStatus();
}
function metric(label, amount, unit, detail) {
  const box = element("div", "", "result-metric"); const value = element("strong", amount); if (unit) value.append(element("small", unit)); box.append(element("span", label), value, element("p", detail)); return box;
}
function renderSelected() {
  const candidate = selectedCandidate(), result = state.result;
  const needsCloud = !candidate && (result.summary.missing_cloud_geometries?.length ?? 0) > 0;
  $("result-badge").className = `result-badge ${candidate?.feasible ? "feasible" : "infeasible"}`;
  $("result-badge").textContent = candidate ? "MEETS CONSTRAINTS" : "NO FEASIBLE DESIGN";
  const isRecommended = candidate && candidate.id === result.recommended?.id;
  $("recommendation-title").textContent = candidate ? isRecommended ? "A design that fits your system" : "Explore this alternative" : needsCloud ? "These dimensions need verification" : "Your limits need another look";
  const priorities = {lowest_cost:"lowest entered installation cost", smallest_volume:"smallest installation volume", lowest_backpressure:"lowest loaded backpressure"};
  $("recommendation-copy").textContent = candidate ? `${isRecommended ? "Best candidate for " + (priorities[result.summary.objective] ?? result.summary.objective) : "Selected feasible alternative"} within the tested dimension grid.` : needsCloud ? "Requested filter dimensions include geometry outside the verified cloud study. Those designs need new Allsolve simulations before the planner can recommend them." : `${integer.format(result.summary.evaluated)} candidate installations were checked. Review the constraints below to see what prevents a feasible design.`;
  for (const id of ["result-metrics","design-diagram","dimension-strip","constraint-status"]) $(id).toggleAttribute("hidden", !candidate);
  $("diagram-empty").hidden = Boolean(candidate); $("operating-panel").hidden = !candidate;
  if (!candidate) { $("diagram-empty").querySelector("strong").textContent = "No feasible installation selected"; $("diagram-empty").querySelector("span").textContent = needsCloud ? "Verify requested filter geometry in Allsolve" : "Adjust a constraint or expand the candidate dimensions"; $("result-note").textContent = "No passing design is being recommended for the current inputs."; return; }
  $("result-metrics").replaceChildren(metric("WORST LOADED BACKPRESSURE", fmt(candidate.worst_loaded_backpressure_kpa,2), "kPa", `Limit ${fmt(result.inputs.constraints.max_backpressure_kpa)} kPa`), metric("TIME ABOVE THRESHOLD", fmt(candidate.hot_time_fraction*100), "%", `Above ${fmt(result.inputs.thermal.hot_threshold_c,0)} °C`), metric("ENTERED INSTALLATION COST", money.format(candidate.cost_eur), "", `Budget ${money.format(result.inputs.constraints.budget_eur)}`));
  const dimensions = [["FILTER CORE", `Ø ${fmt(candidate.diameter_mm,0)} × ${fmt(candidate.filter_length_mm,0)} mm`], ["UPSTREAM PIPE", `${fmt(candidate.pipe_length_mm,0)} mm`], ["INSULATION", `${fmt(candidate.insulation_mm,0)} mm`], ["TOTAL ENVELOPE", `Ø ${fmt(candidate.outer_diameter_mm,0)} × ${fmt(candidate.total_length_mm,0)} mm`]];
  $("dimension-strip").replaceChildren(...dimensions.map(([label,value]) => { const item=element("div"); item.append(element("span",label),element("strong",value)); return item; }));
  drawDesign(candidate); renderConstraints(candidate); renderOperatingPoints(candidate);
  $("result-note").textContent = `${fmt(candidate.specified_capture_pct)}% capture is the entered filter specification. ${fmt(candidate.filter_volume_l,2)} L filter volume; ${fmt(candidate.ideal_pumping_energy_wh,2)} Wh ideal pumping work over the cycle. Hot time is a thermal screening metric.`;
}
function renderConstraints(candidate) {
  const c = state.result.inputs.constraints, target = state.result.inputs.thermal.hot_threshold_c;
  const checks = [
    ["Backpressure", candidate.worst_loaded_backpressure_kpa <= c.max_backpressure_kpa, `${fmt(candidate.worst_loaded_backpressure_kpa,2)} / ${fmt(c.max_backpressure_kpa)} kPa`],
    ["Installation budget", candidate.cost_eur <= c.budget_eur, `${money.format(candidate.cost_eur)} / ${money.format(c.budget_eur)}`],
    ["Outer diameter", candidate.outer_diameter_mm <= c.max_outer_diameter_mm, `${fmt(candidate.outer_diameter_mm,0)} / ${fmt(c.max_outer_diameter_mm,0)} mm`],
    ["Installation length", candidate.total_length_mm <= c.max_total_length_mm, `${fmt(candidate.total_length_mm,0)} / ${fmt(c.max_total_length_mm,0)} mm`],
    ["Specified filter capture", candidate.specified_capture_pct >= c.target_capture_pct, `${fmt(candidate.specified_capture_pct)}% / ${fmt(c.target_capture_pct)}% required`],
    ["Time above threshold", candidate.hot_time_fraction >= c.min_hot_time_fraction, `${pct(candidate.hot_time_fraction)} / ${pct(c.min_hot_time_fraction)} required · ${fmt(target,0)} °C`],
    ["Peak filter temperature", candidate.peak_filter_temp_c <= c.max_filter_temp_c, `${fmt(candidate.peak_filter_temp_c,0)} / ${fmt(c.max_filter_temp_c,0)} °C`],
    ["Minimum filter volume", candidate.filter_volume_l >= state.result.inputs.material.minimum_filter_volume_l, `${fmt(candidate.filter_volume_l,2)} / ${fmt(state.result.inputs.material.minimum_filter_volume_l,2)} L minimum`],
  ];
  $("constraint-status").replaceChildren(...checks.map(([label,passes,detail]) => { const item=element("div","",`constraint-item${passes?"":" fail"}`); const content=element("span",label); content.append(element("small",detail)); item.append(element("i",passes?"✓":"!"),content); return item; }));
}
function drawDesign(candidate) {
  const svg = $("design-diagram"); svg.replaceChildren();
  const left=42,right=630,cy=108,filterLeft=255,filterRight=520,pipeTop=90,pipeBottom=126,coreTop=66,coreBottom=150;
  const insulation=Math.max(0,Math.min(14,candidate.insulation_mm*.65));
  svg.append(svgElement("text",{x:22,y:23,fill:"#91a8b0","font-size":9},"SELECTED INSTALLATION · SCHEMATIC, NOT TO SCALE"));
  if (insulation) svg.append(svgElement("rect",{x:filterLeft-5,y:coreTop-insulation-3,width:filterRight-filterLeft+10,height:coreBottom-coreTop+insulation*2+6,rx:6,fill:"#f0dbc0",stroke:"#d1ac7b","stroke-width":1}));
  const outline = `M${left} ${pipeTop}H${filterLeft-30}L${filterLeft} ${coreTop}H${filterRight}L${filterRight+30} ${pipeTop}H${right}V${pipeBottom}H${filterRight+30}L${filterRight} ${coreBottom}H${filterLeft}L${filterLeft-30} ${pipeBottom}H${left}Z`;
  svg.append(svgElement("path",{d:outline,fill:"#dce8e9",stroke:"#73969e","stroke-width":1.5}));
  svg.append(svgElement("rect",{x:filterLeft+4,y:coreTop+3,width:filterRight-filterLeft-8,height:coreBottom-coreTop-6,fill:"#b4cdcc",stroke:"#719c9c"}));
  for(let x=filterLeft+12;x<filterRight-3;x+=12) svg.append(svgElement("path",{d:`M${x} ${coreTop+4}V${coreBottom-4}`,stroke:"#e7f0ed","stroke-width":3}));
  [82,142,577].forEach((x) => svg.append(svgElement("path",{d:`M${x} ${cy}h25m-7-5 7 5-7 5`,fill:"none",stroke:"#378c85","stroke-width":1.8})));
  svg.append(svgElement("text",{x:120,y:75,fill:"#6c929b","font-size":10,"text-anchor":"middle"},`Ø ${fmt(state.result.inputs.search.pipe_diameter_mm,0)} mm pipe`));
  svg.append(svgElement("text",{x:386,y:48,fill:"#aa8152","font-size":10,"text-anchor":"middle"},`${fmt(candidate.insulation_mm,0)} mm insulation`));
  svg.append(svgElement("text",{x:386,y:113,fill:"#4b787e","font-size":12,"text-anchor":"middle"},"POROUS FILTER"));
  svg.append(svgElement("path",{d:`M${filterLeft} 159V179M${filterRight} 159V179M${filterLeft} 172H${filterRight}`,stroke:"#9fb4bb",fill:"none"}));
  svg.append(svgElement("text",{x:386,y:188,fill:"#809ca6","font-size":10,"text-anchor":"middle"},`${fmt(candidate.filter_length_mm,0)} mm filter core`));
  svg.append(svgElement("path",{d:`M${left} 134V157M${filterLeft-30} 137V157M${left} 150H${filterLeft-30}`,stroke:"#b2c2c7",fill:"none"}));
  svg.append(svgElement("text",{x:130,y:169,fill:"#8ba4ad","font-size":9,"text-anchor":"middle"},`${fmt(candidate.pipe_length_mm,0)} mm upstream run`));
  svg.append(svgElement("text",{x:641,y:99,fill:"#7f9da7","font-size":9,"text-anchor":"end"},"EXHAUST"),svgElement("text",{x:641,y:113,fill:"#7f9da7","font-size":9,"text-anchor":"end"},"OUTLET"));
}
function renderOperatingPoints(candidate) {
  $("operating-body").replaceChildren(...(candidate.duty_results??[]).map((point) => { const row=document.createElement("tr"); [point.name,`${fmt(point.filter_inlet_temp_c,0)} °C`,`${fmt(point.end_filter_temp_c,0)} °C`,`${fmt(point.loaded_backpressure_kpa,2)} kPa`,`${fmt(point.superficial_velocity_m_s,2)} m/s`].forEach((value) => row.append(element("td",value))); return row; }));
}
function renderTradeoffs() {
  const result = state.result, feasible=(result.candidates??[]).filter((candidate)=>candidate.feasible), pareto=result.pareto??[];
  $("search-count").textContent = `${integer.format(result.summary.feasible)} feasible / ${integer.format(result.summary.evaluated)} checked`;
  const ids=new Set(pareto.map((candidate)=>candidate.id)); const all=new Map(); feasible.forEach((candidate)=>all.set(candidate.id,candidate)); pareto.forEach((candidate)=>all.set(candidate.id,candidate));
  if(result.recommended) all.set(result.recommended.id,result.recommended);
  const candidates=[...all.values()]; $("pareto-empty").hidden=Boolean(candidates.length); $("pareto-chart").toggleAttribute("hidden", !candidates.length); $("chart-legend").hidden=!candidates.length; $("candidate-table-wrap").hidden=!candidates.length;
  if(!candidates.length) { $("pareto-empty").textContent="No feasible candidate points for the current constraints."; return; }
  const sorted=[...candidates].sort((a,b)=>a.cost_eur-b.cost_eur); const selected=selectedCandidate(); const display=[];
  if(result.recommended) display.push(result.recommended);
  for(const candidate of sorted.filter((item)=>ids.has(item.id))) if(!display.some((item)=>item.id===candidate.id)&&display.length<7) display.push(candidate);
  for(const candidate of sorted) if(!display.some((item)=>item.id===candidate.id)&&display.length<7) display.push(candidate);
  if(selected&&!display.some((item)=>item.id===selected.id)) display.push(selected);
  $("candidate-body").replaceChildren(...display.map((candidate,index)=>{
    const row=document.createElement("tr"); if(candidate.id===state.selected) row.className="selected";
    const title=element("td",candidate.id===result.recommended?.id?"Recommended":`Alternative ${index}`); title.append(element("span",candidate.id===result.recommended?.id?"Best for your priority":ids.has(candidate.id)?"Pareto tradeoff":"Feasible candidate","row-tag"));
    const size=element("td",`${fmt(candidate.diameter_mm,0)} × ${fmt(candidate.filter_length_mm,0)} mm`);size.append(element("span",`${fmt(candidate.insulation_mm,0)} mm insulation · ${fmt(candidate.pipe_length_mm,0)} mm pipe`,"row-tag"));
    row.append(title,size,element("td",`${fmt(candidate.worst_loaded_backpressure_kpa,2)} kPa`),element("td",pct(candidate.hot_time_fraction)),element("td",money.format(candidate.cost_eur)));
    const cell=element("td"),button=element("button",candidate.id===state.selected?"Viewing":"View ↗","view-design");button.type="button";button.setAttribute("aria-label",`View design ${candidate.id}`);button.addEventListener("click",()=>{state.selected=candidate.id;render();});cell.append(button);row.append(cell);return row;
  }));
  drawPareto(candidates,ids);
}
function drawPareto(candidates, paretoIds) {
  const svg=$("pareto-chart");svg.replaceChildren(); const left=56,right=652,top=18,bottom=189;
  const cost=candidates.map((item)=>item.cost_eur).filter(finite),pressure=candidates.map((item)=>item.worst_loaded_backpressure_kpa).filter(finite);
  if(!cost.length||!pressure.length)return;
  const minX=Math.max(0,Math.min(...cost)*.92),maxX=Math.max(...cost)*1.06+1,minY=Math.max(0,Math.min(...pressure)*.8),maxY=Math.max(...pressure)*1.12+.05;
  const px=(x)=>left+(x-minX)/(maxX-minX)*(right-left),py=(y)=>bottom-(y-minY)/(maxY-minY)*(bottom-top);
  for(let i=0;i<=4;i++){
    const x=left+i/4*(right-left),y=bottom-i/4*(bottom-top);
    svg.append(svgElement("path",{d:`M${x} ${top}V${bottom}M${left} ${y}H${right}`,stroke:"#e8eff0","stroke-width":1}));
    svg.append(svgElement("text",{x,y:bottom+16,"text-anchor":"middle",fill:"#96aab2","font-size":9},integer.format(minX+i/4*(maxX-minX))),svgElement("text",{x:left-10,y:y+3,"text-anchor":"end",fill:"#96aab2","font-size":9},fmt(minY+i/4*(maxY-minY),1)));
  }
  svg.append(svgElement("text",{x:350,y:225,"text-anchor":"middle",fill:"#8da4ad","font-size":9},"Entered installation cost (€)"),svgElement("text",{x:12,y:12,fill:"#8da4ad","font-size":9},"Loaded backpressure (kPa)"));
  const ordered=[...candidates].sort((a,b)=>Number(a.id===state.selected)-Number(b.id===state.selected));
  ordered.forEach((candidate)=>{
    if(!finite(candidate.cost_eur)||!finite(candidate.worst_loaded_backpressure_kpa))return;
    const selected=candidate.id===state.selected,pareto=paretoIds.has(candidate.id);
    const dot=svgElement("circle",{cx:px(candidate.cost_eur),cy:py(candidate.worst_loaded_backpressure_kpa),r:selected?6:pareto?4:2.7,fill:selected?"#cd9652":pareto?"#399c96":"#bad2d6",stroke:selected?"#fff":"none","stroke-width":2,tabindex:0,role:"button","aria-label":`View ${candidate.id}: ${money.format(candidate.cost_eur)}, ${fmt(candidate.worst_loaded_backpressure_kpa,2)} kilopascals`});
    dot.append(svgElement("title",{},`${candidate.id} · ${money.format(candidate.cost_eur)} · ${fmt(candidate.worst_loaded_backpressure_kpa,2)} kPa`));
    const select=()=>{state.selected=candidate.id;render();};dot.addEventListener("click",select);dot.addEventListener("keydown",(event)=>{if(event.key==="Enter"||event.key===" "){event.preventDefault();select();}});svg.append(dot);
  });
}
function renderInfeasible() {
  const result=state.result;$("infeasible-panel").hidden=result.status!=="infeasible";
  if(result.status!=="infeasible")return;
  const missing=(result.summary.missing_cloud_geometries?.length??0)>0;
  $("infeasible-title").textContent=missing ? "Some dimensions need a new simulation" : "No design meets every limit";
  $("infeasible-copy").textContent=missing ? "Geometry verification is a model-coverage requirement. It does not mean the requested design is physically impossible. The remaining counts show constraints that also excluded candidates." : "These counts show how often each requirement excluded a candidate. A candidate can fail more than one requirement; the counts are not additive.";
  $("infeasible-reasons").replaceChildren(...(result.constraint_failures??[]).map((failure)=>{
    const item=element("div","","infeasible-reason"),label=element("span",constraintLabels[failure.constraint]??failure.constraint.replaceAll("_"," "));
    const example=(result.near_feasible??[]).flatMap((candidate)=>candidate.violations??[]).find((violation)=>violation.constraint===failure.constraint);
    if(example&&finite(example.actual)&&finite(example.limit)){
      const fractions=failure.constraint==="hot_time_screen"||failure.constraint==="low_compressibility_envelope";
      const unit=({backpressure:"kPa",outer_diameter:"mm",total_length:"mm",capture_specification:"%",budget:"€",peak_filter_temperature:"°C",minimum_filter_volume:"L",pipe_mach_envelope:"Mach"})[failure.constraint]??"";
      const detail=fractions?`${pct(example.actual)} vs ${pct(example.limit)} limit`:`${number.format(example.actual)} vs ${number.format(example.limit)} ${unit} limit`;
      label.append(element("span",`Example candidate: ${detail}`,"row-tag"));
    }
    item.append(label,element("strong",`${integer.format(failure.count)} candidates`));return item;
  }));
}
function renderEvidence(data) {
  const assumptions=data.assumptions??state.config?.assumptions??[];$("assumptions-list").replaceChildren(...(Array.isArray(assumptions)?assumptions:[]).map((item)=>element("li",typeof item==="string"?item:JSON.stringify(item))));
  if(!assumptions.length)$("assumptions-list").append(element("li","Review the recorded model inputs before using this preliminary sizing result."));
  const provenance=data.provenance??state.config?.provenance??{},cloud=data.cloud_study??data.parallel_study??provenance.cloud_study??provenance.allsolve??state.config?.cloud_study??{};
  $("evidence-summary").textContent=data.mode==="allsolve_verified_screening"?"Verified Allsolve baseline + local duty-cycle and design screening":"Local screening model · inspect available simulation evidence";
  const completed=cloud.completed??cloud.completed_cases??cloud.case_count??provenance.cloud_case_count??(Array.isArray(cloud.cases)?cloud.cases.length:null),concurrency=cloud.observed_concurrency??cloud.max_concurrency??cloud.concurrency?.observed_peak_running_simulations??cloud.concurrency?.peak_active_jobs??cloud.concurrency?.peak_active??provenance.observed_concurrency;
  $("parallel-summary").textContent=data.mode==="allsolve_verified_screening"?`The planner uses a verified equivalent porous-filter baseline from Allsolve. The transient duty-cycle and candidate ranking are local model calculations.${finite(completed)?` ${integer.format(completed)} cloud geometries recorded.`:""}${finite(concurrency)?` Peak overlapping cloud jobs: ${integer.format(concurrency)}; each solve used one rank. This demonstrates independent job overlap, without a measured solver speedup.`:""}`:"The design search uses local analytical and thermal screening. Any cloud cases listed below are supporting evidence; a successful cloud job alone does not validate the full exhaust model.";
  $("provenance-links").replaceChildren();const seen=new Set();
  function visit(value,key="",context=""){
    if(typeof value==="string"&&/^https?:\/\//i.test(value)){
      try{const url=new URL(value);if(!["https:","http:"].includes(url.protocol)||seen.has(url.href))return;seen.add(url.href);const geometry=context.match(/d(\d+)_l(\d+)/i);const label=url.hostname.includes("fgwilson")?"Generator reference datasheet ↗":/project/i.test(key)?geometry?`${geometry[1]} × ${geometry[2]} mm · Allsolve ↗`:"Allsolve project ↗":key.replaceAll("_"," ")+" ↗";const link=element("a",label);link.href=url.href;link.target="_blank";link.rel="noopener noreferrer";$("provenance-links").append(link);}catch(_){/* Invalid links are not rendered. */}
    }else if(value&&typeof value==="object")Object.entries(value).forEach(([name,item])=>visit(item,name,typeof value.case==="string"?value.case:context));
  }
  visit(provenance);visit(cloud);visit(selectedCandidate()?.source);visit(state.config?.default_sources);$("raw-evidence").textContent=JSON.stringify({mode:data.mode,summary:data.summary,provenance,cloud_study:cloud,default_sources:state.config?.default_sources,selected_design_source:selectedCandidate()?.source,model_inputs:data.inputs??state.defaults},null,2);
}

$("planner-form").addEventListener("submit",solve);
$("planner-form").addEventListener("input",markPending);$("objective").addEventListener("change",markPending);
$("add-point").addEventListener("click",()=>{appendDutyRow({name:`Point ${$("duty-body").children.length+1}`,duration_s:300,mass_flow_kg_s:.03,inlet_temp_c:300},$("duty-body").children.length);markPending();});
$("reset-button").addEventListener("click",()=>{if(!state.config)return;fillDefaults(state.config.defaults??state.config);markPending();});
$("retry-button").addEventListener("click",()=>state.defaults?solve():loadConfig());
loadConfig();
