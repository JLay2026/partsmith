# SPDX-FileCopyrightText: 2026 JLay2026
# SPDX-License-Identifier: MIT
"""
build123d wrapper.

execute_code() runs arbitrary Python in a namespace pre-loaded with
build123d. This is intentional and load-bearing — see SECURITY.md.
Do not deploy without an authenticating reverse proxy in front.

v0.2.5 (issue #1): auto-injects partsmith_helpers into the build123d
execution namespace. Tool calls can now use through_hole(), screw_hole(),
slot(), chamfer_edges(), etc. without explicit imports. See
partsmith_helpers.py for the full helper set.

v0.3.3 (issue #13): the geometry summary now carries B-rep topology
counts (face_count / edge_count / vertex_count) so a saved design's
snapshot lets the version diff report complexity deltas. B-rep counts
are deterministic, unlike mesh triangle counts (tessellation-dependent).
"""

from __future__ import annotations

import io
import sys
import time
import traceback
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# v0.1: bound the in-memory model registry to prevent unbounded growth.
# 32 is plenty for batch CAD authoring; LRU eviction discards the
# oldest-touched entries first.
MAX_MODELS = 32


@dataclass
class ModelState:
    name: str
    code: str
    shape: Any = None  # build123d Shape / Part / Solid / Compound
    timestamp: float = field(default_factory=time.time)

    def to_summary(self) -> dict:
        out: dict[str, Any] = {
            "name": self.name,
            "timestamp": self.timestamp,
            "geometry": None,
        }
        if self.shape is None:
            return out
        try:
            bb = self.shape.bounding_box()
            out["geometry"] = {
                "bounding_box": {
                    "min": [round(bb.min.X, 3), round(bb.min.Y, 3), round(bb.min.Z, 3)],
                    "max": [round(bb.max.X, 3), round(bb.max.Y, 3), round(bb.max.Z, 3)],
                    "size": [
                        round(bb.max.X - bb.min.X, 3),
                        round(bb.max.Y - bb.min.Y, 3),
                        round(bb.max.Z - bb.min.Z, 3),
                    ],
                },
                "volume_mm3": (
                    round(self.shape.volume, 3) if hasattr(self.shape, "volume") else None
                ),
                "surface_area_mm2": (
                    round(self.shape.area, 3) if hasattr(self.shape, "area") else None
                ),
            }
            # v0.3.3 (issue #13): B-rep topology counts. Inner try/except
            # so a count failure on odd geometry never costs us the
            # bbox/volume snapshot above. These persist into a saved
            # design's metadata.geometry and power the diff's
            # face_count_delta / edge_count_delta / vertex_count_delta.
            try:
                out["geometry"]["face_count"] = len(self.shape.faces())
                out["geometry"]["edge_count"] = len(self.shape.edges())
                out["geometry"]["vertex_count"] = len(self.shape.vertices())
            except Exception:
                pass
        except Exception:
            pass
        return out


