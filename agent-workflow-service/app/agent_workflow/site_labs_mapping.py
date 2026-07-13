"""Site ↔ lab mapping for query-side filter conflict checks."""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

_MAPPING_PATH = Path(__file__).resolve().parent / "data" / "sites-labs-mapping.csv"
_ALL_LABS = frozenset({"ALL", "all", "*"})


@lru_cache(maxsize=1)
def _load_rows() -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    if not _MAPPING_PATH.is_file():
        return rows
    with _MAPPING_PATH.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            lab = (row.get("Labs") or row.get("labs") or "").strip()
            site = (row.get("Site") or row.get("site") or "").strip()
            if lab and site:
                rows.append((lab, site))
    return rows


def labs_for_site(site: str) -> list[str]:
    site = (site or "").strip()
    if not site:
        return []
    labs: list[str] = []
    for lab, mapped_site in _load_rows():
        if mapped_site != site:
            continue
        if lab in _ALL_LABS:
            continue
        if lab not in labs:
            labs.append(lab)
    return labs


def site_for_lab(lab: str) -> str | None:
    lab = (lab or "").strip()
    if not lab or lab in _ALL_LABS:
        return None
    for mapped_lab, site in _load_rows():
        if mapped_lab == lab:
            return site
    return None


def lab_belongs_to_site(lab: str, site: str) -> bool:
    site = (site or "").strip()
    lab = (lab or "").strip()
    if not site or not lab:
        return False
    if lab in _ALL_LABS:
        return True
    return lab in labs_for_site(site)
