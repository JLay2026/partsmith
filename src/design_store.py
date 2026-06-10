# SPDX-FileCopyrightText: 2026 JLay2026
# SPDX-License-Identifier: MIT
"""
Persistent design store for partsmith (v0.2.4+).

Designs are saved to disk as ``{workspace}/designs/{name}.py`` (the
build123d source code) plus ``{workspace}/designs/{name}.json``
(metadata: timestamps, description, snapshot of geometry at save time).

Two-file layout instead of single JSON so:

- The source is human-readable on disk
  (``cat /workspace/designs/bracket.py`` shows the code as written)
- The source is git-friendly if the workspace is ever versioned
- The user can edit a saved design directly on disk (via SSH or shared
  filesystem) and the next load picks up the change

Key distinctions:

- **Models** live in memory (``CADEngine.models`` OrderedDict, LRU-bounded
  at 32). Lost on container restart.
- **Designs** live on disk (this module). Survive container restart. A
  design can be loaded into a model via ``partsmith_load_design``.

The source ``.py`` file is the source of truth. The ``.json`` sidecar is
bookkeeping that can be regenerated from defaults if missing or corrupt
(``load`` falls back gracefully so a hand-deleted sidecar doesn't break
loading the design).
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Same pattern as model names in cad_engine / server: alphanumeric +
# dash + underscore, 1-64 chars. Prevents path traversal and keeps
# filenames sane on every filesystem we care about.
NAME_PATTERN = r"^[a-zA-Z0-9_-]{1,64}$"
_NAME_RE = re.compile(NAME_PATTERN)


@dataclass
class DesignMetadata:
    """Metadata sidecar for a saved design.

    Stored as ``{name}.json`` next to the source. The shape is
    intentionally small + forward-compatible (extra keys on disk are
    ignored on load, so future fields can be added without breaking
    older designs).
    """

    name: str
    created_at: str = ""  # ISO 8601 UTC, set on first save
    last_modified: str = ""  # ISO 8601 UTC, updated on every save
    description: str = ""
    geometry: Optional[dict] = field(default=None)  # snapshot at save time

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "DesignMetadata":
        """Build from a dict, tolerating extra keys (forward-compat).

        Requires at minimum a 'name' key. Other fields fall back to
        dataclass defaults if absent.
        """
        known = {"name", "created_at", "last_modified", "description", "geometry"}
        clean = {k: v for k, v in d.items() if k in known}
        if "name" not in clean:
            raise ValueError("DesignMetadata requires 'name'")
        return cls(**clean)


class DesignStore:
    """File-backed persistent design store.

    Each design lives at ``{designs_dir}/{name}.py`` (source) +
    ``{designs_dir}/{name}.json`` (metadata). Source is the truth;
    metadata can be regenerated from defaults if missing or corrupt.

    Thread/process-safety: this class is NOT safe for concurrent writes
    to the same design name. partsmith is single-tenant single-process by
    design (single uvicorn worker), so this is acceptable. If you ever
    run multiple workers, add a per-name lock.
    """

    def __init__(self, workspace: Path):
        self.workspace = Path(workspace)
        self.designs_dir = self.workspace / "designs"
        self.designs_dir.mkdir(parents=True, exist_ok=True)

    # ── path helpers ─────────────────────────────

    @staticmethod
    def _validate_name(name: str) -> None:
        if not _NAME_RE.match(name):
            raise ValueError(
                f"Invalid design name {name!r}: must match {NAME_PATTERN}"
            )

    def _path(self, name: str, ext: str) -> Path:
        """Resolved path for a design's .py or .json file.

        Belt-and-braces: name is validated against NAME_PATTERN, then the
        resolved path is checked to confirm it's still under designs_dir.
        Defense against any unicode-normalization or symlink trickery
        that might slip past the name regex.
        """
        self._validate_name(name)
        candidate = (self.designs_dir / f"{name}.{ext}").resolve()
        designs_root = self.designs_dir.resolve()
        try:
            candidate.relative_to(designs_root)
        except ValueError as e:
            raise ValueError(
                f"Design path escapes designs dir: {candidate}"
            ) from e
        return candidate

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    # ── public API ─────────────────────────────────

    def save(
        self,
        name: str,
        code: str,
        description: str = "",
        geometry: Optional[dict] = None,
    ) -> DesignMetadata:
        """Save a design (source + metadata). Overwrite preserves created_at.

        Returns the persisted DesignMetadata.

        Args:
            name: Design name (NAME_PATTERN-validated).
            code: build123d Python source. Stored verbatim; never
                  executed by this class.
            description: Optional free-form description (max 500 chars
                  recommended; not enforced here).
            geometry: Optional bounding-box / volume / surface_area
                  snapshot, typically captured at save time by the
                  caller running the code through the CADEngine. Used
                  by list() to show summary info without re-executing.

        Raises:
            ValueError: invalid name.
            OSError: disk write failed (e.g. bind-mount perm mismatch).
        """
        py_path = self._path(name, "py")
        json_path = self._path(name, "json")

        now = self._now()

        # Preserve created_at on overwrite so design history isn't lost
        created_at = now
        if json_path.exists():
            try:
                prior = json.loads(json_path.read_text(encoding="utf-8"))
                created_at = prior.get("created_at") or now
            except (OSError, json.JSONDecodeError):
                # Prior sidecar corrupt; treat as new and recreate
                pass

        metadata = DesignMetadata(
            name=name,
            created_at=created_at,
            last_modified=now,
            description=description,
            geometry=geometry,
        )

        # Write source first (source of truth), then sidecar. If the
        # sidecar write fails the source is still saved; next load will
        # fall back to default metadata.
        py_path.write_text(code, encoding="utf-8")
        json_path.write_text(
            json.dumps(metadata.to_dict(), indent=2),
            encoding="utf-8",
        )

        return metadata

    def load(self, name: str) -> tuple[str, DesignMetadata]:
        """Load a design's source code + metadata.

        If the .json sidecar is missing or corrupt, returns a minimal
        DesignMetadata (just the name, empty timestamps). The source
        .py file is always required.

        Args:
            name: Design name.

        Returns:
            (code, metadata) tuple.

        Raises:
            ValueError: invalid name.
            FileNotFoundError: the design's .py source doesn't exist.
        """
        py_path = self._path(name, "py")
        json_path = self._path(name, "json")

        if not py_path.exists():
            raise FileNotFoundError(f"Design not found: {name}")

        code = py_path.read_text(encoding="utf-8")

        if json_path.exists():
            try:
                metadata = DesignMetadata.from_dict(
                    json.loads(json_path.read_text(encoding="utf-8"))
                )
            except (OSError, json.JSONDecodeError, ValueError):
                # Sidecar corrupt; fall back to minimal metadata so the
                # caller can still execute the source.
                metadata = DesignMetadata(name=name)
        else:
            metadata = DesignMetadata(name=name)

        return code, metadata

    def delete(self, name: str) -> bool:
        """Delete a design (both .py and .json if present).

        Returns True if anything was deleted, False if neither file
        existed.

        Raises:
            ValueError: invalid name.
            OSError: an unlink failed (permission / FS error).
        """
        py_path = self._path(name, "py")
        json_path = self._path(name, "json")

        deleted = False
        for path in (py_path, json_path):
            if path.exists():
                path.unlink()  # OSError propagates to caller
                deleted = True
        return deleted

    def list_all(self) -> list[DesignMetadata]:
        """List all saved designs, sorted by name.

        Designs whose .json sidecar is missing or corrupt are still
        listed (with minimal metadata). Files in designs_dir that don't
        match NAME_PATTERN are skipped silently (shouldn't happen but
        defensive against direct filesystem tampering).
        """
        out: list[DesignMetadata] = []
        for py_file in sorted(self.designs_dir.glob("*.py")):
            name = py_file.stem
            if not _NAME_RE.match(name):
                continue
            try:
                _, metadata = self.load(name)
                out.append(metadata)
            except (FileNotFoundError, ValueError, OSError):
                # Skip designs we can't load for any reason; better to
                # show the rest than to fail the whole listing.
                continue
        return out
