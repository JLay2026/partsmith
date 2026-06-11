# Changelog

All notable changes to [JLay2026/partsmith](https://github.com/JLay2026/partsmith).
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project follows semver-ish conventions (see [`ROADMAP.md`](ROADMAP.md)).

## [0.2.6] — 2026-06-10

### Added
- **`src/renderer.py:render_section()`** — 2D cross-section through a
  build123d Shape on the XY/XZ/YZ planes at a given `at` offset (mm).
  Uses `trimesh.Trimesh.section()` for the mesh-plane intersection;
  manual axis projection (not `Path3D.to_planar()`) so the 2D axes
  stay aligned with user expectations (Y→horizontal, Z→vertical for
  the default YZ plane, etc.).
- **`POST /render/section`** REST endpoint. Request:
  `{"name": "...", "plane": "YZ"|"XZ"|"XY", "at": 0.0, "with_dimensions": true}`.
  Returns `{"path": ..., "plane": ..., "at": ..., "base64": ...}`.
- **`partsmith_render_section`** MCP tool with detailed plane-convention
  docstring (LLM-readable so the tool selects appropriate `at` values).
- **`tests/test_section.py`** — signature/contract tests
  (4 tests): render_section signature, plane-string validation,
  SECTION_PLANES table consistency, SectionRequest pydantic schema.

### Design notes
- **Outline-only sections in v0.2.6.** Filled material rendering (via
  shapely polygons from `Path2D.polygons_full`) deferred to a possible
  v0.2.7 — wanted to ship the highest-leverage piece (visibility into
  internal geometry) first; aesthetic fill comes once we see what real
  designs need.
- **No-intersection placeholder, not 500.** When `at` is outside the
  geometry's bbox along the plane's normal, returns a PNG with the
  valid range so the LLM can self-correct. Same for degenerate
  tangent-to-face sections.
- **Manual axis projection** instead of `trimesh.Path3D.to_planar()` to
  avoid rotation-matrix surprises that would mismatch axis labels
  ("X (mm)" but actually plotting Y, etc.).
- **`SECTION_PLANES` table** as single source of truth for plane defs;
  any future plane (e.g. arbitrary diagonal) plugs in here. Validated
  for internal consistency by `test_section_planes_constant_complete`.

### Why
Per ROADMAP Theme 2 (output fidelity) — current iso renders confirm
"not garbage" but you can't tell whether wall thickness, screw hole
position, or fillet radius is right. Cross-sections close that gap
inline in the chat (no STL export + Bambu Studio round-trip).

Ranked highest of all open backlog items for in-line viz impact in the
"what improves iterative design + viz" review on 2026-06-10 after the
v0.2.5 ship.

Resolves [#8](https://github.com/JLay2026/partsmith/issues/8).
Third v0.3.0-era item to ship (after #2 design store in v0.2.4 and
#1 helpers in v0.2.5).

### Commit
See [`HEAD`](https://github.com/JLay2026/partsmith/commits/main).

---

## [0.2.5] — 2026-06-10

### Added
- **`src/partsmith_helpers.py`** — reusable build123d patterns,
  auto-injected into the build123d execution namespace by
  `CADEngine.execute_code`. Seven helpers shipped:
  - **Hole helpers:** `through_hole(diameter, depth)`,
    `screw_hole(diameter, depth, countersink=True, head_diameter=None,
    countersink_angle=90)`, `hex_hole(across_flats, depth)`
  - **Slot helper:** `slot(length, width, depth)` — stadium-shaped
  - **Edge treatment:** `chamfer_edges(part, radius, edges='all')`,
    `fillet_top_edges(part, radius)`
  - **Pattern helper:** `screw_pattern(positions, hole_func)`
- **`tests/test_helpers.py`** — lightweight smoke tests for helper
  surface.

### Why
Author ergonomics is the highest-leverage v0.3 theme. Reduces
boilerplate for common 3D-printing patterns.

Resolves [#1](https://github.com/JLay2026/partsmith/issues/1).

### Commit
See [`HEAD`](https://github.com/JLay2026/partsmith/commits/main).

---

## [0.2.4] — 2026-06-09

### Added
- **Persistent design store** (`src/design_store.py`). Designs are
  saved to disk under `{workspace}/designs/` as `{name}.py` (source) +
  `{name}.json` (metadata). Survive container restart; models are
  still in-memory only.
- **4 new MCP tools:** `partsmith_save_design`, `partsmith_load_design`,
  `partsmith_list_designs`, `partsmith_delete_design`.
- **5 new REST endpoints** under `/design/...`.

Resolves [#2](https://github.com/JLay2026/partsmith/issues/2).

### Commit
See [`HEAD`](https://github.com/JLay2026/partsmith/commits/main).

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
- **DNS rebinding protection disabled on the /mcp transport.** Was
  rejecting any non-localhost Host header with 421.

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
- **All disk-write paths catch `OSError` and surface meaningful 500s**
  with the affected path + the expected uid for the chown fix.

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
