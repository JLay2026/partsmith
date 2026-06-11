# partsmith roadmap

Strategic direction for [JLay2026/partsmith](https://github.com/JLay2026/partsmith).
For past releases see [`CHANGELOG.md`](CHANGELOG.md). For tactical work in
flight see [the issues tracker](https://github.com/JLay2026/partsmith/issues).

**Last updated:** 2026-06-11 (post-v0.3.4 — Sprint A closed two Theme 2
items: cross-section fill + topology deltas v0.3.3, dimensioned drawings
v0.3.4. Renderer-swap spike remains).

---

## Status at a glance

| Theme | State |
|---|---|
| Theme 1 — Author ergonomics | ✅ Effectively complete (#1, #2, #3 shipped; #4 backlog) |
| Theme 2 — Output fidelity | 🟡 In progress (cross-section v0.2.6 + fill/deltas v0.3.3 + drawings v0.3.4 shipped; renderer swap remains) |
| Theme 3 — Print workflow | ⬜ Not started |
| Theme 4 — Validated quality | ✅ Complete (#5; full integration suite shipped v0.3.1 + v0.3.2) |
| Theme 5 — Operational (deploy) | ✅ ZimaOS Custom Install live; nut/ retrofit backlog |

---

## Design principles (preserved across the roadmap)

- **Small over capable.** Every feature has to justify its line count.
  The whole server is ~1,400 LOC and we'd like to keep it small enough
  that a new contributor can read it in an afternoon.
- **Perimeter is the security boundary.** No in-app auth, no sandboxing
  theatre, no multi-tenant. See [`SECURITY.md`](SECURITY.md).
- **REST + MCP parity.** What works on one works on the other; both
  layers share the same in-process `CADEngine` instance so state is
  consistent across protocols.
- **Deployment is part of the product.** Bugs that only appear behind
  a real reverse proxy with a real client (see CHANGELOG v0.2.x) are
  bugs we own. The v0.3.1 integration suite now catches them in CI.
- **Reuse the platform's native patterns.** ZimaOS provides Custom
  Install + x-casaos; we use it natively rather than inventing a
  parallel install flow.
- **Earn the feature with real demand.** New patterns (helpers,
  cookbook entries) get added when a real design has demanded them
  twice, not on speculation. See the cookbook (#4) deferral and the
  drawing feature-callout deferral (v0.3.4).

---

## Theme 1 — Author ergonomics (biggest impact on your time) ✅

You'll spend 80% of partsmith time writing build123d code. Anything
that compresses repeated patterns has outsized payoff. **This theme is
effectively complete** — the three shipped items cover the core
blank-page + iteration pain.

| Issue | Item | Status |
|---|---|---|
| [#1](https://github.com/JLay2026/partsmith/issues/1) | `partsmith_helpers` library (through_hole, screw_hole, hex_hole, slot, chamfer_edges, fillet_top_edges, screw_pattern) | ✅ Shipped v0.2.5 |
| [#2](https://github.com/JLay2026/partsmith/issues/2) | Persistent design store — save/load build123d source to disk; survives container restart | ✅ Shipped v0.2.4 |
| [#3](https://github.com/JLay2026/partsmith/issues/3) | Versioned designs + `partsmith_diff_designs(name, v1, v2)` | ✅ Shipped v0.2.7 |
| [#4](https://github.com/JLay2026/partsmith/issues/4) | Cookbook — `examples/` dir with starter designs | ⬜ **Backlog** (no real-design demand yet; revisit after 3-4 more prints) |

---

## Theme 2 — Output fidelity (compresses review cycles) 🟡

Current iso-view renders are "good enough to confirm not garbage" but
you can't tell from them whether wall thickness, screw hole position,
or fillet radius is right. Better outputs → fewer print failures.
**Cross-sections (v0.2.6), section fill + topology diffs (v0.3.3), and
dimensioned drawings (v0.3.4) have all shipped.** Only the renderer
swap remains, and it's a "may decline" spike.

| Issue | Item | What it gives you | Effort | Status |
|---|---|---|---|---|
| [#8](https://github.com/JLay2026/partsmith/issues/8) | Cross-sections — `partsmith_render_section(name, plane, at)` | See internal cavities, wall thickness, snap-fit clearances | M | ✅ Shipped v0.2.6 |
| [#13](https://github.com/JLay2026/partsmith/issues/13) | Cross-section fill + topology-complexity deltas | Solid material reads at a glance; richer version diffs | S-M | ✅ Shipped v0.3.3 |
| [#12](https://github.com/JLay2026/partsmith/issues/12) | Dimensioned 2D engineering drawings — `partsmith_render_drawing(name, view)` | Visual confirmation the bracket is 50 mm wide BEFORE printing | M | ✅ Shipped v0.3.4 |
| [#14](https://github.com/JLay2026/partsmith/issues/14) | VTK / trimesh-scene renderer swap | Photorealistic-ish previews where surface finish matters | M-L | ⬜ Spike — likely declined (bloats the slim container; see principle "small over capable") |
| — | Drawing feature callouts (hole Ø, c-to-c spacing) | Per-feature dims, not just overall W/H | M | ⬜ Deferred from v0.3.4 (needs reliable mesh circle detection; earn with real demand) |
| — | Multi-color preview — indicate AMS slot per face/body | Once you're using all 4 AMS slots for a part | L | ⬜ No issue yet |

**Target release:** Theme 2 substantially done at v0.3.4. File issues
when starting the renderer swap or feature callouts.

---

## Theme 3 — Print workflow integration (closes the loop to the X1C) ⬜

partsmith's job ends at the STL. Shrink the gap between "STL exists"
and "X1C is printing it."

| Item | What it gives you | Effort |
|---|---|---|
| 3MF with Bambu metadata (orientation, supports, AMS slot per body) | One fewer click in Bambu Studio per part | M |
| Pre-slicing analysis — estimated print time, material usage, overhang map, bed adhesion area, COM tipping risk | Catch "this needs supports + tree" before you slice | L |
| Optional: Bambu Connect / MQTT integration | Skip Bambu Studio for repeat prints | XL (out-of-tree candidate) |

**Target release:** v0.5.0 (core); Bambu Connect deferred to v0.6+ or
out-of-tree plugin.

---

## Theme 4 — Validated quality (prevents the next 5-hour debug) ✅

The four v0.2.x deploy bugs (see CHANGELOG) would have been caught by
integration tests against a containerized partsmith. **The full suite
now exists** (v0.3.1 framework + v0.3.2 completion) and runs on every PR.

| Issue | Item | Status |
|---|---|---|
| [#5](https://github.com/JLay2026/partsmith/issues/5) | pytest integration suite + GitHub Actions CI | ✅ Complete — framework v0.3.1, full suite v0.3.2 |

**Shipped:**
- `ci.yml` lightweight pytest job (ruff + `tests/test_versioning.py` on every PR, ~30s)
- `integration.yml` — builds the container, starts it, runs `tests/integration/` against `/health` + `/mcp/`
- Four integration files: `test_health`, `test_mcp_handshake` (v0.3.1);
  `test_mcp_tools` (create→export→section→drawing round-trips),
  `test_caddy_compat` (X-Forwarded-Proto scheme check) (v0.3.2+)
- Catches the v0.2.1/v0.2.2/v0.2.3 regression classes in a single MCP handshake test

---

## Theme 5 — Operational (deployment ergonomics) ✅

User-facing deploy story. Native ZimaOS Custom Install (env vars as
GUI form fields, install/update via dashboard) replaced the CLI gitops
flow that caused real friction. **Live on Box A as of 2026-06-09/10.**

| Item | Where it lives | Status |
|---|---|---|
| ZimaOS Custom Install (x-casaos compose) for partsmith | [zimaboard-services](https://github.com/JLay2026/zimaboard-services) PRs #6→#9 | ✅ Live; install verified on Box A |
| GHCR image publishing (release.yml) | this repo `.github/workflows/release.yml` | ✅ Shipped; `ghcr.io/jlay2026/partsmith` public |
| Docs rewrite — GUI install primary, CLI fallback | zimaboard-services PR #10 | ✅ Shipped |
| Placeholder partsmith icon (SVG, isometric cube) | [`assets/icon.svg`](assets/icon.svg) | ✅ Shipped 2026-06-09 |
| nut/ retrofit to same x-casaos pattern | zimaboard-services | ⬜ Backlog |

**Hard-won deploy lessons** (see zimaboard-services + CHANGELOG):
ZimaOS Custom Install rejects `${VAR:-default}` substitution in
volumes/env/ports — hardcode values; `build:` not supported — use a
published `image:`.

---

## Suggested release sequence

```
v0.2.4  ✅ Theme 1 #2 — persistent design store
v0.2.5  ✅ Theme 1 #1 — partsmith_helpers library
v0.2.6  ✅ Theme 2 #8 — cross-section renderer
v0.2.7  ✅ Theme 1 #3 — versioned designs + diff
v0.3.1  ✅ Theme 4 #5 — pytest CI + integration framework
        ✅ Theme 5    — ZimaOS Custom Install (zimaboard-services)
v0.3.2  ✅ Theme 4 #5 — integration suite completed (mcp_tools, caddy_compat)
v0.3.3  ✅ Theme 2 #13 — cross-section fill + topology deltas
v0.3.4  ✅ Theme 2 #12 — dimensioned drawings
---- you are here ----
v0.3.x  — Theme 2 #14 renderer-swap spike (likely declined) or feature callouts
v0.5.0  — Theme 3 (3MF metadata, pre-slicing analysis)
v0.6+   — Theme 3 cont. (Bambu Connect) or whatever real workloads surface
backlog — #4 cookbook (after more real prints); nut/ retrofit
v1.0    — when partsmith has been used in earnest for 6 months and
          no longer surfaces sharp edges
```

---

## What's NOT on the roadmap (scope boundary)

- ❌ **Multi-tenant / user accounts** — single user, single homelab.
  Add auth at the perimeter if needs change.
- ❌ **Cloud-hosted partsmith.com** — local-first. If others want it,
  they self-host.
- ❌ **Plugin / extension marketplace** — keep the core small.
- ❌ **Built-in slicer** — Bambu Studio exists; we hand off STL/3MF
  and stop.
- ❌ **AI-generated designs server-side** — the LLM lives in the
  client (Cowork, Claude Code, etc.). partsmith is a tool, not a
  model.
- ❌ **Real-time collaboration** — design sessions are single-user.

---

## Related work (sibling repos)

partsmith is one piece of a larger personal homelab stack. Roadmap-
adjacent work lives in sibling repos:

- **[JLay2026/zimaboard-services](https://github.com/JLay2026/zimaboard-services)**
  — the deploy harness. ZimaOS Custom Install pattern shipped (PRs
  #6→#9 + docs #10); nut/ retrofit is the remaining backlog item.
- **[JLay2026/nanoclaw-zimaos](https://github.com/JLay2026/nanoclaw-zimaos)**
  — Caddy frontend for `cad.lan.denkhaus.io` and other LAN/Tailscale
  vhosts.
- **[JLay2026/racknas-services](https://github.com/JLay2026/racknas-services)**
  — historical: hosted the Authentik integration that fronted
  partsmith until 2026-06-09. Now SUPERSEDED for the cad vhost; the
  runbook is preserved for any future browser-only app.

---

## How to contribute

This is a personal homelab project, not a commercial product. That
said:

- **Found a bug?** Open an issue with a reproducible test case (a
  curl command or build123d snippet that triggers it).
- **Want a feature on the roadmap?** Open an issue making the case;
  if it fits the design principles and a real use case is named, it'll
  go on the roadmap.
- **Want a feature NOT on the roadmap?** That's what "What's NOT on
  the roadmap" is for. If you really need it, fork — partsmith is MIT
  and the codebase is small enough to maintain a fork.
- **PRs welcome** for any open issue. The v0.3.1 integration suite runs
  automatically on every PR; keep it green.

## Versioning

Semver-ish, lower-than-1.0 conventions:

- **MAJOR** bumps reserved for v1.0 (the "6 months without surprises"
  milestone).
- **MINOR** bumps for new themes / endpoints / breaking changes to
  REST or MCP contracts.
- **PATCH** bumps for bug fixes, deploy-time discoveries, doc-only
  changes that affect users.

Version lives in:
- `src/__init__.py` (`__version__`)
- `pyproject.toml` (`[project] version`)
- Git tag on the commit that bumps both
- `CHANGELOG.md` entry with the date and the "why"
