# Changelog

All notable changes to [JLay2026/partsmith](https://github.com/JLay2026/partsmith).
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project follows semver-ish conventions (see [`ROADMAP.md`](ROADMAP.md)).

## [0.2.4] — 2026-06-09

### Added
- **Persistent design store** (`src/design_store.py`). Designs are
  saved to disk under `{workspace}/designs/` as `{name}.py` (source) +
  `{name}.json` (metadata: timestamps, description, geometry snapshot).
  Survive container restart; models are still in-memory only.
- **4 new MCP tools:**
  - `partsmith_save_design(name, code, description="")` — save + also
    execute as a model so the result is immediately available
  - `partsmith_load_design(name)` — load source from disk + execute
  - `partsmith_list_designs()` — list all saved designs (cheap, no
    re-execution; uses geometry snapshot captured at save time)
  - `partsmith_delete_design(name)` — remove design files from disk
- **5 new REST endpoints:**
  - `POST /design/save`
  - `GET /design/list`
  - `GET /design/{name}` — source + metadata, no execution
  - `DELETE /design/{name}`
  - `POST /design/{name}/load` — load + execute as model

### Design notes
- Two-file persistence (source + sidecar) instead of single JSON so
  source is human-readable on disk (`cat workspace/designs/bracket.py`)
  and git-friendly if the workspace is versioned. Sidecar is bookkeeping
  that can be regenerated from defaults if missing or corrupt.
- `save` always tries to execute the code so geometry can be snapshotted
  for `list` efficiency. If execution fails, save still succeeds — source
  is the source of truth and the user can fix it later.
- Same `NAME_PATTERN` validation as models. Path-traversal defense via
  resolved-path-relative-to check.

### Why
Real designs go through 5-10 iterations. Pre-v0.2.4 every container
restart wiped them. With this, your work isn't gated on container uptime.

Resolves [#2](https://github.com/JLay2026/partsmith/issues/2).
First v0.3.0 Theme 1 (author ergonomics) item to ship.

### Commit
See [`HEAD`](https://github.com/JLay2026/partsmith/commits/main).

---

## [0.2.3] — 2026-06-09

### Changed
- **MCP transport switched to stateless + json_response mode.** FastMCP's
  default stateful mode keeps a long-poll `GET /mcp/` stream open and
  pushes tool responses to that stream rather than the originating POST
  response. Strict-spec MCP clients (Cowork's managed UI specifically)
  hang for 2-17 minutes on every tool call because they don't multiplex
  POST-response + GET-stream events the way FastMCP expects.
  Stateless + json_response collapses every MCP call to a single POST
  with the response in the body as `application/json`. partsmith's
  tools are all request/response (no streaming) so this loses nothing
  and gains compatibility.

### Verified
- End-to-end through Cowork managed MCP UI 2026-06-09 (first real
  workload — Woodpeckers wall mount STL — designed, exported, printed).

### Commit
[`0a2c238`](https://github.com/JLay2026/partsmith/commit/0a2c23813a94fa8e0caf8c0f8965305711429781)

---

## [0.2.2] — 2026-06-09

### Fixed
- **DNS rebinding protection disabled on the /mcp transport.** FastMCP's
  `TransportSecuritySettings` defaults to
  `enable_dns_rebinding_protection=True` with an empty `allowed_hosts`,
  which rejects any `Host:` header that isn't `localhost`/`127.0.0.1`
  with `421 Misdirected Request: Invalid Host header`. Discovered when
  the v0.2.1 deploy returned 421 for every `https://cad.<host>/mcp/`
  request. DNS rebinding is a browser attack; partsmith's MCP endpoint
  is for AI agents and the threat model is perimeter-based
  (`SECURITY.md`), so the protection is out of scope.

### Commit
[`07883e7`](https://github.com/JLay2026/partsmith/commit/07883e7e3f94bde2f4e0eb316888782b9f1b9ad2)

---

## [0.2.1] — 2026-06-09

### Fixed
- **MCP lifespan integration.** FastMCP's `StreamableHTTPSessionManager`
  must run inside an async context manager (`async with sm.run(): ...`).
  FastAPI's `lifespan` kwarg does **not** propagate to sub-apps mounted
  via `app.mount()`. v0.2.0 mounted the MCP ASGI app via `app.mount("/mcp", ...)`
  without wiring the lifespan, so every MCP request crashed with
  `RuntimeError: Task group is not initialized. Make sure to use run().`
  Now: build the FastMCP server first, call `streamable_http_app()` to
  lazily init the session manager, wire `session_manager.run()` into
  the FastAPI lifespan, then construct the FastAPI app with that
  lifespan.
- **Clean `/mcp/` URL.** FastMCP's `streamable_http_path` defaults to
  `/mcp`. Combined with our outer `app.mount("/mcp", ...)` on FastAPI,
  the public URL became the awkward `/mcp/mcp/` (and `/mcp/` 404'd).
  Now: explicitly set `_mcp_server.settings.streamable_http_path = "/"`
  before calling `streamable_http_app()` so the combined URL is just
  `/mcp/`.
- **uvicorn `--proxy-headers --forwarded-allow-ips "*"`.** Without
  these flags, uvicorn ignores `X-Forwarded-Proto` from a reverse proxy
  whose source IP isn't `127.0.0.1`. For a containerized partsmith
  behind Caddy on a separate container, Caddy's source IP is whatever
  the docker network assigned it (e.g. `172.x.x.x`) — NOT 127.0.0.1.
  Result before this fix: redirects came back with `Location:
  http://...` instead of `https://...`, breaking clients that don't
  follow scheme-downgrade redirects.

### Commit
[`0f6a57f`](https://github.com/JLay2026/partsmith/commit/0f6a57f6e08ee99a3a94201d9c237bd6072c571d)

---

## [0.2.0] — 2026-06-09

### Added
- **FastMCP Streamable-HTTP transport mounted at `/mcp`.** Ten tools
  prefixed `partsmith_*` (health, create_model, modify_model,
  list_models, measure_model, render_3d, render_2d, render_multiview,
  export, analyze_printability). Shares the same in-process `CADEngine`
  as the REST endpoints so state is consistent across protocols.
- **`GET /workspace/{filename}` endpoint** for the MCP large-file
  URL-pointer fallback. Files > 8 MiB skip the inline base64 path and
  return a `url_path` the client fetches via this endpoint. Strict
  allowlist on filename (`[a-zA-Z0-9_-]+\.(stl|step|3mf)`) as defense
  in depth against path traversal.

### Removed
- **`cad-agent-shim` dependency.** URL-based MCP clients (Cowork's
  managed MCP UI, Claude Code, etc.) can now drive partsmith directly
  via the `/mcp` endpoint. The shim is deprecated; see
  [JLay2026/cad-agent-shim](https://github.com/JLay2026/cad-agent-shim)
  (archived 2026-06-09).

### Note
This release introduced bugs fixed in v0.2.1/v0.2.2/v0.2.3 (lifespan,
URL prefix, scheme downgrade, DNS rebinding, stateful-mode hang). The
first genuinely working `/mcp` end-to-end release is v0.2.3.

### Commit
[`6fad5db`](https://github.com/JLay2026/partsmith/commit/6fad5dbb181642175962d24295eec80c8eb7d12d)

---

## [0.1.3] — 2026-06-08

### Fixed
- **All disk-write paths catch `OSError` and surface meaningful 500s.**
  Previously a bind-mount permission mismatch (workspace/ or renders/
  on the host owned by `root:root` instead of `1000:1000`) produced a
  bare "Internal Server Error" with no clue what was wrong. Now the
  500 names the path and the expected uid so the fix is obvious from
  the error alone.

### Added
- README "First-time deploy" section calling out the chown step
  explicitly so first-time deployers don't trip on it.

### Commit
[`83a4a65`](https://github.com/JLay2026/partsmith/commit/83a4a65d11712d60de34b391031cb6c45cc2e6a3)

---

## [0.1.2] — 2026-06-08

### Fixed
- **Docker container port-publishing routing.** Removed `internal: true`
  from the compose network; with it set, the container's healthcheck
  passed but `curl http://127.0.0.1:8123/health` from the host got
  connection-refused depending on Docker version.

---

## [0.1.1] — 2026-06-08

### Added
- Per-face Lambertian shading in the 3D renderer (`renderer.py`).
  Cubes look like cubes; geometry has depth cues; not photorealistic
  but much better than the flat shading of v0.1.0.

---

## [0.1.0] — 2026-06-08

### Added
- Initial release. FastAPI server with the following REST endpoints:
  - `GET /health`
  - `POST /model/create` — execute build123d code, register as named model
  - `POST /model/modify`
  - `GET /model/list`
  - `GET /model/{name}/measure`
  - `POST /render/3d`, `/render/2d`, `/render/multiview`, `/render/all`
  - `POST /export` (STL / STEP / 3MF)
  - `POST /analyze/printability`
- Pydantic Field-pattern validation on model names (path traversal
  defense).
- Custom middleware rejecting request bodies above 1 MiB
  (`MAX_REQUEST_BYTES`).
- Container hardening: non-root uid 1000, `cap_drop: ALL`,
  `no-new-privileges`, `mem_limit: 4g`, `cpus: 2.0`, port published to
  `127.0.0.1:8123` (loopback).
- MIT license, SPDX headers on every source file, `SECURITY.md` with
  explicit threat model ("no sandbox theatre — perimeter is the
  boundary").
- ~500 LOC across `src/server.py`, `src/cad_engine.py`,
  `src/renderer.py`, `src/printability.py`.

### Why partsmith exists

Replaces the abandoned `Svetlana-DAO-LLC/cad-agent` which shipped a
literal `SyntaxError` in its main file four months prior and nobody
noticed. Rather than maintain a long-term patched fork, the wrapped
surface was small enough (~500 LOC) to clean-room rewrite. See
[`NOTICE.md`](NOTICE.md) for credit to prior work that informed
endpoint shapes.
