# Changelog

All notable changes to [JLay2026/partsmith](https://github.com/JLay2026/partsmith).
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project follows semver-ish conventions (see [`ROADMAP.md`](ROADMAP.md)).

## [0.2.7] — 2026-06-10

### Added
- **Versioned designs.** Each design is now a directory of versions
  (`{workspace}/designs/{name}/v1.py + v1.json`, `v2.py + v2.json`, ...)
  instead of a single overwrite-in-place pair. Iteration produces a
  v1/v2/v3 trail you can compare.
- **`partsmith_list_versions(name)`** MCP tool + `GET /design/{name}/versions`
  REST endpoint — returns the sorted version list for a design.
- **`partsmith_diff_designs(name, v1, v2)`** MCP tool + `GET /design/{name}/diff`
  REST endpoint. Returns:
  - `source_diff`: unified diff text (3 lines of context)
  - `volume_delta_mm3`: v2 - v1 (or null if either side lacks geometry)
  - `surface_area_delta_mm2`: v2 - v1
  - `bbox_size_delta_mm`: `[dx, dy, dz]` (v2 size - v1 size)
  - `v1_metadata`, `v2_metadata`: full metadata dicts
- **`version` parameter** on existing tools/endpoints:
  - `partsmith_save_design(..., version="auto"|int)` — "auto" appends
    next unused; int targets that slot (overwrites)
  - `partsmith_load_design(..., version=None)` — None / unset = latest
  - `partsmith_delete_design(..., version=None)` — None nukes all
    versions + directory; int deletes just that version
  - `POST /design/save` body accepts `version`; `GET /design/{name}`,
    `DELETE /design/{name}`, `POST /design/{name}/load` accept
    `?version=N` query param.
- **`tests/test_versioning.py`** — 15 end-to-end tests covering save,
  load, delete (per-version + all-versions), diff (source + geometry
  deltas), list_all (latest-per-design), legacy layout read compat,
  legacy auto-migration on first save, REST schema, error paths.

### Backward compatibility
- **Pre-v0.2.7 flat layout** (`designs/{name}.py + {name}.json`) is read
  transparently as version 1. `list_versions("legacy_design")` returns
  `[1]`, `load("legacy_design")` returns the legacy code.
- **Auto-migration on next save.** When you save to a legacy design,
  the flat files are moved to `designs/{name}/v1.py + v1.json`
  (preserving created_at) and the new code lands as v2. Migration
  happens once per design, in-place, with no data loss.
- All existing v0.2.4-v0.2.6 callers (REST + MCP) work unchanged because
  the new `version` params have backward-compatible defaults.

### Design notes
- **One directory per design.** Originally considered packing all
  versions into one JSON file but rejected: source `.py` files stay
  human-readable + grep-friendly + git-friendly that way.
- **Explicit-version save overwrites.** No "version already exists,
  refuse" — overwriting an existing version is a deliberate user
  choice ("redo v3 cleanly"). Use auto for normal appending.
- **created_at preserved on overwrite.** Even when you overwrite a
  specific version slot, its original created_at is kept; only
  last_modified bumps. So design history isn't lost by a re-save.
- **Diff is geometry-aware but optional.** Deltas come from the
  geometry snapshot saved at save time. If either version was saved
  without geometry (or with corrupt metadata), deltas come back as
  null with no error — the source diff is always available.
- **Side-by-side render NOT in this PR.** Issue #3 lists "optional:
  side-by-side render PNG" — deferring to v0.2.8 once we see whether
  the metadata-delta approach is sufficient signal in real iteration.
- **Triangle count NOT in delta.** Not currently captured in the
  geometry snapshot. Adding it would require a measure() pass at save
  time — out of scope, may add in v0.2.8 with side-by-side render.

### Why
"Is v3 actually better than v2 in the ways I care about?" requires
side-by-side comparison. Without versioning every `create_model` clobbered
prior work. With this, iteration becomes a tracked trail; geometry
deltas give an at-a-glance answer ("v3 is 12% smaller volume, 0.5mm
narrower in X — that's what I wanted").

Resolves [#3](https://github.com/JLay2026/partsmith/issues/3).
Fourth v0.3.0-era item to ship (after #2 design store in v0.2.4,
#1 helpers in v0.2.5, #8 cross-section in v0.2.6).

### Commit
See [`HEAD`](https://github.com/JLay2026/partsmith/commits/main).

---

## [0.2.6] — 2026-06-10

### Added
- **`src/renderer.py:render_section()`** — 2D cross-section through a
  build123d Shape on the XY/XZ/YZ planes at a given `at` offset (mm).
- **`POST /render/section`** REST endpoint + **`partsmith_render_section`**
  MCP tool.
- **`tests/test_section.py`** — signature/contract tests.

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
