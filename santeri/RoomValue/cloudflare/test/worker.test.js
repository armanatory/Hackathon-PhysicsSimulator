import assert from "node:assert/strict";
import test from "node:test";
import { configuredOrigin, configuredSecret, createHandler, MAX_REQUEST_BYTES, routeMethod } from "../src/index.js";

const SITE = "https://roomvalue.santerihukari.com";
const ID = "0abcde12-3456-7890-abcd-123456789abc";
const SECRET = "test-only-server-secret-0123456789ABCDEF";
const connected = { ROOMVALUE_API_ORIGIN: "https://solver.example.com", ROOMVALUE_ORIGIN_SECRET: SECRET };
const running = { ...connected, ROOMVALUE_ALLOW_RUNS: "true" };
const request = (path, init = {}) => new Request(SITE + path, init);

test("only current 3D website API routes are allowed", () => {
  for (const path of ["/api/health", "/api/room3d/catalog", "/api/room3d/minimize/latest", "/api/room3d/preview/room", "/api/room3d/preview/field", `/api/jobs/${ID}`]) {
    assert.equal(routeMethod(path), "GET");
  }
  for (const path of ["/api/room3d/minimize", `/api/jobs/${ID}/resume`]) assert.equal(routeMethod(path), "POST");
  for (const path of ["/api", "/api/compare", "/api/room3d/optimize", "/api/room3d/latest", "/api/jobs/not-a-uuid", `/api/jobs/${ID}/delete`, "/api/room3d/preview/anything", "/api/room3d/minimize/", "/docs", "/api/openapi.json"]) {
    assert.equal(routeMethod(path), null, path);
  }
});

test("origin accepts only a bare HTTPS origin", () => {
  assert.equal(configuredOrigin(connected), "https://solver.example.com");
  for (const origin of [undefined, "not-a-url", "http://solver.example.com", "https://user:pass@solver.example.com", "https://solver.example.com/subpath", "https://solver.example.com/?query=1", "https://solver.example.com/#fragment"]) {
    assert.equal(configuredOrigin({ ROOMVALUE_API_ORIGIN: origin }), null);
  }
});

test("origin secret must be long and header-safe", () => {
  assert.equal(configuredSecret(connected), SECRET);
  for (const secret of [undefined, "replace-me", " ".repeat(40), "x".repeat(32) + "\n", "ä".repeat(40)]) {
    assert.equal(configuredSecret({ ROOMVALUE_ORIGIN_SECRET: secret }), null);
  }
});

test("non-API paths are served through the assets binding", async () => {
  let seen;
  const handler = createHandler(() => assert.fail("API should not be called"));
  const req = request("/assets/index.js");
  const response = await handler(req, { ASSETS: { fetch: async (r) => { seen = r; return new Response("asset"); } } });
  assert.equal(seen, req);
  assert.equal(await response.text(), "asset");
});

test("unknown API routes cannot fall through to the SPA or origin", async () => {
  const handler = createHandler(() => assert.fail("Origin should not be called"));
  const response = await handler(request("/api/compare", { method: "POST" }), running);
  assert.equal(response.status, 404);
  assert.equal((await response.json()).code, "route_not_available");
});

test("unsupported methods return their exact allowed method", async () => {
  const handler = createHandler(() => assert.fail("Origin should not be called"));
  for (const [path, method, allowed] of [["/api/room3d/catalog", "POST", "GET"], ["/api/room3d/minimize", "GET", "POST"], ["/api/health", "HEAD", "GET"]]) {
    const response = await handler(request(path, { method }), running);
    assert.equal(response.status, 405);
    assert.equal(response.headers.get("Allow"), allowed);
  }
});

test("API queries are rejected", async () => {
  const handler = createHandler(() => assert.fail("Origin should not be called"));
  assert.equal((await handler(request("/api/room3d/catalog?secret=bad"), connected)).status, 400);
});

test("missing and invalid backend settings have safe useful errors", async () => {
  const handler = createHandler(() => assert.fail("Origin should not be called"));
  for (const env of [{}, { ...connected, ROOMVALUE_ORIGIN_SECRET: "short" }, { ...connected, ROOMVALUE_API_ORIGIN: "http://localhost:8002" }]) {
    const response = await handler(request("/api/room3d/catalog"), env);
    assert.equal(response.status, 503);
    assert.equal(response.headers.get("Cache-Control"), "no-store");
    const json = await response.json();
    assert.equal(json.code, "backend_not_configured");
    assert.match(json.detail, /simulation service/);
    assert.equal(JSON.stringify(json).includes(SECRET), false);
  }
});

