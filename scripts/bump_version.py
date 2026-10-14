#!/usr/bin/env python3
"""Set the release number shown in the app (web + API) in one go.

    python3 scripts/bump_version.py 0.3.1

Updates apps/web/package.json (+ lock), services/api/pyproject.toml and
services/api/app/version.py. The exact build (git commit) is added automatically.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    if len(sys.argv) != 2 or not re.fullmatch(r"\d+\.\d+\.\d+", sys.argv[1]):
        sys.exit("usage: python3 scripts/bump_version.py X.Y.Z")
    v = sys.argv[1]
    for name in ("package.json", "package-lock.json"):
        p = ROOT / "apps/web" / name
        d = json.loads(p.read_text())
        d["version"] = v
        if "" in d.get("packages", {}):
            d["packages"][""]["version"] = v
        p.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
    p = ROOT / "services/api/pyproject.toml"
    p.write_text(re.sub(r'(?m)^version = "[^"]*"', f'version = "{v}"', p.read_text(), count=1))
    p = ROOT / "services/api/app/version.py"
    p.write_text(re.sub(r'(?m)^VERSION = "[^"]*"', f'VERSION = "{v}"', p.read_text(), count=1))
    print(f"version -> {v}")


if __name__ == "__main__":
    main()
