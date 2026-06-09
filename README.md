# partsmith

Minimal, headless parametric-CAD server. Wraps
[build123d](https://github.com/gumyr/build123d) (OpenCascade) with a
small REST API so AI agents can:

- Author parts via build123d Python (`result = Box(30, 20, 10)`)
- Render 3D + 2D views as inline PNGs (per-face Lambertian shading)
- Validate printability (watertight / manifold checks)
- Export to STL / STEP / 3MF

Designed for headless deployment on a small Linux host, fronted by an
authenticating reverse proxy. The container itself does no
authentication — the perimeter is the security boundary. See
[`SECURITY.md`](SECURITY.md).

## Quick start (local dev)

```bash
pip install -e .
python -m uvicorn src.server:app --host 0.0.0.0 --port 8123
curl http://localhost:8123/health
```

## Container

```bash
git clone https://github.com/JLay2026/partsmith
cd partsmith

# First-time deploy — pre-create the bind-mount dirs as uid 1000.
# The container runs as uid 1000; without this step, docker compose
# auto-creates workspace/ and renders/ as root:root, and every export
# and render returns a permission-denied 500.
mkdir -p workspace renders
sudo chown -R 1000:1000 workspace renders

docker compose up -d --build
docker logs partsmith
curl http://127.0.0.1:8123/health
```

The shipped `docker-compose.yml` binds to `127.0.0.1:8123` (loopback
only) — adapt for your deployment. With the bind mounts above, STL
exports land in `./workspace/` and render PNGs land in `./renders/`,
both reachable from the host.

## Operational notes

- **In-memory model registry.** Models live in a Python dict for the
  lifetime of the container process. `docker compose restart` or any
  other container restart **wipes all named models**. The build123d
  code itself is not persisted; re-execute `POST /model/create` to
  re-instantiate. Acceptable for batch workflows
  (create → render → export → done). LRU-capped at 32 models.
- **Single uvicorn worker by default.** Concurrent renders serialize.
  Fine for a single-user homelab; add `--workers N` to `entrypoint.sh`
  if you need parallelism (each worker is +500 MB resident memory).
- **No persistence across restarts** for renders cached in `/renders`
  either, but those are inexpensive to regenerate from the source code
  if you keep your prompts.

## Tool surface

| Endpoint | Method | Purpose |
|---|---|---|
| `/health` | GET | `{"status":"ok","version":"X"}` |
| `/model/create` | POST | Execute build123d code, store as named model, return geometry summary + base64 preview PNG |
| `/model/modify` | POST | Same as `/model/create` — re-execute for existing name |
| `/model/list` | GET | List loaded models |
| `/model/{name}/measure` | GET | Bounding box, volume, surface area, counts |
| `/render/3d` | POST | 3D view, base64 PNG with Lambertian shading. Views: `front`, `back`, `left`, `right`, `top`, `bottom`, `iso`, `iso_back` |
| `/render/2d` | POST | 2D orthographic view with optional dimension annotations, base64 PNG |
| `/render/multiview` | POST | Composite: front + right + top + iso (shaded) |
| `/render/all` | POST | Render every standard view to disk, return paths |
| `/export` | POST | Export STL / STEP / 3MF as binary download |
| `/analyze/printability` | POST | Trimesh watertight / manifold check |

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `PARTSMITH_WORKSPACE` | `/workspace` | Where exported STL/STEP/3MF files land |
| `PARTSMITH_RENDERS` | `/renders` | Where rendered PNGs are cached |
| `PARTSMITH_HOST` | `0.0.0.0` | Server bind address |
| `PARTSMITH_PORT` | `8123` | Server bind port |
| `PARTSMITH_MAX_BODY_BYTES` | `1048576` (1 MiB) | Reject requests with `Content-Length` larger than this |

## Why this exists

There are a few existing build123d-MCP wrappers. We chose to ship a
new one because (a) the most prominent existing project shipped a
SyntaxError in its main file four months ago and nobody noticed, and
(b) the wrapped surface is small enough (~500 LOC) that owning it
outright is cheaper than maintaining a fork with patches.

See [`NOTICE.md`](NOTICE.md) for credit to prior work.

## License

MIT — see [`LICENSE`](LICENSE).
