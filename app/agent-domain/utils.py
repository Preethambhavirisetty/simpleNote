from pathlib import Path

import yaml


CATALOG_ROOT = Path(__file__).resolve().parent


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
