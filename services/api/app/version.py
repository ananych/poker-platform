"""Release identification shown in the UI.

`VERSION` is the human release number (bump with scripts/bump_version.sh, which also
updates apps/web/package.json). `commit()` is the exact build: Railway provides
RAILWAY_GIT_COMMIT_SHA at runtime; locally we ask git; otherwise "dev".
"""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

VERSION = "0.3.0"
STARTED_AT = datetime.now(UTC).isoformat(timespec="seconds")


@lru_cache
def commit() -> str:
    sha = os.environ.get("RAILWAY_GIT_COMMIT_SHA") or os.environ.get("GIT_COMMIT_SHA") or ""
    if not sha:
        try:
            sha = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=Path(__file__).resolve().parent,
                capture_output=True,
                text=True,
                timeout=2,
            ).stdout.strip()
        except Exception:
            sha = ""
    return sha[:7] if sha else "dev"


def info() -> dict[str, str]:
    return {"version": VERSION, "commit": commit(), "started_at": STARTED_AT}
