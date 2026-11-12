import assert from "node:assert/strict";
import { once } from "node:events";
import { mkdtemp, mkdir, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { createFrontendServer } from "./server.mjs";

test("serves built assets and runtime config without proxying API traffic", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "folio-static-"));
  await mkdir(join(root, "assets"));
  await writeFile(join(root, "index.html"), "<html>Folio</html>");
  await writeFile(join(root, "assets", "app.js"), 'console.log("Folio")');
  const server = createFrontendServer({
    root,
    apiBaseUrl: "http://localhost:8123",
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  t.after(async () => {
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
    await rm(root, { recursive: true, force: true });
  });
  const base = `http://127.0.0.1:${server.address().port}`;
  assert.equal((await fetch(base + "/health")).status, 200);
  assert.match(
    await (await fetch(base + "/config.js")).text(),
    /http:\/\/localhost:8123/,
  );
  assert.equal(
    (await fetch(base + "/config.js")).headers.get("cache-control"),
    "no-store",
  );
  assert.match(await (await fetch(base + "/")).text(), /Folio/);
  assert.equal(
    (await fetch(base + "/assets/app.js")).headers.get("cache-control"),
    "public, max-age=31536000, immutable",
  );
  assert.match(
    (await fetch(base + "/assets/app.js")).headers.get("content-type"),
    /javascript/,
  );
  assert.equal((await fetch(base + "/api/reviews")).status, 404);
  assert.equal((await fetch(base + "/assets/missing.js")).status, 404);
  assert.equal((await fetch(base + "/reviews/example")).status, 200);
  assert.equal((await fetch(base + "/", { method: "POST" })).status, 405);
  assert.equal(await (await fetch(base + "/", { method: "HEAD" })).text(), "");
  assert.equal((await fetch(base + "/%2e%2e%2fsecret")).status, 403);
});

test("rejects invalid API origins", () => {
  for (const apiBaseUrl of [
    "file:///etc/passwd",
    "http://user:pass@localhost:8000",
    "http://localhost:8000/api",
  ]) {
    assert.throws(() => createFrontendServer({ apiBaseUrl }), /API_BASE_URL/);
  }
});
