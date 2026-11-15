"""Shared strict JSON helpers for static display inputs."""
import hashlib
import json
from pathlib import Path


class BuildError(ValueError):
    """A display input cannot be safely rendered."""


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise BuildError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique_pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(BuildError("Non-finite JSON number")))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BuildError(f"Cannot read {Path(path).name}: {exc.__class__.__name__}") from exc


def object_fields(value, expected, label):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise BuildError(f"{label}: missing or unexpected fields")
