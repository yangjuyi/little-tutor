"""Create timestamped SQLite backups for runtime databases."""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def backup_sqlite(source: Path, destination: Path) -> None:
    if not source.exists():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_conn = sqlite3.connect(
        f"file:{source.resolve().as_posix()}?mode=ro",
        uri=True,
    )
    target_conn = sqlite3.connect(destination)
    try:
        source_conn.backup(target_conn)
    finally:
        target_conn.close()
        source_conn.close()


def prune_backups(directory: Path, keep: int) -> None:
    files = sorted(
        directory.glob("*.db"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in files[keep:]:
        path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "outputs" / "backups",
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=ROOT,
    )
    parser.add_argument("--keep", type=int, default=14)
    args = parser.parse_args()
    if args.keep <= 0:
        raise SystemExit("--keep must be greater than 0")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for name in ("tutor.db", "checkpoints.db"):
        source = args.source_dir / name
        destination = args.output_dir / f"{name[:-3]}-{stamp}.db"
        backup_sqlite(source, destination)
        print(f"{source} -> {destination}")
    prune_backups(args.output_dir, args.keep)


if __name__ == "__main__":
    main()
