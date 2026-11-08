"""Stable JSON, input hashes and output location checks."""
import hashlib
import json
from pathlib import Path


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def object_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def code_fingerprint():
    root = Path(__file__).resolve().parent
    return object_digest({p.name:digest(p) for p in sorted(root.glob("*.py"))})


def external_directory(path, *, fresh=False):
    """Keep data, fitted artifacts and reports outside every Git worktree."""
    path = Path(path).resolve()
    for ancestor in (path, *path.parents):
        if (ancestor/".git").exists():
            raise ValueError("Choose an output directory outside Git worktrees")
    # This package may be run before the first Git commit exists.
    source = Path(__file__).resolve().parent.parent
    if path == source or source in path.parents:
        raise ValueError("Choose an output directory outside the source tree")
    if fresh and path.exists() and any(path.iterdir()):
        raise ValueError("Output directory must be empty; use a new experiment directory")
    path.mkdir(parents=True, exist_ok=True)
    return path
