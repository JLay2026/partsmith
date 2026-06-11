# Changelog

All notable changes to [JLay2026/partsmith](https://github.com/JLay2026/partsmith).
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project follows semver-ish conventions (see [`ROADMAP.md`](ROADMAP.md)).

## [0.3.4] — 2026-06-11

### Added
- **Dimensioned engineering drawings** (`src/renderer.py`
  `render_drawing()`). A new render that draws proper overall
  **width + height dimension lines** — extension lines, double-headed
  arrows, and the measured value centered on each — plus a **title
  block** (part name, view, units, scale, date). Answers "is this
  bracket actually 50 mm wide?" from the render, before slicing.
- **`POST /render/drawing`** REST endpoint + **`partsmith_render_drawing`**
  MCP tool (`name`, `view`, `part_name`). The existing `render_2d`
  plain W/H text overlay is unchanged — this is a separate, richer tool.
- **`tests/integration/test_mcp_tools.py::test_render_drawing_via_mcp`**
  — drives the new tool end-to-end against the real container and
  asserts a valid PNG. Tool-surface check in `test_mcp_handshake.py`
  extended to require `partsmith_render_drawing`.

### Design notes
- **New tool, not a mode flag.** Per the issue's lean, drawings are a
  dedicated `render_drawing` rather than a `with_dimensions="engineering"`
  mode on `render_2d`, so the simple overlay stays available and the
  two concerns don't entangle.
- **Overall dims only in v0.3.4.** Feature callouts (hole diameters,
  center-to-center spacing) are deferred: reliable circle detection
  from a *triangulated mesh* is the risky part, and per "earn the
  feature with real demand" it waits until a real design needs it.
  Overall W/H covers the 90% "did I get the size right" check.
- **Dimension drawing is pure 2D matplotlib** operating on the
  projected bbox extents (`_draw_overall_dimensions`), so it's
  view-agnostic and was unit-validated against synthetic geometry
  before wiring to the CAD stack. No new dependency.

### Why
Sprint A / Theme 2 (output fidelity). Cross-sections (v0.2.6/v0.3.3)
let you see *inside* a part; dimensioned drawings let you verify its
*size*. Together they close the "looks right but is it right" gap
before a print is committed.

Resolves [#12](https://github.com/JLay2026/partsmith/issues/12).

### Commit
See [`HEAD`](https://github.com/JLay2026/partsmith/commits/main).

---

## [0.3.3] — 2026-06-11

### Added
- **Filled cross-sections** (`src/renderer.py`). `render_section()` now
  shades the cut material (translucent fill) under the section outline
  so solid vs. void reads at a glance — the whole point of looking at a
  section. Drawn from the slice's discrete closed loops, projected to
  the same 2D frame as the outline. Holes (e.g. a tube bore) are marked
  by their outline and read as lighter regions.
- **Topology-complexity deltas in `partsmith_diff_designs`** /
  `GET /design/{name}/diff` (`src/design_store.py`). The diff now
  reports `face_count_delta`, `edge_count_delta`, and
  `vertex_count_delta` alongside the existing volume / surface-area /
  bbox deltas. A positive `face_count_delta` means v2 is structurally
  more complex than v1 (added bosses, holes, fillets…).
- **Topology counts in the geometry snapshot** (`src/cad_engine.py`).
  `ModelState.to_summary()` now includes `face_count` / `edge_count` /
  `vertex_count`, so every saved design version persists them and the
  diff above has data to work with. Also enriches `/model/list` and
  create/modify responses.
- **`tests/test_versioning.py`** — 2 new pure-stdlib tests:
  `test_diff_topology_deltas` (counts subtract correctly) and
  `test_diff_topology_deltas_missing` (None-safe when a pre-v0.3.3
  version lacks counts). Existing missing-geometry test extended to
  assert the new fields are None-safe too.

### Design notes
- **B-rep counts, not mesh triangles.** Issue #13 framed this as a
  "triangle-count delta", but mesh triangle counts depend on
  tessellation tolerance — the same design would diff non-reproducibly.
  B-rep `shape.faces()/edges()/vertices()` counts are deterministic and
  a truer signal of "did the part get more complex", so that's what
  ships. They're also free (already computed by `measure()`).
- **Single source of truth for the snapshot.** The counts are added in
  `to_summary()` rather than duplicated across the REST and MCP save
  handlers, so both protocols inherit them with no per-handler code.
- **Fill is best-effort.** Any failure in the fill path is caught and
  the render degrades to the v0.2.6 outline-only behavior rather than
  erroring. The outline is always truth; the fill is a visual aid.

### Why
Sprint A / Theme 2 (output fidelity). A section you can't tell solid
from void in is only half a section; a diff that says "the source
changed" without "and it got 3 faces more complex" makes the reviewer
do the geometry math in their head. Both close that gap.

Resolves [#13](https://github.com/JLay2026/partsmith/issues/13).

### Commit
See [`HEAD`](https://github.com/JLay2026/partsmith/commits/main).

---

## [0.3.2] — 2026-06-11

### Added
- **`tests/integration/test_mcp_tools.py`** — full MCP tool-call
  round-trip (the deferred half of #5):
  - `test_create_model_then_export_roundtrip` — initialize → call
    `partsmith_create_model` with a 20 mm cube → assert
    `success` + geometry (8000 mm³, 20×20×20 bbox) + a real PNG in
    `preview_data_b64` → call `partsmith_export` (STL) → assert the
    returned base64 decodes to valid STL bytes.
  - `test_render_section_via_mcp` — proves the v0.2.6 cross-section
    tool executes against the real trimesh stack in the container and
    returns an inline PNG.
  - `_tool_result_dict()` helper parses the FastMCP tools/call response
    defensively (`structuredContent` or `content[0].text` JSON) so the
    tests aren't coupled to one FastMCP wrapping.
- **`tests/integration/test_caddy_compat.py`** — reverse-proxy header
  compatibility (the other deferred half of #5):
  - `test_forwarded_headers_accepted` — `/health` with
    `X-Forwarded-Proto/-For/-Host` returns 200 (proves
    `--forwarded-allow-ips` parses rather than rejects the headers).
  - `test_redirect_preserves_https_scheme` — GET `/mcp` (no trailing
    slash) under `X-Forwarded-Proto: https` must redirect to an
    `https://` Location, directly guarding the v0.2.1 scheme-downgrade
    regression. Skips (rather than false-fails) if the build doesn't
    redirect that path or emits a relative Location — the regression
    only manifests as an absolute `http://` Location.

### Completes
Issue [#5](https://github.com/JLay2026/partsmith/issues/5) is now fully
delivered: all four originally-scoped integration test files exist
(`test_health`, `test_mcp_handshake` in v0.3.1; `test_mcp_tools`,
`test_caddy_compat` here). The integration workflow now exercises the
transport, the tool inventory, real tool execution, and proxy-header
handling on every PR.

### Design notes
- **Defensive result parsing.** FastMCP's exact tools/call response
  shape (structuredContent vs. content[0].text) varies by version;
  `_tool_result_dict()` handles both so a FastMCP bump doesn't
  spuriously break the round-trip test.
- **Conditional skip on the scheme test.** The slash-redirect behavior
  is server/version-dependent; the test guards the regression when the
  redirect exists and skips cleanly otherwise rather than asserting on
  behavior that may not be present. The baseline
  `test_forwarded_headers_accepted` always runs.
- **Still no new runtime deps.** Tests use `requests` (already a dev
  dep since v0.3.1). The integration container has the full stack;
  these tests just drive it over HTTP.

### Why
v0.3.1 shipped the CI framework + transport/inventory tests but
deferred the two heavier tests to keep that ship tight. With the
framework proven green across the v0.3.1 merge, completing the suite
now means real tool execution + proxy-header handling are both under
regression guard before Theme 2 (output fidelity) work begins.

Per ROADMAP Theme 4 ("Validated quality").

### Commit
See [`HEAD`](https://github.com/JLay2026/partsmith/commits/main).

---

## [0.3.1] — 2026-06-10

### Added
- **`pytest` job in `.github/workflows/ci.yml`.** Runs lightweight
  tests (`tests/test_versioning.py`) on every PR + push to main.
  Installs only `pytest + fastapi + pydantic` (~10 sec); tests that
  need build123d / trimesh / matplotlib run against the real container
  via the integration workflow instead.
- **`.github/workflows/integration.yml`.** New separate workflow that:
  1. Builds the partsmith image from the current branch (Buildx +
     GH Actions cache; ~30 sec on warm cache, ~5 min first time)
  2. Starts the container on 127.0.0.1:8123, waits up to 90s for
     `/health` to return 200
  3. Runs `pytest tests/integration/` with `PARTSMITH_URL` set
  4. Dumps `docker logs partsmith` on failure for diagnosis
- **`tests/integration/`** suite (initial scaffold + 3 tests):
  - `conftest.py` — `partsmith_url` fixture; skips if
    `PARTSMITH_URL` env unset so local pytest discovery is harmless
  - `test_health.py:test_health_returns_200_with_version` — REST
    `/health` smoke. Catches v0.1.2-class deploy regressions
    (port-bind failure, FastAPI lifespan crash, etc.)
  - `test_mcp_handshake.py:test_mcp_initialize_returns_partsmith_serverinfo`
    — POST `/mcp/` initialize. Catches v0.2.1 (lifespan / URL prefix),
    v0.2.2 (DNS rebinding 421), v0.2.3 (stateful long-poll hang)
    regressions
  - `test_mcp_handshake.py:test_mcp_tools_list_includes_expected_surface`
    — verifies the full v0.2.0 + v0.2.4 + v0.2.6 + v0.2.7 tool surface
    is exposed; banded by version cohort so a missing tool is a clear
    signal of which release regressed
- **`requests>=2.28.0`** dev dependency for integration test HTTP client.

### Deferred to a future patch (v0.3.2 or later)
Issue [#5](https://github.com/JLay2026/partsmith/issues/5) originally
scoped four integration test files. Shipped 2/4 here; the other 2 land
as a follow-up once this framework has proven stable in CI for a week
or two of actual PRs:

- `test_mcp_tools.py` — full round-trip: initialize → call
  `partsmith_create_model` with a cube → verify success + geometry +
  preview_data_b64 → call `partsmith_export` → verify STL bytes
  decodable. Higher complexity (chain of MCP tool calls), value is
  important but deferred to keep the v0.3.1 ship surface tight.
- `test_caddy_compat.py` — verify uvicorn handles `X-Forwarded-Proto:
  https` correctly. Catches the v0.2.1 scheme-downgrade regression.
  Easy to add but separate concern.

### Design notes
- **Two workflows, not one.** Lightweight CI (ruff + pytest) runs in
  ~30 sec and gates every PR. Integration runs in 1-5 min and runs
  alongside but doesn't block. Separation means a build123d API drift
  doesn't sneak in just because pip cache went stale.
- **`PARTSMITH_URL` env var, not testcontainers-python.** The
  `testcontainers` library adds a dep, complicates local dev, and
  doesn't materially simplify the CI workflow over plain
  `docker run + curl + pytest`. Skipped per the project's
  "small over capable" toolkit preference.
- **Local-dev story preserved.** `conftest.py` skips if
  `PARTSMITH_URL` is unset, so `pytest tests/integration/ -v` on a
  laptop without a running container just says "skipped". Run with
  `PARTSMITH_URL=http://127.0.0.1:8123 pytest tests/integration/ -v`
  against a local container to validate before pushing.
- **GH Actions cache for Docker layers.** `cache-from / cache-to type=gha`
  on the buildx step means subsequent runs reuse the OpenCASCADE Python
  wheel layer (the expensive part). First-PR build is ~5 min; rebuilds
  on the same branch are ~30 sec.

### Why
v0.2.x shipped four deploy bugs (lifespan, double-prefix path, scheme
downgrade, DNS rebinding) that would have been caught in 5 minutes by a
container-based integration test. Cost was ~5 hours of evening debugging
across the v0.2.0 → v0.2.3 cycle. This is the boring defensive layer
that protects every future feature ship.

Resolves the immediate ask of [#5](https://github.com/JLay2026/partsmith/issues/5)
(pytest integration suite + GH Actions CI workflow exist + run on every
PR). Two integration tests remain to land in a follow-up.

Per ROADMAP Theme 4 ("Validated quality"). Fifth v0.3.x item to ship,
and the one that protects investment in everything else.

### Commit
See [`HEAD`](https://github.com/JLay2026/partsmith/commits/main).

---

## [0.2.7] — 2026-06-10

### Added
- **Versioned designs.** Each design is now a directory of versions
  (`{workspace}/designs/{name}/v1.py + v1.json`, `v2.py + v2.json`, ...)
  instead of a single overwrite-in-place pair.
- **`partsmith_list_versions(name)`** MCP tool + `GET /design/{name}/versions`
- **`partsmith_diff_designs(name, v1, v2)`** MCP tool + `GET /design/{name}/diff`
  — returns source diff + volume/surface-area/bbox deltas
- **`version` parameter** on existing save/load/delete tools/endpoints
- **`tests/test_versioning.py`** — 15 end-to-end tests
- Backward-compatible with v0.2.4-v0.2.6 flat layout (auto-migrates
  on first save)

Resolves [#3](https://github.com/JLay2026/partsmith/issues/3).

### Commit
See [`HEAD`](https://github.com/JLay2026/partsmith/commits/main).

---

## [0.2.6] — 2026-06-10

### Added
- **`src/renderer.py:render_section()`** — 2D cross-section through a
  build123d Shape on the XY/XZ/YZ planes.
- **`POST /render/section`** REST endpoint + **`partsmith_render_section`**
  MCP tool.

Resolves [#8](https://github.com/JLay2026/partsmith/issues/8).

### Commit
See [`HEAD`](https://github.com/JLay2026/partsmith/commits/main).

---

## [0.2.5] — 2026-06-10

### Added
- **`src/partsmith_helpers.py`** — 7 reusable build123d patterns
  (through_hole, screw_hole, hex_hole, slot, chamfer_edges,
  fillet_top_edges, screw_pattern) auto-injected into the build123d
  execution namespace.

Resolves [#1](https://github.com/JLay2026/partsmith/issues/1).

### Commit
See [`HEAD`](https://github.com/JLay2026/partsmith/commits/main).

---

## [0.2.4] — 2026-06-09

### Added
- **Persistent design store** (`src/design_store.py`). Flat layout:
  `{workspace}/designs/{name}.py + {name}.json`. Survives container
  restart.
- **4 new MCP tools:** `partsmith_save_design`, `partsmith_load_design`,
  `partsmith_list_designs`, `partsmith_delete_design`.
- **5 new REST endpoints** under `/design/...`.

Resolves [#2](https://github.com/JLay2026/partsmith/issues/2).

---

## [0.2.3] — 2026-06-09

### Changed
- **MCP transport switched to stateless + json_response mode.** Fixes
  the 2-17 min hang in Cowork's managed MCP UI caused by FastMCP's
  default stateful long-poll mode.

### Commit
[`0a2c238`](https://github.com/JLay2026/partsmith/commit/0a2c23813a94fa8e0caf8c0f8965305711429781)

---

## [0.2.2] — 2026-06-09

### Fixed
- **DNS rebinding protection disabled on the /mcp transport.**

### Commit
[`07883e7`](https://github.com/JLay2026/partsmith/commit/07883e7e3f94bde2f4e0eb316888782b9f1b9ad2)

---

## [0.2.1] — 2026-06-09

### Fixed
- **MCP lifespan integration** — FastMCP session manager wired into
  FastAPI lifespan; clean `/mcp/` URL via streamable_http_path="/";
  uvicorn `--proxy-headers` for behind-Caddy scheme handling.

### Commit
[`0f6a57f`](https://github.com/JLay2026/partsmith/commit/0f6a57f6e08ee99a3a94201d9c237bd6072c571d)

---

## [0.2.0] — 2026-06-09

### Added
- **FastMCP Streamable-HTTP transport at `/mcp`.** Ten tools prefixed
  `partsmith_*`. Shares the same in-process `CADEngine` as REST.
- **`GET /workspace/{filename}`** for MCP large-file URL pointer fallback.

### Removed
- **`cad-agent-shim`** — deprecated, archived 2026-06-09.

### Commit
[`6fad5db`](https://github.com/JLay2026/partsmith/commit/6fad5dbb181642175962d24295eec80c8eb7d12d)

---

## [0.1.3] — 2026-06-08

### Fixed
- **All disk-write paths catch `OSError` and surface meaningful 500s.**

### Commit
[`83a4a65`](https://github.com/JLay2026/partsmith/commit/83a4a65d11712d60de34b391031cb6c45cc2e6a3)

---

## [0.1.2] — 2026-06-08

### Fixed
- **Docker container port-publishing routing.** Removed `internal: true`
  from the compose network.

---

## [0.1.1] — 2026-06-08

### Added
- Per-face Lambertian shading in the 3D renderer.

---

## [0.1.0] — 2026-06-08

### Added
- Initial release. FastAPI server, build123d wrapper, matplotlib
  renderer, printability check, MIT license, perimeter security model.

### Why partsmith exists
Replaces the abandoned `Svetlana-DAO-LLC/cad-agent` which shipped a
literal `SyntaxError` in its main file four months prior and nobody
noticed. ~500 LOC clean-room rewrite.