test("GET proxy attaches only controlled headers and strips client credentials", async () => {
  let seen;
  const handler = createHandler(async (url, init) => {
    seen = { url, init };
    return new Response('{"ok":true}', { headers: { "Content-Type": "application/json", "Set-Cookie": "session=upstream-secret", "Access-Control-Allow-Origin": "*", "X-Internal": "secret" } });
  });
  const response = await handler(request("/api/room3d/catalog", { headers: { Cookie: "session=caller", Authorization: "Bearer caller", Origin: "https://foreign.example", "X-RoomValue-Origin-Secret": "caller-fake", "CF-Access-Jwt-Assertion": "caller-jwt", "X-Forwarded-Host": "foreign.example" } }), connected);
  assert.equal(seen.url.href, "https://solver.example.com/api/room3d/catalog");
  assert.equal(seen.init.method, "GET");
  assert.equal(seen.init.redirect, "manual");
  assert.equal(seen.init.headers.get("X-RoomValue-Origin-Secret"), SECRET);
  assert.deepEqual([...seen.init.headers.keys()].sort(), ["accept", "cache-control", "x-roomvalue-origin-secret"]);
  assert.equal(response.headers.get("Set-Cookie"), null);
  assert.equal(response.headers.get("Access-Control-Allow-Origin"), null);
  assert.equal(response.headers.get("X-Internal"), null);
  assert.equal(response.headers.get("Cache-Control"), "no-store");
  assert.deepEqual(await response.json(), { ok: true });
});

test("submission gate fails closed unless explicitly enabled", async () => {
  const handler = createHandler(() => assert.fail("Origin should not be called"));
  for (const allow of [undefined, "false", "TRUE", true]) {
    const response = await handler(request("/api/room3d/minimize", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }), { ...connected, ROOMVALUE_ALLOW_RUNS: allow });
    assert.equal(response.status, 403);
    assert.equal((await response.json()).code, "simulation_submissions_disabled");
  }
});

test("cross-origin submissions are forbidden even when submissions enabled", async () => {
  const handler = createHandler(() => assert.fail("Origin should not be called"));
  const response = await handler(request("/api/room3d/minimize", { method: "POST", headers: { "Content-Type": "application/json", Origin: "https://foreign.example" }, body: "{}" }), running);
  assert.equal(response.status, 403);
  assert.equal((await response.json()).code, "origin_not_allowed");
});

test("enabled same-origin POST forwards its JSON body, no client auth", async () => {
  let seen;
  const body = '{"max_panels":1,"sources":[]}';
  const handler = createHandler(async (url, init) => {
    seen = { url, init };
    return Response.json({ job_id: ID }, { status: 202 });
  });
  const response = await handler(request("/api/room3d/minimize", { method: "POST", headers: { "Content-Type": "application/json; charset=utf-8", Origin: SITE, Authorization: "Bearer caller" }, body }), running);
  assert.equal(response.status, 202);
  assert.equal(seen.init.headers.get("Content-Type"), "application/json");
  assert.equal(seen.init.headers.get("Authorization"), null);
  assert.equal(new TextDecoder().decode(seen.init.body), body);
  assert.equal(seen.init.headers.get("X-RoomValue-Origin-Secret"), SECRET);
});

test("empty resume body is allowed, other content types and missing minimize JSON type rejected", async () => {
  let calls = 0;
  const handler = createHandler(async (_url, init) => { calls++; assert.equal(init.body, undefined); return new Response("{}"); });
  assert.equal((await handler(request(`/api/jobs/${ID}/resume`, { method: "POST" }), running)).status, 200);
  for (const contentType of [null, "text/plain", "application/octet-stream"]) {
    const headers = contentType ? { "Content-Type": contentType } : {};
    assert.equal((await handler(request("/api/room3d/minimize", { method: "POST", headers }), running)).status, 415);
  }
  assert.equal(calls, 1);
});

test("oversized declared and actual POST bodies never reach the origin", async () => {
  const handler = createHandler(() => assert.fail("Origin should not be called"));
  for (const init of [
    { headers: { "Content-Type": "application/json", "Content-Length": String(MAX_REQUEST_BYTES + 1) }, body: "{}" },
    { headers: { "Content-Type": "application/json" }, body: "x".repeat(MAX_REQUEST_BYTES + 1) },
  ]) {
    const response = await handler(request("/api/room3d/minimize", { method: "POST", ...init }), running);
    assert.equal(response.status, 413);
  }
});

