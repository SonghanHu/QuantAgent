"""
Shared workspace for a single agent run.

Every tool can read/write artifacts through the workspace so downstream tools
automatically pick up upstream outputs (DataFrames, JSON configs, feature plans, etc.).

Storage layout::

    data/workspaces/<run_id>/
    ├── manifest.json
    ├── raw_data.parquet
    ├── feature_plan.json
    └── ...
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field


class ArtifactMeta(BaseModel):
    name: str
    path: str
    kind: str = Field(description="'dataframe' | 'json' | 'file'")
    description: str = ""
    shape: list[int] | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class Workspace:
    """File-backed artifact store for one agent run."""

    def __init__(self, root: Path | str, run_id: str | None = None) -> None:
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._manifest_path = self.root / "manifest.json"
        self._manifest: dict[str, ArtifactMeta] = {}
        if self._manifest_path.exists():
            raw = json.loads(self._manifest_path.read_text())
            self._manifest = {k: ArtifactMeta(**v) for k, v in raw.items()}

    # ------------------------------------------------------------------
    # DataFrame
    # ------------------------------------------------------------------

    def save_df(self, name: str, df: pd.DataFrame, *, description: str = "") -> Path:
        path = self.root / f"{name}.parquet"
        df.to_parquet(path, index=True)
        self._manifest[name] = ArtifactMeta(
            name=name,
            path=str(path),
            kind="dataframe",
            description=description,
            shape=[df.shape[0], df.shape[1]],
        )
        self._flush_manifest()
        return path

    def load_df(self, name: str) -> pd.DataFrame:
        meta = self._manifest.get(name)
        if meta is None:
            raise KeyError(f"No artifact '{name}' in workspace; available: {list(self._manifest)}")
        return pd.read_parquet(meta.path)

    def has(self, name: str) -> bool:
        return name in self._manifest

    def df_path(self, name: str) -> Path:
        meta = self._manifest.get(name)
        if meta is None:
            raise KeyError(f"No artifact '{name}'; available: {list(self._manifest)}")
        return Path(meta.path)

    # ------------------------------------------------------------------
    # JSON
    # ------------------------------------------------------------------

    def save_json(self, name: str, data: Any, *, description: str = "") -> Path:
        path = self.root / f"{name}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str))
        self._manifest[name] = ArtifactMeta(
            name=name,
            path=str(path),
            kind="json",
            description=description,
        )
        self._flush_manifest()
        return path

    def load_json(self, name: str) -> Any:
        meta = self._manifest.get(name)
        if meta is None:
            raise KeyError(f"No artifact '{name}'; available: {list(self._manifest)}")
        return json.loads(Path(meta.path).read_text())

    def artifact_path(self, name: str) -> Path:
        """Filesystem path for any manifest entry (parquet, json, image, …)."""
        meta = self._manifest.get(name)
        if meta is None:
            raise KeyError(f"No artifact '{name}'; available: {list(self._manifest)}")
        return Path(meta.path)

    def save_binary(
        self,
        name: str,
        *,
        filename: str,
        data: bytes,
        kind: str = "image",
        description: str = "",
    ) -> Path:
        """Write raw bytes under the workspace root and register in the manifest."""
        path = self.root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        self._manifest[name] = ArtifactMeta(
            name=name,
            path=str(path),
            kind=kind,
            description=description,
        )
        self._flush_manifest()
        return path

    def save_text(
        self,
        name: str,
        text: str,
        *,
        ext: str = "txt",
        description: str = "",
    ) -> Path:
        """Write UTF-8 text (e.g. generated ``.py``) and register as ``kind: text`` for API preview."""
        safe_ext = ext.lstrip(".") or "txt"
        path = self.root / f"{name}.{safe_ext}"
        path.write_text(text, encoding="utf-8")
        self._manifest[name] = ArtifactMeta(
            name=name,
            path=str(path),
            kind="text",
            description=description,
        )
        self._flush_manifest()
        return path

    def discard(self, name: str) -> None:
        """Remove an artifact from the manifest and delete its file if present."""
        meta = self._manifest.pop(name, None)
        if meta is not None:
            p = Path(meta.path)
            if p.exists():
                p.unlink()
        self._flush_manifest()

    # ------------------------------------------------------------------
    # Introspection (for LLM context)
    # ------------------------------------------------------------------

    def list_artifacts(self) -> dict[str, dict[str, Any]]:
        """Return a JSON-serialisable summary suitable for injecting into LLM prompts."""
        out: dict[str, dict[str, Any]] = {}
        for name, meta in self._manifest.items():
            entry: dict[str, Any] = {"kind": meta.kind, "description": meta.description}
            if meta.shape:
                entry["shape"] = meta.shape
            out[name] = entry
        return out

    def summary(self) -> str:
        """One-line human-readable summary."""
        items = [f"{n} ({m.kind})" for n, m in self._manifest.items()]
        return f"Workspace({self.run_id}): {', '.join(items) or 'empty'}"

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _flush_manifest(self) -> None:
        data = {k: v.model_dump() for k, v in self._manifest.items()}
        self._manifest_path.write_text(json.dumps(data, indent=2, default=str))

    def __repr__(self) -> str:
        return self.summary()
