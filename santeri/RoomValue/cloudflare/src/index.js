/**
 * Public RoomValue static app and a narrowly scoped bridge to its Python API.
 * Solver credentials remain exclusively on the Python origin.
 */
const UUID = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}";
const JOB = new RegExp(`^/api/jobs/${UUID}$`);
const RESUME = new RegExp(`^/api/jobs/${UUID}/resume$`);
const READ_ROUTES = new Set([
  "/api/health",
  "/api/room3d/catalog",
  "/api/room3d/minimize/latest",
  "/api/room3d/preview/room",
  "/api/room3d/preview/field",
]);
export const MAX_REQUEST_BYTES = 32 * 1024;
const OFFLINE_MESSAGE = "The simulation PC is offline. Showing a verified saved example; new simulations will be available when the PC reconnects.";

export function routeMethod(pathname) {
  if (READ_ROUTES.has(pathname) || JOB.test(pathname)) return "GET";
  if (pathname === "/api/room3d/minimize" || RESUME.test(pathname)) return "POST";
  return null;
}

function jsonError(status, code, detail, extraHeaders = {}) {
  return Response.json({ detail, code }, {
    status,
    headers: { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", ...extraHeaders },
  });
}

export function configuredOrigin(env) {
  if (typeof env.ROOMVALUE_API_ORIGIN !== "string") return null;
  try {
    const url = new URL(env.ROOMVALUE_API_ORIGIN);
    if (url.protocol !== "https:" || url.username || url.password || url.search || url.hash || url.pathname !== "/") return null;
    return url.origin;
  } catch {
    return null;
  }
}

export function configuredSecret(env) {
  const secret = env.ROOMVALUE_ORIGIN_SECRET;
  // A deployment must supply a strong header-safe value, not an accidental placeholder.
  return typeof secret === "string" && secret.length >= 32 && /^[\x21-\x7e]+$/.test(secret) ? secret : null;
}

async function readSnapshot(env, siteUrl, filename) {
  if (!env.ASSETS || typeof env.ASSETS.fetch !== "function") return null;
  try {
    const response = await env.ASSETS.fetch(new Request(new URL(`/deployment/${filename}`, siteUrl.origin)));
    // An absent static asset may resolve to index.html through SPA fallback.
    if (!response.ok || !response.headers.get("Content-Type")?.includes("application/json")) return null;
    return await response.json();
  } catch {
    return null;
  }
}

function savedJob(job) {
  return job && JOB.test(`/api/jobs/${job.job_id}`) && job.status === "completed" &&
    job.result?.objective === "minimize_listener_noise" && job.result?.dimension === 3 &&
    job.result?.optimal_layout?.status === "SUCCESS";
}

function snapshotResponse(value) {
  return Response.json(value, { headers: { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "X-RoomValue-Mode": "offline-snapshot" } });
}

async function offlineGet(env, url) {
  if (url.pathname === "/api/health") {
    return snapshotResponse({ status: "ok", allsolve_ready: false, deployment: "worker-pc", offline: true, snapshot: true, message: OFFLINE_MESSAGE });
  }
  if (url.pathname === "/api/room3d/catalog") {
    const catalog = await readSnapshot(env, url, "catalog.json");
    if (catalog?.room?.size_m?.length === 3 && Array.isArray(catalog.sources) && Array.isArray(catalog.slots)) {
      return snapshotResponse({ ...catalog, allsolve_ready: false, deployment: "worker-pc", offline: true, snapshot: true, message: OFFLINE_MESSAGE });
    }
  }
  if (url.pathname === "/api/room3d/minimize/latest" || JOB.test(url.pathname)) {
    const job = await readSnapshot(env, url, "default-job.json");
    if (savedJob(job) && (url.pathname === "/api/room3d/minimize/latest" || url.pathname === `/api/jobs/${job.job_id}`)) {
      return snapshotResponse({ ...job, allsolve_ready: false, deployment: "worker-pc", offline: true, snapshot: true,
        progress: { ...job.progress, stage: "completed", message: OFFLINE_MESSAGE } });
    }
  }
  const preview = {
    "/api/room3d/preview/room": "room.png",
    "/api/room3d/preview/field": "field.png",
  }[url.pathname];
  if (preview && env.ASSETS && typeof env.ASSETS.fetch === "function") {
    try {
      const response = await env.ASSETS.fetch(new Request(new URL(`/deployment/${preview}`, url.origin)));
      if (response.ok && response.headers.get("Content-Type")?.split(";")[0] === "image/png") {
        return new Response(response.body, { headers: { "Content-Type": "image/png", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "X-RoomValue-Mode": "offline-snapshot" } });
      }
    } catch { /* Return the explicit service-unavailable error below. */ }
  }
  return null;
}

async function proxyApi(request, env, url, fetchImpl) {
  const method = routeMethod(url.pathname);
  if (!method) return jsonError(404, "route_not_available", "This API route is not exposed by the RoomValue website.");
  if (url.search) return jsonError(400, "query_not_available", "This API route does not accept query parameters.");
  if (request.method !== method) return jsonError(405, "method_not_allowed", `Use ${method} for this API route.`, { Allow: method });

  const vpc = env.ROOMVALUE_API && typeof env.ROOMVALUE_API.fetch === "function" ? env.ROOMVALUE_API : null;
  const origin = vpc ? "http://roomvalue.internal" : configuredOrigin(env);
  const secret = configuredSecret(env);
  if (!origin || !secret) {
    if (method === "GET") {
      const snapshot = await offlineGet(env, url);
      if (snapshot) return snapshot;
    }
    return jsonError(503, "backend_not_configured", "The 3D website is online, but its simulation service has not been connected to this cloud deployment.");
  }

  let body;
  if (method === "POST") {
    const callerOrigin = request.headers.get("Origin");
    if (callerOrigin && callerOrigin !== url.origin) {
      return jsonError(403, "origin_not_allowed", "Submit simulation requests from this RoomValue website.");
    }
    if (env.ROOMVALUE_ALLOW_RUNS !== "true") {
      return jsonError(403, "simulation_submissions_disabled", "Cloud simulation submissions are disabled. Viewing existing results remains available.");
    }
    const length = request.headers.get("Content-Length");
    if (length && (!/^\d+$/.test(length) || Number(length) > MAX_REQUEST_BYTES)) {
      return jsonError(413, "request_too_large", "The simulation request exceeds the 32 KiB limit.");
    }
    const contentType = request.headers.get("Content-Type");
    if (contentType && !/^application\/json(?:\s*;\s*charset=utf-8)?$/i.test(contentType)) {
      return jsonError(415, "content_type_not_allowed", "Simulation requests must use application/json.");
    }
    if (url.pathname === "/api/room3d/minimize" && !contentType) {
      return jsonError(415, "content_type_not_allowed", "Simulation requests must use application/json.");
    }
    body = await request.arrayBuffer();
    if (body.byteLength > MAX_REQUEST_BYTES) {
      return jsonError(413, "request_too_large", "The simulation request exceeds the 32 KiB limit.");
    }
  }

  // Construct headers from an allowlist. Caller cookies, bearer tokens, Access
  // assertions and origin-secret headers cannot reach or authenticate to the API.
  const headers = new Headers({
    Accept: url.pathname.startsWith("/api/room3d/preview/") ? "image/png" : "application/json",
    "X-RoomValue-Origin-Secret": secret,
    "Cache-Control": "no-store",
  });
  if (method === "POST" && body.byteLength) headers.set("Content-Type", "application/json");
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 25_000);
  try {
    const target = new URL(url.pathname, origin);
    const init = {
      method,
      headers,
      body: method === "POST" && body.byteLength ? body : undefined,
      redirect: "manual",
      signal: controller.signal,
    };
    // VPC service routing is fixed by the binding's configured host and port.
    // Neither this dummy hostname nor any caller input selects a network target.
    const upstream = vpc ? await vpc.fetch(new Request(target, init)) : await fetchImpl(target, init);
    if (upstream.status >= 300 && upstream.status < 400) {
      return jsonError(502, "backend_redirect_rejected", "The simulation service returned an unexpected redirect.");
    }
    if (method === "GET" && upstream.status >= 500) {
      const snapshot = await offlineGet(env, url);
      if (snapshot) return snapshot;
    }
    if (url.pathname === "/api/health" && upstream.ok && upstream.headers.get("Content-Type")?.includes("application/json")) {
      const health = await upstream.json();
      return Response.json({ ...health, deployment: "worker-pc", offline: false, snapshot: false }, {
        headers: { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" },
      });
    }
    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        "Content-Type": upstream.headers.get("Content-Type") || "application/json",
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
      },
    });
  } catch {
    if (method === "GET") {
      const snapshot = await offlineGet(env, url);
      if (snapshot) return snapshot;
    }
    return jsonError(503, "backend_unavailable", "The simulation PC is currently offline or unreachable. New simulations will be available when the PC reconnects.");
  } finally {
    clearTimeout(timeout);
  }
}

// Dependency injection keeps route/security tests entirely local.
export function createHandler(fetchImpl = fetch) {
  return async (request, env) => {
    const url = new URL(request.url);
    if (url.pathname === "/api" || url.pathname.startsWith("/api/")) {
      return proxyApi(request, env, url, fetchImpl);
    }
    if (!env.ASSETS || typeof env.ASSETS.fetch !== "function") {
      return jsonError(503, "assets_not_configured", "The website assets have not been deployed.");
    }
    return env.ASSETS.fetch(request);
  };
}

export default { fetch: createHandler() };
