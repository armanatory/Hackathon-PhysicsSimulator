/** Static MetaSense app with a scoped, authenticated private Python bridge. */
const JOB = /^\/api\/optimization\/jobs\/[0-9a-f]{32}$/;
const READ_ROUTES = new Set([
  "/api/health", "/api/optimization/config", "/api/optimization/jobs/latest", "/api/validation/slab",
]);
export const MAX_REQUEST_BYTES = 32 * 1024;
const OFFLINE_MESSAGE = "Simulation PC offline. Viewing the verified saved result; optimization is unavailable.";

export function routeMethod(path) {
  if (READ_ROUTES.has(path) || JOB.test(path)) return "GET";
  if (path === "/api/optimization/jobs") return "POST";
  return null;
}

function responseJson(value, status = 200, headers = {}) {
  return Response.json(value, { status, headers: {
    "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", ...headers,
  } });
}
function error(status, code, detail, headers = {}) {
  return responseJson({ code, detail }, status, headers);
}
function strongSecret(value) {
  return typeof value === "string" && value.length >= 32 && value.length <= 1024 && /^[\x21-\x7e]+$/.test(value);
}
function sameOrigin(request, url) {
  return request.headers.get("Origin") === url.origin;
}
function jsonContentType(request) {
  return /^application\/json(?:\s*;\s*charset=utf-8)?$/i.test(request.headers.get("Content-Type") || "");
}

async function boundedBody(request, limit) {
  const length = request.headers.get("Content-Length");
  if (length !== null && (!/^\d+$/.test(length) || Number(length) > limit)) return null;
  if (!request.body) return new Uint8Array();
  const reader = request.body.getReader();
  const chunks = [];
  let size = 0;
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > limit) { await reader.cancel(); return null; }
      chunks.push(value);
    }
  } finally { reader.releaseLock(); }
  const body = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { body.set(chunk, offset); offset += chunk.byteLength; }
  return body;
}

async function readSnapshot(env, url, filename) {
  try {
    const response = await env.ASSETS?.fetch(new Request(new URL(`/deployment/${filename}`, url.origin)));
    if (!response?.ok || !response.headers.get("Content-Type")?.includes("application/json")) return null;
    return await response.json();
  } catch { return null; }
}
function savedConfig(value) {
  return value?.label === "allsolve_liquid_discriminator" && value.synthetic === false &&
    value.default_request?.objective === "max_abs_reflectance_contrast" &&
    Array.isArray(value.default_request.liquids) && value.default_request.liquids.length === 2 &&
    value.default_request.liquids.every(liquid => typeof liquid.label === "string" && Number.isFinite(liquid.n)) &&
    value.limits && typeof value.limits === "object" && value.model && typeof value.model === "object";
}
function savedJob(value) {
  const report = value?.report, best = report?.best_design, verification = best?.verification;
  return typeof value?.id === "string" && JOB.test(`/api/optimization/jobs/${value.id}`) &&
    value.label === "allsolve_liquid_discriminator" && value.synthetic === false && value.status === "completed" &&
    report?.label === "allsolve_liquid_discriminator" && report.synthetic === false && report.status === "completed" &&
    best?.validated === true && verification?.passed === true && verification.checks?.mesh_dimensions === true &&
    Object.values(verification.checks).every(check => check === true) &&
    Number.isFinite(best.R_A) && Number.isFinite(best.R_B) && best.R_A >= 0 && best.R_A <= 1 && best.R_B >= 0 && best.R_B <= 1 &&
    value.request?.objective === "max_abs_reflectance_contrast";
}
function offlineResponse(value) {
  return responseJson({ ...value, deployment: "worker-pc", offline: true, snapshot: true, message: OFFLINE_MESSAGE }, 200,
    { "X-MetaSense-Mode": "offline-snapshot" });
}
async function offlineGet(env, url) {
  if (url.pathname === "/api/health") return offlineResponse({ status: "ok", allsolve_configured: false, liquid_optimizer_available: false });
  if (url.pathname === "/api/optimization/config") {
    const config = await readSnapshot(env, url, "config.json");
    if (savedConfig(config)) return offlineResponse({ ...config, available: false, allsolve_configured: false });
  }
  if (url.pathname === "/api/optimization/jobs/latest" || JOB.test(url.pathname)) {
    const job = await readSnapshot(env, url, "latest-job.json");
    if (savedJob(job) && (url.pathname === "/api/optimization/jobs/latest" || url.pathname === `/api/optimization/jobs/${job.id}`)) {
      return offlineResponse(job);
    }
  }
  return null;
}

