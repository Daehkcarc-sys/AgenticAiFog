"""Apply retention policy to local SQLite cloud/twin stores."""

from __future__ import annotations

import argparse
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


def prune_cloud(db_path: Path, cutoff: str) -> int:
    if not db_path.exists():
        return 0
    conn = sqlite3.connect(db_path)
    try:
        deleted = conn.execute(
            "DELETE FROM cloud_events WHERE ingested_at < ?",
            (cutoff,),
        ).rowcount
        conn.commit()
        return int(deleted or 0)
    finally:
        conn.close()


def prune_twin(db_path: Path, cutoff: str) -> int:
    if not db_path.exists():
        return 0
    conn = sqlite3.connect(db_path)
    try:
        deleted = conn.execute(
            "DELETE FROM twin_events WHERE applied_at < ?",
            (cutoff,),
        ).rowcount
        conn.commit()
        return int(deleted or 0)
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=int(os.getenv("CLOUD_EVENT_RETENTION_DAYS", "90")))
    parser.add_argument("--cloud-db", default=os.getenv("CLOUD_DB_PATH", "state/cloud_events.db"))
    parser.add_argument("--twin-db", default=os.getenv("DIGITAL_TWIN_DB_PATH", "state/digital_twin.db"))
    args = parser.parse_args()

    cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()
    cloud_deleted = prune_cloud(Path(args.cloud_db), cutoff)
    twin_deleted = prune_twin(Path(args.twin_db), cutoff)
    print(f"retention cutoff={cutoff}")
    print(f"deleted cloud_events={cloud_deleted}")
    print(f"deleted twin_events={twin_deleted}")


if __name__ == "__main__":
    main()
