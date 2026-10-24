"""Copy source JSON data into the static public artifact."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data"
DESTINATION = ROOT / "public" / "data"


def main() -> int:
    DESTINATION.mkdir(parents=True, exist_ok=True)
    for name in ("reports.json", "state.json"):
        source = SOURCE / name
        with source.open("r", encoding="utf-8") as handle:
            json.load(handle)
        shutil.copy2(source, DESTINATION / name)
        print(f"Copied {source.relative_to(ROOT)} -> {(DESTINATION / name).relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