test("upstream redirects are not followed or exposed", async () => {
  const handler = createHandler(async () => new Response(null, { status: 302, headers: { Location: "https://foreign.example" } }));
  const response = await handler(request("/api/health"), connected);
  assert.equal(response.status, 502);
  assert.equal(response.headers.get("Location"), null);
  assert.equal((await response.json()).code, "backend_redirect_rejected");
});

test("upstream network failures produce safe offline health without raw errors", async () => {
  const handler = createHandler(async () => { throw new Error(`internal connection ${SECRET}`); });
  const response = await handler(request("/api/health"), connected);
  assert.equal(response.status, 200);
  const text = await response.text();
  assert.equal(text.includes(SECRET), false);
  assert.equal(JSON.parse(text).allsolve_ready, false);
  assert.equal(JSON.parse(text).deployment, "worker-pc");
  assert.equal(JSON.parse(text).offline, true);
});

test("preview image MIME and upstream non-success status are preserved", async () => {
  const handler = createHandler(async (_url, init) => {
    assert.equal(init.headers.get("Accept"), "image/png");
    return new Response("png", { status: 404, headers: { "Content-Type": "image/png" } });
  });
  const response = await handler(request("/api/room3d/preview/room"), connected);
  assert.equal(response.status, 404);
  assert.equal(response.headers.get("Content-Type"), "image/png");
  assert.equal(await response.text(), "png");
});

test("VPC binding takes precedence and receives only the fixed target and safe headers", async () => {
  let seen;
  const handler = createHandler(() => assert.fail("Public fetch must not be used"));
  const response = await handler(request("/api/room3d/catalog", { headers: { Cookie: "caller", Authorization: "Bearer caller", "X-RoomValue-Origin-Secret": "fake", "X-Forwarded-Host": "attacker" } }), {
    ...connected,
    ROOMVALUE_API: { fetch: async (req) => { seen = req; return Response.json({ catalog: true }); } },
  });
  assert.equal(response.status, 200);
  assert.equal(seen.url, "http://roomvalue.internal/api/room3d/catalog");
  assert.equal(seen.redirect, "manual");
  assert.equal(seen.headers.get("X-RoomValue-Origin-Secret"), SECRET);
  assert.deepEqual([...seen.headers.keys()].sort(), ["accept", "cache-control", "x-roomvalue-origin-secret"]);
});

test("VPC binding works without a public origin and still requires the server secret", async () => {
  let calls = 0;
  const binding = { fetch: async () => { calls++; return Response.json({ ok: true }); } };
  const handler = createHandler(() => assert.fail("Public fetch must not be used"));
  assert.equal((await handler(request("/api/room3d/catalog"), { ROOMVALUE_API: binding, ROOMVALUE_ORIGIN_SECRET: SECRET })).status, 200);
  assert.equal((await handler(request("/api/room3d/catalog"), { ROOMVALUE_API: binding })).status, 503);
  assert.equal(calls, 1);
});

test("VPC submission forwards JSON only when enabled and never substitutes a snapshot", async () => {
  let seen;
  const handler = createHandler(() => assert.fail("Public fetch must not be used"));
  const env = { ROOMVALUE_ALLOW_RUNS: "true", ROOMVALUE_ORIGIN_SECRET: SECRET, ROOMVALUE_API: { fetch: async (req) => { seen = req; return Response.json({ job_id: ID }, { status: 202 }); } } };
  const response = await handler(request("/api/room3d/minimize", { method: "POST", headers: { "Content-Type": "application/json", Origin: SITE }, body: '{"max_panels":0}' }), env);
  assert.equal(response.status, 202);
  assert.equal(await seen.text(), '{"max_panels":0}');
  assert.equal(seen.headers.get("X-RoomValue-Origin-Secret"), SECRET);
  const failed = await handler(request("/api/room3d/minimize", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }), {
    ...env, ROOMVALUE_API: { fetch: async () => { throw new Error("offline"); } }, ASSETS: { fetch: () => assert.fail("POST must not use snapshots") },
  });
  assert.equal(failed.status, 503);
  assert.equal((await failed.json()).code, "backend_unavailable");
});

const snapshotCatalog = { room: { size_m: [5.705, 5.965, 2.355] }, sources: [{ id: "src1" }], slots: [], allsolve_ready: true };
const snapshotJob = { job_id: ID, status: "completed", result: { objective: "minimize_listener_noise", dimension: 3, optimal_layout: { status: "SUCCESS", noise_db: 56.2412, simulation_ids: ["verified-real-simulation"] } }, progress: { stage: "completed", evaluated: 7 } };
function snapshots(overrides = {}) {
  return { fetch: async (req) => {
    const path = new URL(req.url).pathname;
    if (path === "/deployment/catalog.json") return Response.json(snapshotCatalog);
    if (path === "/deployment/default-job.json") return Response.json(snapshotJob);
    if (path === "/deployment/room.png" || path === "/deployment/field.png") return new Response("verified png", { headers: { "Content-Type": "image/png" } });
    assert.fail(`Unexpected assets request: ${path}`);
  }, ...overrides };
}

