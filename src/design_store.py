# SPDX-FileCopyrightText: 2026 JLay2026
# SPDX-License-Identifier: MIT
"""
Persistent design store for partsmith (v0.2.4+).

v0.2.7 (issue #3): added per-design version tracking. Each design is
now a directory containing v1.py, v1.json, v2.py, v2.json, ... so
iteration is a v1/v2/v3 trail rather than overwriting in place.

Backward compatibility: designs saved by v0.2.4-v0.2.6 (flat layout
``designs/{name}.py + {name}.json``) are read transparently as version
1. On the next save the legacy files are auto-migrated to
``designs/{name}/v1.py + v1.json`` and subsequent saves append v2, v3
etc.

Layouts side-by-side::

    pre-v0.2.7 (legacy, still readable):
        designs/
          bracket.py
          bracket.json

    v0.2.7+ (versioned):
        designs/
          bracket/
            v1.py
            v1.json
            v2.py
            v2.json
            v3.py
            v3.json

Source files are still the source of truth; sidecars are bookkeeping
that can be regenerated from defaults if missing or corrupt.

Key distinctions (unchanged from v0.2.4):
- **Models** live in memory (CADEngine.models, LRU-bounded at 32).
- **Designs** live on disk. Survive container restart. A design can
  be loaded into a model via partsmith_load_design.
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

NAME_PATTERN = r"^[a-zA-Z0-9_-]{1,64}$"
_NAME_RE = re.compile(NAME_PATTERN)

# v0.2.7: version filenames look like "v1.py" / "v1.json". Stem must
# match this pattern.
_VERSION_STEM_RE = re.compile(r"^v(\d+)$")


@dataclass
class DesignMetadata:
    """Metadata sidecar for a saved design version.

    Stored as ``{name}/v{N}.json`` (v0.2.7+) or ``{name}.json``
    (pre-v0.2.7 legacy). Shape is forward-compatible: extra keys on
    disk are ignored on load.

    v0.2.7 adds ``version``. Old metadata files don't have this; load
    falls back to ``1`` for legacy entries.
    """

    name: str
    version: int = 1
    created_at: str = ""
    last_modified: str = ""
    description: str = ""
    geometry: Optional[dict] = field(default=None)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "DesignMetadata":
        """Build from a dict, tolerating extra keys (forward-compat)."""
        known = {
            "name", "version", "created_at", "last_modified",
            "description", "geometry",
        }
        clean = {k: v for k, v in d.items() if k in known}
        if "name" not in clean:
            raise ValueError("DesignMetadata requires 'name'")
        # Default version to 1 if missing (pre-v0.2.7 metadata).
        clean.setdefault("version", 1)
        return cls(**clean)


class DesignStore:
    """File-backed persistent design store with per-design versioning."""

    def __init__(self, workspace: Path):
        self.workspace = Path(workspace)
        self.designs_dir = self.workspace / "designs"
        self.designs_dir.mkdir(parents=True, exist_ok=True)

    # ── name + path helpers ─────────────────────────────

    @staticmethod
    def _validate_name(name: str) -> None:
        if not _NAME_RE.match(name):
            raise ValueError(
                f"Invalid design name {name!r}: must match {NAME_PATTERN}"
            )

    def _design_dir(self, name: str) -> Path:
        """Resolved per-design directory; defense against path escape."""
        self._validate_name(name)
        candidate = (self.designs_dir / name).resolve()
        try:
            candidate.relative_to(self.designs_dir.resolve())
        except ValueError as e:
            raise ValueError(
                f"Design path escapes designs dir: {candidate}"
            ) from e
        return candidate

    def _version_path(self, name: str, version: int, ext: str) -> Path:
        """Path for {name}/v{version}.{ext} in versioned layout."""
        return self._design_dir(name) / f"v{int(version)}.{ext}"

    def _legacy_path(self, name: str, ext: str) -> Path:
        """Path for pre-v0.2.7 flat layout: {name}.{ext}."""
        self._validate_name(name)
        candidate = (self.designs_dir / f"{name}.{ext}").resolve()
        try:
            candidate.relative_to(self.designs_dir.resolve())
        except ValueError as e:
            raise ValueError(
                f"Legacy design path escapes designs dir: {candidate}"
            ) from e
        return candidate

    def _is_legacy(self, name: str) -> bool:
        """A design is in legacy layout if {name}.py exists at root AND
        {name}/ directory does NOT exist."""
        legacy_py = self.designs_dir / f"{name}.py"
        versioned_dir = self.designs_dir / name
        return legacy_py.exists() and not versioned_dir.exists()

    def _migrate_legacy(self, name: str) -> None:
        """Move legacy {name}.py + {name}.json into {name}/v1.{py,json}.

        Called on first save of a previously-legacy design when version
        resolution is "auto" -- the v0.2.7 save flow needs the versioned
        directory to exist before it can append a new version.
        """
        legacy_py = self._legacy_path(name, "py")
        legacy_json = self._legacy_path(name, "json")

        dest_dir = self._design_dir(name)
        dest_dir.mkdir(parents=True, exist_ok=True)

        v1_py = self._version_path(name, 1, "py")
        v1_json = self._version_path(name, 1, "json")

        if legacy_py.exists():
            legacy_py.rename(v1_py)
        if legacy_json.exists():
            # Bump the version field in the migrated metadata so it
            # accurately reflects what it is (legacy got 0 implicit
            # version; now stamped as v1).
            try:
                meta = json.loads(legacy_json.read_text(encoding="utf-8"))
                meta["version"] = 1
                v1_json.write_text(
                    json.dumps(meta, indent=2), encoding="utf-8"
                )
                legacy_json.unlink()
            except (OSError, json.JSONDecodeError):
                # Corrupt sidecar; just move it and let the next load
                # fall back to default metadata
                legacy_json.rename(v1_json)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    # ── version listing + resolution ───────────────────

    def list_versions(self, name: str) -> list[int]:
        """List version numbers for a design, sorted ascending.

        Returns [] if the design doesn't exist. For legacy (pre-v0.2.7)
        designs, returns [1].

        Raises:
            ValueError: invalid name.
        """
        self._validate_name(name)

        if self._is_legacy(name):
            return [1]

        d = self._design_dir(name)
        if not d.exists():
            return []

        versions: list[int] = []
        for p in d.glob("v*.py"):
            m = _VERSION_STEM_RE.match(p.stem)
            if m:
                versions.append(int(m.group(1)))
        return sorted(versions)

    def _resolve_version(
        self, name: str, version: Union[int, str, None]
    ) -> int:
        """Resolve version arg to a concrete int.

        Args:
            name: design name (must exist for "latest"/"None")
            version: int (specific), None or "latest" (newest)

        Raises:
            FileNotFoundError: design has no versions and version is
                None/"latest"
            ValueError: bad version arg
        """
        if version is None or version == "latest":
            existing = self.list_versions(name)
            if not existing:
                raise FileNotFoundError(f"Design not found: {name}")
            return existing[-1]
        if isinstance(version, int) and version > 0:
            return version
        raise ValueError(
            f"version must be 'latest', None, or positive int, got {version!r}"
        )

    def _next_version(self, name: str) -> int:
        existing = self.list_versions(name)
        return (existing[-1] + 1) if existing else 1

    # ── public API: save / load / delete / list / diff ────────

    def save(
        self,
        name: str,
        code: str,
        description: str = "",
        geometry: Optional[dict] = None,
        version: Union[int, str] = "auto",
    ) -> DesignMetadata:
        """Save a design version. Returns the persisted metadata.

        Args:
            name: design name (NAME_PATTERN-validated).
            code: build123d Python source (stored verbatim).
            description: optional free-form description.
            geometry: optional bbox/volume/surface_area snapshot. As of
                v0.3.3 the save flow also stuffs face_count / edge_count
                / vertex_count in here so the version diff can report
                topology-complexity deltas.
            version: "auto" (default) appends the next unused version;
                     an int targets that specific slot, overwriting any
                     existing content at that version.

        Raises:
            ValueError: invalid name or version arg.
            OSError: disk write failed (e.g. bind-mount perm mismatch).
        """
        self._validate_name(name)

        # Resolve target version
        if version == "auto":
            # Migrate legacy layout transparently so the v0.2.7 save
            # appends a new version on top of the migrated v1.
            if self._is_legacy(name):
                self._migrate_legacy(name)
            target_version = self._next_version(name)
        elif isinstance(version, int) and version > 0:
            # Explicit version -- still migrate legacy first if
            # targeting v1 on a legacy design.
            if self._is_legacy(name):
                self._migrate_legacy(name)
            target_version = version
        else:
            raise ValueError(
                f"version must be 'auto' or positive int, got {version!r}"
            )

        # Ensure versioned directory exists
        d = self._design_dir(name)
        d.mkdir(parents=True, exist_ok=True)

        py_path = self._version_path(name, target_version, "py")
        json_path = self._version_path(name, target_version, "json")

        now = self._now()

        # Preserve created_at on overwrite of an existing slot
        created_at = now
        if json_path.exists():
            try:
                prior = json.loads(json_path.read_text(encoding="utf-8"))
                created_at = prior.get("created_at") or now
            except (OSError, json.JSONDecodeError):
                pass

        metadata = DesignMetadata(
            name=name,
            version=target_version,
            created_at=created_at,
            last_modified=now,
            description=description,
            geometry=geometry,
        )

        # Source first (truth), then sidecar
        py_path.write_text(code, encoding="utf-8")
        json_path.write_text(
            json.dumps(metadata.to_dict(), indent=2),
            encoding="utf-8",
        )

        return metadata

    def load(
        self,
        name: str,
        version: Union[int, str, None] = None,
    ) -> tuple[str, DesignMetadata]:
        """Load a design's source + metadata.

        Args:
            name: design name.
            version: int (specific), None (default) or "latest" (latest
                     version). Legacy (pre-v0.2.7) designs are exposed
                     as version 1.

        Returns:
            (code, metadata) tuple.

        Raises:
            ValueError: invalid name or version arg.
            FileNotFoundError: design or specific version doesn't exist.
        """
        self._validate_name(name)
        target_version = self._resolve_version(name, version)

        # Handle legacy layout transparently
        if self._is_legacy(name) and target_version == 1:
            py_path = self._legacy_path(name, "py")
            json_path = self._legacy_path(name, "json")
        else:
            py_path = self._version_path(name, target_version, "py")
            json_path = self._version_path(name, target_version, "json")

        if not py_path.exists():
            raise FileNotFoundError(
                f"Design not found: {name} v{target_version}"
            )

        code = py_path.read_text(encoding="utf-8")

        if json_path.exists():
            try:
                metadata = DesignMetadata.from_dict(
                    json.loads(json_path.read_text(encoding="utf-8"))
                )
            except (OSError, json.JSONDecodeError, ValueError):
                metadata = DesignMetadata(name=name, version=target_version)
        else:
            metadata = DesignMetadata(name=name, version=target_version)

        # Force version field to match what we actually loaded (in case
        # of metadata drift, e.g. user hand-edited the sidecar)
        metadata.version = target_version
        return code, metadata

    def delete(
        self,
        name: str,
        version: Union[int, str, None] = None,
    ) -> bool:
        """Delete design version(s).

        Args:
            name: design name.
            version: None (default) deletes ALL versions plus the
                     directory. int deletes just that version (leaves
                     other versions intact). Legacy designs: version=1
                     OR version=None both nuke the legacy files.

        Returns:
            True if anything was removed, False otherwise.
        """
        self._validate_name(name)

        deleted = False

        if version is None:
            # Nuke everything for this design name
            # Legacy files first
            for ext in ("py", "json"):
                lp = self._legacy_path(name, ext)
                if lp.exists():
                    lp.unlink()
                    deleted = True
            # Versioned dir
            d = self._design_dir(name)
            if d.exists():
                for child in d.iterdir():
                    child.unlink()
                d.rmdir()
                deleted = True
            return deleted

        if not isinstance(version, int) or version <= 0:
            raise ValueError(
                f"version must be None or positive int, got {version!r}"
            )

        # Specific version delete
        # Legacy v1: nuke the legacy files
        if self._is_legacy(name) and version == 1:
            for ext in ("py", "json"):
                lp = self._legacy_path(name, ext)
                if lp.exists():
                    lp.unlink()
                    deleted = True
            return deleted

        # Versioned layout
        for ext in ("py", "json"):
            vp = self._version_path(name, version, ext)
            if vp.exists():
                vp.unlink()
                deleted = True

        # Clean up empty design dir (last version was just removed)
        d = self._design_dir(name)
        if d.exists() and not any(d.iterdir()):
            d.rmdir()

        return deleted

    def list_all(self) -> list[DesignMetadata]:
        """List all saved designs (latest version of each) sorted by name.

        For multi-version designs, returns the metadata of the latest
        version. Use ``list_versions(name)`` for per-design version list.

        Designs whose latest sidecar is missing or corrupt are still
        listed (with minimal metadata).
        """
        names: set[str] = set()

        # Legacy entries: {name}.py files at designs_dir root
        for py_file in self.designs_dir.glob("*.py"):
            stem = py_file.stem
            if _NAME_RE.match(stem):
                names.add(stem)

        # Versioned entries: subdirectories under designs_dir
        for child in self.designs_dir.iterdir():
            if child.is_dir() and _NAME_RE.match(child.name):
                # Only count if at least one v*.py exists
                if any(child.glob("v*.py")):
                    names.add(child.name)

        out: list[DesignMetadata] = []
        for name in sorted(names):
            try:
                _, metadata = self.load(name)  # latest by default
                out.append(metadata)
            except (FileNotFoundError, ValueError, OSError):
                # Skip designs we can't load; better to show the rest
                continue
        return out

    def diff(
        self,
        name: str,
        v1: int,
        v2: int,
    ) -> dict:
        """Compute diff between two versions of a design.

        Returns a dict containing:
            name, v1, v2
            source_diff: unified diff text (str, empty if identical)
            volume_delta_mm3: v2 - v1 (or None if unavailable)
            surface_area_delta_mm2: v2 - v1 (or None if unavailable)
            bbox_size_delta_mm: [dx, dy, dz] (v2 size - v1 size)
                                 (or None if unavailable)
            face_count_delta: v2 - v1 B-rep face count (or None)
            edge_count_delta: v2 - v1 B-rep edge count (or None)
            vertex_count_delta: v2 - v1 B-rep vertex count (or None)
            v1_metadata: full metadata dict for v1
            v2_metadata: full metadata dict for v2

        The *_count_delta fields (v0.3.3, issue #13) report B-rep
        topology complexity change. B-rep counts come from
        ``shape.faces()/edges()/vertices()`` and are deterministic --
        unlike mesh triangle counts, which depend on tessellation
        tolerance and would make the same design diff non-reproducibly.
        A positive face_count_delta means v2 is structurally more
        complex than v1 (added bosses, holes, fillets, etc.). These are
        only populated when both versions were saved with geometry
        snapshots that captured the counts (saves via v0.3.3+).

        Both versions must already exist. Use partsmith_list_versions to
        check available versions first.

        Args:
            name: design name.
            v1: from-version (older)
            v2: to-version (newer)

        Raises:
            ValueError: invalid name or non-positive version ints.
            FileNotFoundError: either version doesn't exist.
        """
        self._validate_name(name)
        if not (isinstance(v1, int) and v1 > 0):
            raise ValueError(f"v1 must be positive int, got {v1!r}")
        if not (isinstance(v2, int) and v2 > 0):
            raise ValueError(f"v2 must be positive int, got {v2!r}")

        code1, meta1 = self.load(name, version=v1)
        code2, meta2 = self.load(name, version=v2)

        # Source diff (unified format, 3 lines of context)
        source_diff = "".join(
            difflib.unified_diff(
                code1.splitlines(keepends=True),
                code2.splitlines(keepends=True),
                fromfile=f"{name}_v{v1}.py",
                tofile=f"{name}_v{v2}.py",
                n=3,
            )
        )

        geo1 = meta1.geometry or {}
        geo2 = meta2.geometry or {}

        def _delta(key: str) -> Optional[float]:
            a, b = geo1.get(key), geo2.get(key)
            if a is None or b is None:
                return None
            try:
                return round(float(b) - float(a), 3)
            except (TypeError, ValueError):
                return None

        # v0.3.3 (issue #13): integer topology-complexity deltas.
        # Deterministic B-rep counts (see docstring) rather than
        # tessellation-dependent mesh triangle counts.
        def _int_delta(key: str) -> Optional[int]:
            a, b = geo1.get(key), geo2.get(key)
            if a is None or b is None:
                return None
            try:
                return int(b) - int(a)
            except (TypeError, ValueError):
                return None

        bbox_size_delta = None
        bb1 = geo1.get("bounding_box") or {}
        bb2 = geo2.get("bounding_box") or {}
        s1 = bb1.get("size")
        s2 = bb2.get("size")
        if (
            isinstance(s1, list) and isinstance(s2, list)
            and len(s1) == 3 and len(s2) == 3
        ):
            try:
                bbox_size_delta = [
                    round(float(s2[i]) - float(s1[i]), 3)
                    for i in range(3)
                ]
            except (TypeError, ValueError):
                bbox_size_delta = None

        return {
            "name": name,
            "v1": v1,
            "v2": v2,
            "source_diff": source_diff,
            "volume_delta_mm3": _delta("volume_mm3"),
            "surface_area_delta_mm2": _delta("surface_area_mm2"),
            "bbox_size_delta_mm": bbox_size_delta,
            "face_count_delta": _int_delta("face_count"),
            "edge_count_delta": _int_delta("edge_count"),
            "vertex_count_delta": _int_delta("vertex_count"),
            "v1_metadata": meta1.to_dict(),
            "v2_metadata": meta2.to_dict(),
        }
