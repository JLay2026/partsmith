# Changelog

All notable changes to [JLay2026/partsmith](https://github.com/JLay2026/partsmith).
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project follows semver-ish conventions (see [`ROADMAP.md`](ROADMAP.md)).

## [0.3.6] — 2026-06-12

### Changed
- **`create_model` / `modify_model` / `load_design` preview is now
  opt-in** (`src/mcp_transport.py` `_do_create`). New `include_preview`
  parameter, **default `False`**. Previously every create/modify/load
  unconditionally embedded a full 800×600 iso PNG as inline base64
  (~75–150 KB → ~25 K+ tokens), which overflowed the calling client's
  response token budget on every call. Default responses are now just
  `success` + `geometry` + `stdout` (tiny).
- **When requested, the preview is downscaled + capped.** Rendered at
  384×288 and gated behind `PARTSMITH_PREVIEW_INLINE_MAX` (default
  48 KB); if it still exceeds the cap the bytes are dropped and a
  `preview_note` points the caller at `partsmith_render_3d`. Inline
  previews now carry `preview_size_bytes` + `preview_sha256` for parity
  with the v0.3.5 file-delivery contract.

### Added
- **`tests/integration/test_mcp_tools.py::test_create_model_preview_optional`**
  — asserts a default create carries no `preview_data_b64`, and that
  `include_preview=True` yields either a capped, sha-verifiable inline
  preview or a `preview_note` (never an unbounded raw embed). The
  existing round-trip test now asserts the default-no-preview contract.

### Migration note
This changes the default MCP create/modify/load response shape:
`preview_data_b64` no longer appears unless `include_preview=True`.
Callers that relied on the auto-preview should either pass
`include_preview=True` or call `partsmith_render_3d` explicitly. REST
`create_model` is unchanged (HTTP clients aren't subject to the chat
token cap).

### Why
The auto-preview was the last unbounded inline payload after #18 made
exports verifiable. It provided little value (most creates are followed
by `measure` or an explicit render) at the cost of overflowing every
create response. Default-off makes `create_model` lightweight and
predictable. Per ROADMAP Theme 4 (validated quality).

Resolves [#20](https://github.com/JLay2026/partsmith/issues/20).

### Commit
See [`HEAD`](https://github.com/JLay2026/partsmith/commits/main).

---

## [0.3.5] — 2026-06-12

### Added
- **Integrity metadata on every MCP file response** (`src/mcp_transport.py`
  `_file_response`). Every export/render now returns `sha256` and
  `size_bytes`, so the calling client can verify the bytes it writes to
  disk (`len == size_bytes` and `sha256` match). This converts a silent
  truncation — e.g. a shell-heredoc write that got cut off mid-paste —
  into a caught, retryable error. stdlib `hashlib`, no new dependency.
- **`url_path` advertised for all workspace-servable exports** (stl/step/3mf),
  not just files over the 8 MiB inline cap. `engine.export()` already
  persists to the workspace and `GET /workspace/{filename}` already
  serves it; this just surfaces the transcription-free fetch path on
  every export. Render PNGs are not workspace-persisted, so they
  correctly **omit** `url_path` and stay inline.
- **`integrity_note` on inline payloads + a rewritten `partsmith_export`
  docstring** instructing the caller: decode → write bytes → verify;
  materialize with a real binary write (`base64 -d` / `open(p,'wb')`);
  **never** paste base64 through a shell heredoc/echo (truncates
  silently); on mismatch, re-call rather than keep a partial file.
- **`tests/integration/test_mcp_tools.py::test_export_integrity_metadata`**
  — asserts the returned `sha256`/`size_bytes` actually match the decoded
  bytes and that an stl export advertises the correct `url_path`. The
  section test now also asserts render PNGs carry **no** `url_path`.

### Design notes
- **Server makes corruption *detectable*; it can't make the client's
  write correct.** The fix is a verifiable contract (sha + size) plus a
  fetch fallback, not an attempt to control how the client materializes
  bytes. Highest-leverage, smallest change.
- **Scope held tight.** An `inline: bool` flag, a metadata-only export
  variant, and extending fetchable artifacts to renders (which would
  need the renders dir served + PNG added to the workspace allow-list,
  relevant to the heavy-inline-preview token-cap issue) are all
  deferred until the inline path proves insufficient — per "earn the
  feature with real demand."

### Why
Triggered by a real incident: a ~2.3 KB lid STL exported fine
server-side but the client wrote the inline base64 via a shell heredoc
that truncated, leaving a missing/corrupt file with no error surfaced.
partsmith now ships the metadata to catch exactly that. Per ROADMAP
Theme 4 (validated quality).

Resolves [#18](https://github.com/JLay2026/partsmith/issues/18).

### Commit
See [`HEAD`](https://github.com/JLay2026/partsmith/commits/main).

---

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

### Why
v0.3.1 shipped the CI framework + transport/inventory tests but
deferred the two heavier tests to keep that ship tight. Completing the
suite now means real tool execution + proxy-header handling are both
under regression guard before Theme 2 (output fidelity) work begins.

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
- **`.github/workflows/integration.yml`.** New separate workflow that
  builds the partsmith image, starts the container on 127.0.0.1:8123,
  waits for `/health`, and runs `tests/integration/` with
  `PARTSMITH_URL` set.
- **`tests/integration/`** suite (scaffold + 3 tests): `conftest.py`
  (`partsmith_url` fixture; skips if unset), `test_health.py`,
  `test_mcp_handshake.py` (initialize + tool inventory).
- **`requests>=2.28.0`** dev dependency for the integration HTTP client.

### Why
v0.2.x shipped four deploy bugs (lifespan, double-prefix path, scheme
downgrade, DNS rebinding) that a container-based integration test would
have caught in 5 minutes. This is the boring defensive layer that
protects every future feature ship. Per ROADMAP Theme 4.

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
