import assert from "node:assert/strict";
import test from "node:test";
import { createHandler, MAX_REQUEST_BYTES, routeMethod } from "../src/index.js";

const SITE = "https://metasense.santerihukari.com";
const ID = "5caa299a62fb450da3c57baa1eec3e36";
const OTHER_ID = "a".repeat(32);
const SECRET = "test-private-origin-secret-" + "x".repeat(32);
const CONFIG = {
  label: "allsolve_liquid_discriminator", synthetic: false, available: true, allsolve_configured: true,
  default_request: { objective: "max_abs_reflectance_contrast", liquids: [{ label: "A", n: 1.33 }, { label: "B", n: 1.38 }] },
  limits: {}, model: {},
};
const SAVED = {
  id: ID, label: "allsolve_liquid_discriminator", synthetic: false, status: "completed",
  created_at: "2026-10-03T00:00:00Z", updated_at: "2026-10-03T00:14:00Z", request: CONFIG.default_request,
  report: {
    label: "allsolve_liquid_discriminator", synthetic: false, status: "completed",
    best_design: { R_A: 0.299669, R_B: 0.460781, validated: true, verification: { passed: true, checks: { mesh_dimensions: true, readout_checks: true } } },
  },
};
function request(path, { method = "GET", body, headers = {} } = {}) {
  return new Request(SITE + path, { method, body, headers });
}
function post(headers = {}, body = "{}") {
  return request("/api/optimization/jobs", { method: "POST", body, headers: { Origin: SITE, "Content-Type": "application/json", ...headers } });
}
function assets(values = { "config.json": CONFIG, "latest-job.json": SAVED }) {
  return { fetch: async req => {
    const key = new URL(req.url).pathname.split("/").at(-1);
    return key in values ? Response.json(values[key]) : new Response("<html>SPA</html>", { headers: { "Content-Type": "text/html" } });
  } };
}
function live(fetch) {
  return { METASENSE_ALLOW_RUNS: "true", METASENSE_ORIGIN_SECRET: SECRET, METASENSE_API: { fetch }, ASSETS: assets() };
}
const handle = createHandler();

test("only current website routes and lowercase job IDs are exposed", () => {
  for (const path of ["/api/health", "/api/optimization/config", "/api/optimization/jobs/latest", `/api/optimization/jobs/${ID}`, "/api/validation/slab"]) assert.equal(routeMethod(path), "GET");
  assert.equal(routeMethod("/api/optimization/jobs"), "POST");
  for (const path of ["/api", "/api/jobs", "/api/session", "/docs", `/api/optimization/jobs/${ID.toUpperCase()}`, `/api/optimization/jobs/${ID}/resume`, "/api/optimization/jobs/../config"]) assert.equal(routeMethod(path), null);
});

test("static assets bypass the API bridge", async () => {
  let seen;
  const response = await handle(request("/"), { ASSETS: { fetch: async req => { seen = req.url; return new Response("app"); } } });
  assert.equal(await response.text(), "app"); assert.equal(seen, SITE + "/");
});

test("unknown API paths never become SPA HTML or bridge calls", async () => {
  const env = live(() => assert.fail("unexpected bridge call"));
  const response = await handle(request("/api/jobs"), env);
  assert.equal(response.status, 404); assert.equal((await response.json()).code, "route_not_available");
});

test("wrong methods and query parameters are rejected before proxying", async () => {
  const env = live(() => assert.fail("unexpected bridge call"));
  const wrong = await handle(request("/api/optimization/config", { method: "POST" }), env);
  assert.equal(wrong.status, 405); assert.equal(wrong.headers.get("Allow"), "GET");
  assert.equal((await handle(request("/api/optimization/config?target=evil"), env)).status, 400);
});

test("public launch forwards immediately with only server-selected headers and target", async () => {
  let outgoing;
  const response = await handle(post({ Cookie: "private-browser-cookie", Authorization: "Bearer caller", "X-MetaSense-Origin-Secret": "forged", "Cf-Access-Jwt-Assertion": "caller-jwt" }, '{"candidate_count":1}'), live(async req => {
    outgoing = req; return Response.json({ id: ID, status: "queued", synthetic: false }, { status: 202, headers: { "Set-Cookie": "origin-cookie=unsafe", Authorization: "private", "X-Secret": "private" } });
  }));
  assert.equal(response.status, 202);
  assert.equal(outgoing.url, "http://metasense.internal/api/optimization/jobs");
  assert.equal(outgoing.redirect, "manual");
  assert.equal(outgoing.headers.get("X-MetaSense-Origin-Secret"), SECRET);
  for (const header of ["Cookie", "Authorization", "Cf-Access-Jwt-Assertion"]) assert.equal(outgoing.headers.get(header), null);
  assert.equal(await outgoing.text(), '{"candidate_count":1}');
  for (const header of ["Set-Cookie", "Authorization", "X-Secret"]) assert.equal(response.headers.get(header), null);
  assert.equal(response.headers.get("Cache-Control"), "no-store");
  assert.deepEqual(await response.json(), { id: ID, status: "queued", synthetic: false, deployment: "worker-pc", offline: false, snapshot: false });
});

test("launch admission requires the exact enabled flag", async () => {
  for (const flag of [undefined, "false", "TRUE", true]) {
    const env = live(() => assert.fail("unexpected bridge call")); env.METASENSE_ALLOW_RUNS = flag;
    assert.equal((await handle(post(), env)).status, 403);
  }
});

test("cross-origin and missing-origin launches are rejected", async () => {
  const env = live(() => assert.fail("unexpected bridge call"));
  assert.equal((await handle(post({ Origin: "https://other.example" }), env)).status, 403);
  assert.equal((await handle(request("/api/optimization/jobs", { method: "POST", body: "{}", headers: { "Content-Type": "application/json" } }), env)).status, 403);
});

