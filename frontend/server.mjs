/** Static assets and browser runtime configuration only. API traffic goes directly to FastAPI. */
import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { createServer } from "node:http";
import { dirname, extname, resolve, sep } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".svg": "image/svg+xml",
  ".json": "application/json",
  ".ico": "image/x-icon",
  ".png": "image/png",
  ".woff2": "font/woff2",
};

export function createFrontendServer({
  root = resolve(dirname(fileURLToPath(import.meta.url)), "dist"),
  apiBaseUrl = process.env.API_BASE_URL || "http://localhost:8000",
} = {}) {
  const api = new URL(apiBaseUrl);
  if (
    !["http:", "https:"].includes(api.protocol) ||
    api.username ||
    api.password ||
    api.search ||
    api.hash ||
    api.pathname !== "/"
  )
    throw new Error(
      "API_BASE_URL must be an HTTP(S) origin, such as http://localhost:8000",
    );
  const config = `window.__FOLIO_CONFIG__ = ${JSON.stringify({ apiBaseUrl: api.origin })};\n`;
  root = resolve(root);
  return createServer(async (req, res) => {
    if (!["GET", "HEAD"].includes(req.method)) {
      res.writeHead(405, { Allow: "GET, HEAD" });
      res.end();
      return;
    }
    const send = (status, body, type = "text/plain; charset=utf-8") => {
      res.writeHead(status, {
        "Content-Type": type,
        "Content-Length": Buffer.byteLength(body),
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
      });
      res.end(req.method === "HEAD" ? undefined : body);
    };
    let pathname;
    try {
      pathname = decodeURIComponent(
        new URL(req.url, "http://localhost").pathname,
      );
    } catch {
      send(400, "Invalid request path");
      return;
    }
    if (pathname === "/config.js") {
      send(200, config, TYPES[".js"]);
      return;
    }
    if (pathname === "/health") {
      send(200, '{"status":"ok"}', TYPES[".json"]);
      return;
    }
    if (pathname === "/api" || pathname.startsWith("/api/")) {
      send(404, "Use the configured FastAPI origin for API requests.");
      return;
    }
    let target = resolve(root, `.${pathname}`);
    if (target !== root && !target.startsWith(root + sep)) {
      send(403, "Forbidden");
      return;
    }
    try {
      let info;
      try {
        info = await stat(target);
      } catch (error) {
        if (error.code !== "ENOENT") throw error;
      }
      if (!info?.isFile()) {
        if (extname(pathname)) {
          send(404, "Not found");
          return;
        }
        target = resolve(root, "index.html");
        info = await stat(target);
      }
      res.writeHead(200, {
        "Content-Type": TYPES[extname(target)] || "application/octet-stream",
        "Content-Length": info.size,
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": pathname.startsWith("/assets/")
          ? "public, max-age=31536000, immutable"
          : "no-cache",
      });
      if (req.method === "HEAD") {
        res.end();
        return;
      }
      const stream = createReadStream(target);
      stream.on("error", () => res.destroy());
      stream.pipe(res);
    } catch {
      if (!res.headersSent)
        send(500, "Frontend build is unavailable. Run npm run build.");
      else res.destroy();
    }
  });
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(resolve(process.argv[1])).href
) {
  const port = Number(process.env.PORT || 3000);
  if (!Number.isInteger(port) || port < 1 || port > 65535)
    throw new Error("PORT must be between 1 and 65535");
  const server = createFrontendServer();
  server.listen(port, "0.0.0.0", () =>
    console.log(`Folio frontend listening on :${port}`),
  );
  for (const signal of ["SIGINT", "SIGTERM"])
    process.once(signal, () => server.close());
}