async function proxyApi(request, env, url) {
  const method = routeMethod(url.pathname);
  if (!method) return error(404, "route_not_available", "This API route is unavailable.");
  if (url.search) return error(400, "query_not_available", "This API route does not accept query parameters.");
  if (request.method !== method) return error(405, "method_not_allowed", `Use ${method} for this API route.`, { Allow: method });
  let body;
  if (method === "POST") {
    if (!sameOrigin(request, url)) return error(403, "origin_not_allowed", "Submit optimization requests from this website.");
    if (env.METASENSE_ALLOW_RUNS !== "true") return error(403, "optimization_submissions_disabled", "Optimization submissions are disabled.");
    if (!jsonContentType(request)) return error(415, "content_type_not_allowed", "Optimization requests require application/json.");
    body = await boundedBody(request, MAX_REQUEST_BYTES);
    if (body === null) return error(413, "request_too_large", "The optimization request exceeds 32 KiB.");
  }
  const service = env.METASENSE_API && typeof env.METASENSE_API.fetch === "function" ? env.METASENSE_API : null;
  if (!service || !strongSecret(env.METASENSE_ORIGIN_SECRET)) {
    if (method === "GET") { const snapshot = await offlineGet(env, url); if (snapshot) return snapshot; }
    return error(503, "backend_not_configured", "The simulation service is not connected.");
  }
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15_000);
  try {
    const headers = new Headers({ Accept: "application/json", "X-MetaSense-Origin-Secret": env.METASENSE_ORIGIN_SECRET, "Cache-Control": "no-store" });
    if (method === "POST") headers.set("Content-Type", "application/json");
    const outgoing = new Request(new URL(url.pathname, "http://metasense.internal"), {
      method, headers, body: method === "POST" ? body : undefined, redirect: "manual", signal: controller.signal,
    });
    const upstream = await service.fetch(outgoing);
    if (upstream.status >= 300 && upstream.status < 400) return error(502, "backend_redirect_rejected", "Unexpected simulation service redirect.");
    if (method === "GET" && upstream.status >= 500) { const snapshot = await offlineGet(env, url); if (snapshot) return snapshot; }
    if (!upstream.headers.get("Content-Type")?.includes("application/json")) return error(502, "backend_response_rejected", "The simulation service returned an invalid response.");
    const payload = await upstream.json();
    if (upstream.ok && payload && typeof payload === "object" && !Array.isArray(payload)) {
      return responseJson({ ...payload, deployment: "worker-pc", offline: false, snapshot: false }, upstream.status);
    }
    return responseJson(payload, upstream.status);
  } catch {
    if (method === "GET") { const snapshot = await offlineGet(env, url); if (snapshot) return snapshot; }
    return error(503, "backend_unavailable", "The simulation PC is offline or unreachable.");
  } finally { clearTimeout(timeout); }
}

// The service and asset bindings are replaceable in fully local tests.
export function createHandler() {
  return async (request, env) => {
    const url = new URL(request.url);
    if (url.pathname === "/api" || url.pathname.startsWith("/api/")) return proxyApi(request, env, url);
    if (!env.ASSETS || typeof env.ASSETS.fetch !== "function") return error(503, "assets_not_configured", "Website assets are unavailable.");
    return env.ASSETS.fetch(request);
  };
}

export default { fetch: createHandler() };
