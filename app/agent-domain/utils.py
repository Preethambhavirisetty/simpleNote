from pathlib import Path
from typing import Any, TypeVar

import yaml
from fastapi import HTTPException
from pydantic import BaseModel, ValidationError


CATALOG_ROOT = Path(__file__).resolve().parent

ModelT = TypeVar("ModelT", bound=BaseModel)


class CatalogNotFoundError(FileNotFoundError):
    """Raised when a catalog item cannot be located on disk."""


def read_yaml(relative_path: str) -> dict:
    file_path = CATALOG_ROOT / relative_path

    if not file_path.is_file():
        raise CatalogNotFoundError(f"YAML file not found: {file_path}")

    try:
        with file_path.open("r", encoding="utf-8") as file:
            payload = yaml.safe_load(file)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in {relative_path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError(f"Invalid YAML document in {relative_path}")

    return payload


def list_child_dirs(relative_path: str) -> list[str]:
    path = CATALOG_ROOT / relative_path

    if not path.exists():
        raise CatalogNotFoundError(f"Directory not found: {path}")

    if not path.is_dir():
        raise NotADirectoryError(f"{path} is not a directory")

    return sorted(child.name for child in path.iterdir() if child.is_dir())


def read_catalog_section(relative_path: str, key: str, label: str) -> Any:
    """Read one top-level key out of a catalog file as an HTTP-shaped result."""
    try:
        payload = read_yaml(relative_path)
    except CatalogNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"{label} Catalog Not Found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    section = payload.get(key)
    if section is None:
        raise HTTPException(status_code=500, detail=f"Invalid {label} Catalog Format")

    return section


def named_entries(section: Any, label: str) -> list[dict]:
    """Flatten a name-keyed catalog mapping into records carrying their name."""
    if not isinstance(section, dict):
        raise HTTPException(status_code=500, detail=f"Invalid {label} Catalog Format")

    entries = []
    for name, fields in section.items():
        if not isinstance(fields, dict):
            raise HTTPException(
                status_code=500, detail=f"Invalid {label} Catalog Entry: {name}"
            )
        entries.append({"name": str(name), **fields})
    return entries


def build_model(model: type[ModelT], payload: Any, label: str) -> ModelT:
    """Validate a catalog record; a malformed catalog is a server-side fault."""
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=500, detail=f"Invalid {label}: {exc}") from exc