test("launch bodies must be JSON and bounded with or without announced length", async () => {
  const env = live(() => assert.fail("unexpected bridge call"));
  assert.equal((await handle(post({ "Content-Type": "text/plain" }), env)).status, 415);
  assert.equal((await handle(post({ "Content-Length": String(MAX_REQUEST_BYTES + 1) }), env)).status, 413);
  assert.equal((await handle(post({ "Content-Length": "-1" }), env)).status, 413);
  assert.equal((await handle(post({}, "x".repeat(MAX_REQUEST_BYTES + 1)), env)).status, 413);
});

test("missing or weak private origin secrets fail closed without forwarding", async () => {
  for (const secret of [undefined, "short", " ".repeat(48), "x".repeat(32) + "\n"]) {
    const env = live(() => assert.fail("unexpected bridge call")); env.METASENSE_ORIGIN_SECRET = secret;
    assert.equal((await handle(post(), env)).status, 503);
  }
});

test("unconfigured and unreachable PC return exact verified saved result metadata", async () => {
  for (const env of [{ ASSETS: assets() }, live(async () => { throw Error("private connector info"); })]) {
    const response = await handle(request("/api/optimization/jobs/latest"), env);
    const value = await response.json();
    assert.equal(value.offline, true); assert.equal(value.snapshot, true); assert.equal(value.status, "completed");
    assert.equal(value.id, ID); assert.equal(value.updated_at, SAVED.updated_at);
    assert.deepEqual(value.report, SAVED.report); assert.deepEqual(value.request, SAVED.request);
    assert.equal(response.headers.get("X-MetaSense-Mode"), "offline-snapshot");
    assert.equal(value.message.includes("private connector info"), false);
  }
});

test("offline config disables runs and keeps real model/default request", async () => {
  const value = await (await handle(request("/api/optimization/config"), { ASSETS: assets() })).json();
  assert.equal(value.available, false); assert.equal(value.allsolve_configured, false); assert.equal(value.offline, true);
  assert.deepEqual(value.default_request, CONFIG.default_request); assert.deepEqual(value.model, CONFIG.model);
  const health = await (await handle(request("/api/health"), { ASSETS: assets() })).json();
  assert.equal(health.liquid_optimizer_available, false); assert.equal(health.offline, true);
});

test("offline snapshot resolves only its own completed job ID", async () => {
  const env = { ASSETS: assets() };
  assert.equal((await handle(request(`/api/optimization/jobs/${ID}`), env)).status, 200);
  const response = await handle(request(`/api/optimization/jobs/${OTHER_ID}`), env);
  assert.equal(response.status, 503); assert.equal((await response.json()).code, "backend_not_configured");
});

test("failed, synthetic, unverified, malformed or missing snapshots are rejected", async () => {
  const variants = [
    { ...SAVED, status: "running" }, { ...SAVED, synthetic: true },
    { ...SAVED, report: { ...SAVED.report, synthetic: true } },
    { ...SAVED, report: { ...SAVED.report, best_design: { ...SAVED.report.best_design, validated: false } } },
    { ...SAVED, report: { ...SAVED.report, best_design: { ...SAVED.report.best_design, verification: { passed: true, checks: { mesh_dimensions: false } } } } },
    null,
  ];
  for (const snapshot of variants) assert.equal((await handle(request("/api/optimization/jobs/latest"), { ASSETS: assets({ "latest-job.json": snapshot }) })).status, 503);
  assert.equal((await handle(request("/api/optimization/jobs/latest"), { ASSETS: assets({}) })).status, 503);
  assert.equal((await handle(request("/api/optimization/config"), { ASSETS: assets({ "config.json": { ...CONFIG, synthetic: true } }) })).status, 503);
});

test("a new offline POST never receives a saved completed job", async () => {
  const response = await handle(post(), live(async () => { throw Error("private failure"); }));
  assert.equal(response.status, 503);
  assert.deepEqual(await response.json(), { code: "backend_unavailable", detail: "The simulation PC is offline or unreachable." });
});

test("live job and config are marked live; null latest remains null", async () => {
  const env = live(async req => Response.json(new URL(req.url).pathname.endsWith("latest") ? null : CONFIG));
  const config = await (await handle(request("/api/optimization/config"), env)).json();
  assert.equal(config.offline, false); assert.equal(config.snapshot, false); assert.equal(config.available, true);
  assert.equal(await (await handle(request("/api/optimization/jobs/latest"), env)).json(), null);
});

test("live validation errors pass through, upstream 404 does not become snapshot", async () => {
  const env = live(async () => Response.json({ detail: "Not found" }, { status: 404 }));
  const response = await handle(request(`/api/optimization/jobs/${ID}`), env);
  assert.equal(response.status, 404); assert.deepEqual(await response.json(), { detail: "Not found" });
  const validation = await handle(post(), live(async () => Response.json({ detail: [{ msg: "Invalid candidate count" }] }, { status: 422 })));
  assert.equal(validation.status, 422);
});

test("GET server errors allow snapshots, redirects and HTML are rejected", async () => {
  const saved = await handle(request("/api/optimization/jobs/latest"), live(async () => Response.json({}, { status: 503 })));
  assert.equal((await saved.json()).snapshot, true);
  const redirect = await handle(request("/api/health"), live(async () => new Response(null, { status: 302, headers: { Location: "https://evil.example" } })));
  assert.equal(redirect.status, 502); assert.equal((await redirect.json()).code, "backend_redirect_rejected");
  const html = await handle(request("/api/health"), live(async () => new Response("<html>not data</html>", { headers: { "Content-Type": "text/html" } })));
  assert.equal(html.status, 502);
});
