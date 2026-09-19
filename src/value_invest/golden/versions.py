"""Extractor versions are folders: ``extractors/vN/{system.md, version.yaml}``.

``system.md`` is the surface a later optimiser may edit; ``version.yaml`` is
frozen for a version (model, effort, max_turns) so two versions differ only in
prompt. The fingerprint is part of the cache key, so a changed prompt re-runs
and an unchanged one never re-bills."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml

from value_invest.config import ROOT

EXTRACTORS_DIR = ROOT / "extractors"


@dataclass(frozen=True)
class ExtractorVersion:
    name: str
    path: Path
    system_prompt: str
    model: str
    effort: str
    max_turns: int
    critic_model: str
    fingerprint: str


def load_version(name: str = "v0") -> ExtractorVersion:
    path = EXTRACTORS_DIR / name
    system = (path / "system.md").read_text()
    cfg = yaml.safe_load((path / "version.yaml").read_text()) or {}
    h = hashlib.sha256()
    h.update(system.encode())
    h.update((path / "version.yaml").read_bytes())
    return ExtractorVersion(
        name=name,
        path=path,
        system_prompt=system,
        model=str(cfg.get("model", "sonnet")),
        effort=str(cfg.get("effort", "medium")),
        max_turns=int(cfg.get("max_turns", 4)),
        critic_model=str(cfg.get("critic_model", "opus")),
        fingerprint=h.hexdigest()[:12],
    )


def list_versions() -> list[str]:
    return sorted(p.name for p in EXTRACTORS_DIR.iterdir() if (p / "system.md").exists())
