"""Backup local cloud and digital twin SQLite databases."""

from __future__ import annotations

import argparse
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path


def backup_file(source: Path, backup_dir: Path) -> Path | None:
    if not source.exists():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / f"{source.stem}-{stamp}{source.suffix}"
    shutil.copy2(source, target)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cloud-db", default=os.getenv("CLOUD_DB_PATH", "state/cloud_events.db"))
    parser.add_argument("--twin-db", default=os.getenv("DIGITAL_TWIN_DB_PATH", "state/digital_twin.db"))
    parser.add_argument("--backup-dir", default=os.getenv("BACKUP_DIR", "backups"))
    args = parser.parse_args()

    backup_dir = Path(args.backup_dir)
    for source in (Path(args.cloud_db), Path(args.twin_db)):
        target = backup_file(source, backup_dir)
        if target:
            print(f"backed up {source} -> {target}")
        else:
            print(f"skipped missing database: {source}")


if __name__ == "__main__":
    main()
