# partsmith roadmap

Strategic direction for [JLay2026/partsmith](https://github.com/JLay2026/partsmith).
For past releases see [`CHANGELOG.md`](CHANGELOG.md). For tactical work in
flight see [the issues tracker](https://github.com/JLay2026/partsmith/issues).

**Last updated:** 2026-06-09 (post-v0.2.4 — persistent design store
shipped; Wave A scope expanded to include ZimaOS Custom Install).

---

## Design principles (preserved across the roadmap)

- **Small over capable.** Every feature has to justify its line count.
  The whole server is ~900 LOC and we'd like to keep it small enough
  that a new contributor can read it in an afternoon.
- **Perimeter is the security boundary.** No in-app auth, no sandboxing
  theatre, no multi-tenant. See [`SECURITY.md`](SECURITY.md).
- **REST + MCP parity.** What works on one works on the other; both
  layers share the same in-process `CADEngine` instance so state is
  consistent across protocols.
- **Deployment is part of the product.** Bugs that only appear behind
  a real reverse proxy with a real client (see CHANGELOG v0.2.x) are
  bugs we own. Tests catch them; defaults assume real-world deploy.
- **Reuse the platform's native patterns.** ZimaOS provides Custom
  Install + x-casaos; we use it natively rather than inventing a
  parallel install flow.

---

## Theme 1 — Author ergonomics (biggest impact on your time)

You'll spend 80% of partsmith time writing build123d code. Anything
that compresses repeated patterns has outsized payoff.

| Issue | Item | Status |
|---|---|---|
| [#1](https://github.com/JLay2026/partsmith/issues/1) | Extract `partsmith_helpers` library from real designs (screw holes, slots, fillets, mounting patterns) | Open |
| [#2](https://github.com/JLay2026/partsmith/issues/2) | Persistent design store — save/load build123d source to disk; survives container restart | ✅ Shipped in v0.2.4 |
| [#3](https://github.com/JLay2026/partsmith/issues/3) | Versioned designs with `partsmith_diff_designs(name, v1, v2)` | Open (depends on #2) |
| [#4](https://github.com/JLay2026/partsmith/issues/4) | Cookbook — `examples/` dir with 5-10 starter designs covering common patterns | Open |

**Target release:** v0.3.0 (#1 + #3 + #4 still pending)

---

## Theme 2 — Output fidelity (compresses review cycles)

Current iso-view renders are "good enough to confirm not garbage" but
you can't tell from them whether wall thickness, screw hole position,
or fillet radius is right. Better outputs → fewer print failures.

| Item | What it gives you | Effort |
|---|---|---|
| Dimensioned 2D engineering drawings | Visual confirmation that the bracket is 50mm wide BEFORE printing | M |
| VTK or trimesh-scene renderer swap | Photorealistic-ish previews where surface finish matters | M-L |
| Cross-sections — `partsmith_render_section(name, plane='YZ', at=0)` | See internal cavities, wall thickness, snap-fit clearances | M |
| Multi-color preview — indicate AMS slot per face/body | Once you're using all 4 AMS slots for a part | L |

**Target release:** v0.4.0. No GitHub issues yet — file them when
starting work.

---

## Theme 3 — Print workflow integration (closes the loop to the X1C)

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

## Theme 4 — Validated quality (prevents the next 5-hour debug)

The four v0.2.x deploy bugs (see CHANGELOG) would have been caught by
integration tests against a containerized partsmith. Currently zero
coverage. This is boring no-feature work that protects investment in
everything else.

| Issue | Item | Status |
|---|---|---|
| [#5](https://github.com/JLay2026/partsmith/issues/5) | pytest integration suite (testcontainers, FastMCP client, full round-trip) + GitHub Actions CI workflow | Open |

**Target release:** v0.3.1 (do this BEFORE Theme 2/3 work — protects
investment).

---

## Theme 5 — Operational (deployment ergonomics)

User-facing deploy story. Native ZimaOS Custom Install (env vars as
GUI form fields, install/update via dashboard) replaces the current
CLI gitops flow that's caused real friction (e.g. the `.env` vs
`.env.example` sync gotcha during v0.2.0 deploy).

The actual implementation lives in `zimaboard-services` since that's
where the deploy compose file lives. partsmith's contribution is
the icon asset.

| Item | Where it lives | Status |
|---|---|---|
| ZimaOS Custom Install pattern (x-casaos compose extension) for partsmith + nut/ retrofit | [zimaboard-services#5](https://github.com/JLay2026/zimaboard-services/issues/5) | Open (full draft x-casaos block in issue body) |
| Placeholder partsmith icon (SVG, isometric cube) | [`assets/icon.svg`](assets/icon.svg) (this repo) | ✅ Shipped 2026-06-09 |

**Target release:** v0.3.0 (bundled with Theme 1 since both are user-facing).

---

## Suggested release sequence

```
v0.3.0  — Theme 1 (issues #1, #3, #4 — #2 already shipped in v0.2.4)
        + Theme 5 (zimaboard-services#5 — ZimaOS Custom Install)
v0.3.1  — Theme 4 (issue #5) — defensive, before more features
v0.4.0  — Theme 2 (renderer + drawings)
v0.5.0  — Theme 3 (3MF metadata, print analysis)
v0.6+   — Theme 3 cont. (Bambu Connect) or whatever real workloads have surfaced
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
  — the deploy harness. ZimaOS Custom Install pattern + nut/ retrofit
  tracked in [issue #5](https://github.com/JLay2026/zimaboard-services/issues/5).
- **[JLay2026/nanoclaw-zimaos](https://github.com/JLay2026/nanoclaw-zimaos)**
  — Caddy frontend for `cad.lan.denkhaus.io` and other LAN/Tailscale
  vhosts. Pending: `flush_interval -1` defensive add on the `@cad`
  block (no-op on modern Caddy since SSE is auto-detected, but
  belt-and-suspenders).
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
  and the codebase is small enough (~900 LOC) to maintain a fork.
- **PRs welcome** for any open issue. Run the integration suite (#5,
  when it lands) before submitting.

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