class CADEngine:
    """In-memory model registry + build123d code executor.

    Models are kept in an LRU OrderedDict bounded by ``MAX_MODELS``.
    """

    def __init__(self, workspace: Path = Path("/workspace")):
        self.workspace = Path(workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.models: OrderedDict[str, ModelState] = OrderedDict()
        self.active: Optional[str] = None

    def execute_code(self, code: str, name: str = "default") -> dict:
        """
        Run user-supplied build123d code. The code may assign the final
        shape to a variable named `result` (preferred), or any
        Part / Solid / Compound — the last one defined is captured.

        Returns:
            {"success": bool, "stdout": str, "error": str | None,
             "geometry": dict | None}
        """
        result: dict[str, Any] = {
            "success": False,
            "stdout": "",
            "error": None,
            "geometry": None,
        }

        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()

        namespace: dict[str, Any] = {"__name__": "__main__"}
        extra_stdout = ""
        try:
            exec("from build123d import *", namespace)
            exec("import numpy as np", namespace)

            # v0.2.5: inject partsmith_helpers into namespace.
            # Lazy import: keeps server-boot fast (helpers import is only
            # paid on first execute_code call; subsequent calls hit the
            # interpreter's import cache for free).
            try:
                from .partsmith_helpers import HELPERS as _PARTSMITH_HELPERS
                namespace.update(_PARTSMITH_HELPERS)
            except ImportError:
                # Should never happen in a healthy deploy; preserve
                # legacy behavior (raw build123d only) if it does.
                pass

            exec(code, namespace)

            shape = self._extract_shape(namespace)
            if shape is not None:
                state = ModelState(name=name, code=code, shape=shape)
                self.models[name] = state
                self.models.move_to_end(name)  # touch -> most-recently-used
                # LRU eviction
                while len(self.models) > MAX_MODELS:
                    evicted_name, _ = self.models.popitem(last=False)
                    if self.active == evicted_name:
                        self.active = None
                self.active = name
                result["success"] = True
                result["geometry"] = state.to_summary()["geometry"]
            else:
                result["success"] = True
                extra_stdout = (
                    "\n[Warning: no Shape found. Assign final result to "
                    "'result' variable.]"
                )
        except Exception as e:
            result["error"] = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        finally:
            result["stdout"] = sys.stdout.getvalue() + extra_stdout
            err = sys.stderr.getvalue()
            if err:
                result["error"] = (err + "\n" + (result["error"] or "")).strip()
            sys.stdout, sys.stderr = old_stdout, old_stderr

        return result

    def _extract_shape(self, namespace: dict) -> Any:
        if "result" in namespace and namespace["result"] is not None:
            return namespace["result"]
        try:
            from build123d import Compound, Part, Shape, Solid
            shape_types = (Part, Solid, Compound, Shape)
        except ImportError:
            return None
        candidates = [
            (k, v) for k, v in namespace.items()
            if not k.startswith("_") and isinstance(v, shape_types)
        ]
        return candidates[-1][1] if candidates else None

    def get(self, name: Optional[str] = None) -> Optional[ModelState]:
        name = name or self.active
        if not name:
            return None
        state = self.models.get(name)
        if state is not None:
            # Touch on access so frequently-used models don't get evicted
            self.models.move_to_end(name)
        return state

    def list_all(self) -> list[dict]:
        return [
            {**state.to_summary(), "active": k == self.active}
            for k, state in self.models.items()
        ]

    def measure(self, name: Optional[str] = None) -> dict:
        state = self.get(name)
        if state is None or state.shape is None:
            return {"error": f"No model '{name or 'active'}' found"}
        shape = state.shape
        try:
            bb = shape.bounding_box()
            out: dict[str, Any] = {
                "bounding_box": {
                    "min": [round(bb.min.X, 3), round(bb.min.Y, 3), round(bb.min.Z, 3)],
                    "max": [round(bb.max.X, 3), round(bb.max.Y, 3), round(bb.max.Z, 3)],
                    "width_mm": round(bb.max.X - bb.min.X, 3),
                    "depth_mm": round(bb.max.Y - bb.min.Y, 3),
                    "height_mm": round(bb.max.Z - bb.min.Z, 3),
                },
                "volume_mm3": round(shape.volume, 3) if hasattr(shape, "volume") else None,
                "surface_area_mm2": (
                    round(shape.area, 3) if hasattr(shape, "area") else None
                ),
            }
            try:
                com = shape.center()
                out["center_of_mass"] = [round(com.X, 3), round(com.Y, 3), round(com.Z, 3)]
            except Exception:
                pass
            try:
                out["face_count"] = len(shape.faces())
                out["edge_count"] = len(shape.edges())
                out["vertex_count"] = len(shape.vertices())
            except Exception:
                pass
            return out
        except Exception as e:
            return {"error": str(e)}

    def export(self, name: Optional[str] = None, format: str = "stl") -> Path:
        state = self.get(name)
        if state is None or state.shape is None:
            raise ValueError(f"No model '{name or 'active'}' available")

        # Defense-in-depth: even though server.py validates `name` at the
        # request layer, refuse anything that could escape the workspace.
        # state.name comes from the validated request so this is belt+braces.
        safe_name = Path(state.name).name  # strips any leading dirs
        if safe_name != state.name or not safe_name:
            raise ValueError(f"Unsafe model name: {state.name!r}")

        path = self.workspace / f"{safe_name}.{format}"
        # Final guard: resolved path must stay under workspace
        try:
            path.resolve().relative_to(self.workspace.resolve())
        except ValueError:
            raise ValueError(f"Export path escapes workspace: {path}")

        if format == "stl":
            from build123d import export_stl
            export_stl(state.shape, str(path))
        elif format == "step":
            from build123d import export_step
            export_step(state.shape, str(path))
        elif format == "3mf":
            try:
                from build123d import export_3mf  # type: ignore
                export_3mf(state.shape, str(path))
            except ImportError:
                from build123d import export_stl
                path = path.with_suffix(".stl")
                export_stl(state.shape, str(path))
        else:
            raise ValueError(f"Unsupported format: {format}")
        return path