test("offline and unconfigured origins serve a frozen catalog with availability false", async () => {
  const handler = createHandler(async () => { throw new Error("PC asleep"); });
  for (const env of [{ ASSETS: snapshots() }, { ...connected, ASSETS: snapshots() }, { ROOMVALUE_API: { fetch: async () => { throw new Error("offline"); } }, ROOMVALUE_ORIGIN_SECRET: SECRET, ASSETS: snapshots() }]) {
    const response = await handler(request("/api/room3d/catalog"), env);
    const catalog = await response.json();
    assert.equal(response.status, 200);
    assert.deepEqual(catalog.room, snapshotCatalog.room);
    assert.equal(catalog.allsolve_ready, false);
    assert.equal(catalog.snapshot, true);
    assert.equal(catalog.deployment, "worker-pc");
    assert.equal(response.headers.get("X-RoomValue-Mode"), "offline-snapshot");
  }
  assert.equal(snapshotCatalog.allsolve_ready, true);
});

test("offline latest/default job preserves actual verified data and refuses unrelated job IDs", async () => {
  const handler = createHandler(async () => { throw new Error("PC asleep"); });
  const env = { ...connected, ASSETS: snapshots() };
  for (const path of ["/api/room3d/minimize/latest", `/api/jobs/${ID}`]) {
    const response = await handler(request(path), env);
    const job = await response.json();
    assert.equal(response.status, 200);
    assert.equal(job.job_id, ID);
    assert.equal(job.status, "completed");
    assert.deepEqual(job.result, snapshotJob.result);
    assert.equal(job.allsolve_ready, false);
    assert.match(job.progress.message, /verified saved example/);
    assert.equal(job.progress.evaluated, 7);
  }
  const response = await handler(request("/api/jobs/ffffffff-ffff-ffff-ffff-ffffffffffff"), env);
  assert.equal(response.status, 503);
  assert.equal((await response.json()).code, "backend_unavailable");
  assert.equal(snapshotJob.progress.message, undefined);
});

test("snapshot read cannot turn SPA HTML or an unfinished job into valid API data", async () => {
  const handler = createHandler(async () => { throw new Error("PC asleep"); });
  const html = { ...connected, ASSETS: snapshots({ fetch: async () => new Response("<html>SPA</html>", { headers: { "Content-Type": "text/html" } }) }) };
  assert.equal((await handler(request("/api/room3d/catalog"), html)).status, 503);
  const unfinished = { ...connected, ASSETS: snapshots({ fetch: async () => Response.json({ ...snapshotJob, status: "running" }) }) };
  assert.equal((await handler(request("/api/room3d/minimize/latest"), unfinished)).status, 503);
});

test("offline previews use exact PNG assets and reject SPA responses", async () => {
  const handler = createHandler(async () => { throw new Error("PC asleep"); });
  for (const view of ["room", "field"]) {
    const response = await handler(request(`/api/room3d/preview/${view}`), { ...connected, ASSETS: snapshots() });
    assert.equal(response.status, 200);
    assert.equal(response.headers.get("Content-Type"), "image/png");
    assert.equal(await response.text(), "verified png");
  }
  const html = { ...connected, ASSETS: snapshots({ fetch: async () => new Response("<html>SPA</html>", { headers: { "Content-Type": "text/html" } }) }) };
  assert.equal((await handler(request("/api/room3d/preview/room"), html)).status, 503);
});

test("health reports PC-backed deployment online and offline, without exposing errors", async () => {
  const online = createHandler(async () => Response.json({ status: "ok", allsolve_ready: true, message: "ready" }));
  const health = await (await online(request("/api/health"), connected)).json();
  assert.equal(health.allsolve_ready, true);
  assert.equal(health.deployment, "worker-pc");
  assert.equal(health.offline, false);
  const failed = createHandler(async () => new Response("unreachable", { status: 503 }));
  const response = await failed(request("/api/health"), connected);
  const offline = await response.json();
  assert.equal(response.status, 200);
  assert.equal(offline.allsolve_ready, false);
  assert.equal(offline.offline, true);
  assert.match(offline.message, /PC is offline/);
});
