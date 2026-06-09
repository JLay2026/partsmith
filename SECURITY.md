# Security Policy

## Threat model

`partsmith` exposes endpoints (`POST /model/create` over REST, and the
equivalent `partsmith_create_model` over the MCP transport at `/mcp`)
that **execute arbitrary Python code** provided by the caller. This is
intentional — the use case is "AI agents author parts via build123d
code." Without this, the service has no reason to exist.

The security model is **perimeter-based**, with the container as the
last line of defense:

1. **The container has no authentication.** Every endpoint accepts
   unauthenticated requests. There are no API tokens, no rate
   limiting, no source-IP allowlists at the application layer. This
   applies equally to the REST surface and the MCP transport at
   `/mcp`.
2. **Code execution is scoped to the container** by Linux primitives:
   - Non-root user (uid 1000) by default in the shipped Dockerfile
   - All Linux capabilities dropped (`cap_drop: ALL` in `docker-compose.yml`)
   - `security_opt: no-new-privileges:true` (no setuid escalation)
   - Memory and CPU bounded (`mem_limit: 4g`, `cpus: 2.0`)
   - Filesystem writes restricted to `/workspace` and `/renders`
     (typically bind-mounted from host)
   - No outbound network calls required for normal operation
3. **The intended deployment** places an authenticating reverse proxy
   (e.g. Caddy with forward-auth to an identity provider) in front of
   the container, with the container's port reachable only via that
   proxy (host-firewall rule or Docker network isolation). The proxy
   protects both `/` (REST) and `/mcp` (MCP) under the same auth flow.

## What partsmith does NOT do

- **No code sandboxing.** No substring blacklists, no restricted
  `__builtins__`, no AST filtering. These approaches are escapable in
  practice (the classic `().__class__.__bases__[0].__subclasses__()`
  walk works against any of them) and give false confidence. We do not
  ship security theatre.
- **No CORS allow-all.** The default FastAPI config does not enable
  CORS. If you need to call the API from a browser context, add CORS
  middleware explicitly and scope it.
- **No outbound LLM integration.** Unlike some adjacent projects,
  partsmith does not call external APIs (OpenAI, Anthropic, etc.).
  The caller IS the LLM.

## v0.2 notes

- The MCP transport at `/mcp` inherits the same perimeter trust model
  as the REST layer — anything past your reverse proxy reaches both
  surfaces equally. Both wrap the same `CADEngine` instance so the
  blast radius is identical.
- The MCP `partsmith_export` tool can return files inline as base64
  (≤ 8 MiB by default) or as a `url_path` the client fetches via
  `GET /workspace/{filename}`. That GET endpoint enforces a strict
  allowlist on filenames (`[a-zA-Z0-9_-]+\.(stl|step|3mf)` only) as
  defense in depth against path traversal; the WORKSPACE bind mount
  is the actual containment boundary.
- The `BodySizeLimitMiddleware` 1 MiB cap applies to REST requests
  only. MCP requests at `/mcp` are exempt because legitimate MCP
  responses (base64-inlined renders / exports) can exceed 1 MiB; MCP
  client-side framework limits bound the request side.

## Don't deploy partsmith without the perimeter

If you expose port 8123 directly to a network you do not control,
treat the container as conceptually equivalent to giving that network
shell access to a sandbox user on a small VM. Bound risk, but real.

## Reporting a vulnerability

Open a private security advisory on this repository:
https://github.com/JLay2026/partsmith/security/advisories/new
