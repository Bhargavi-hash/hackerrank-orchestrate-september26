"""Portable paths; explicit argument takes precedence over environment."""
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUDIT_PATH = REPO_ROOT / "evaluation" / "phase1_data_audit.json"


def dataset_root(path: str | Path | None = None) -> Path:
    return Path(path if path is not None else os.environ.get("DATASET_ROOT", REPO_ROOT / "dataset")).resolve()
