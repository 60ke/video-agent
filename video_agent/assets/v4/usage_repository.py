from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
import sqlite3


@dataclass
class AssetUsageRepository:
    """In-process usage history for Stage 4 soft ranking."""

    completed_counts: Counter[str] = field(default_factory=Counter)
    pending: list[tuple[str, str, str, str]] = field(default_factory=list)

    def record_pending(self, *, run_id: str, scene_id: str, slot_id: str, asset_ref: str) -> None:
        self.pending.append((run_id, scene_id, slot_id, asset_ref))

    def mark_completed(self, run_id: str) -> None:
        for item_run, _scene, _slot, asset_ref in self.pending:
            if item_run == run_id:
                self.completed_counts[asset_ref] += 1
        self.pending = [item for item in self.pending if item[0] != run_id]

    def abandon(self, run_id: str) -> None:
        self.pending = [item for item in self.pending if item[0] != run_id]

    def counts(self) -> dict[str, int]:
        return dict(self.completed_counts)


class SQLiteAssetUsageRepository:
    """Durable usage history; only completed Runs affect future ranking."""

    def __init__(self, database: Path) -> None:
        self.connection = sqlite3.connect(database)
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS stage4_asset_usage (
            run_id TEXT NOT NULL, scene_id TEXT NOT NULL, slot_id TEXT NOT NULL,
            asset_ref TEXT NOT NULL, completed INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(run_id, scene_id, slot_id, asset_ref))"""
        )
        self.connection.commit()

    def record_pending(self, *, run_id: str, scene_id: str, slot_id: str, asset_ref: str) -> None:
        self.connection.execute(
            "INSERT OR IGNORE INTO stage4_asset_usage VALUES (?,?,?,?,0)",
            (run_id, scene_id, slot_id, asset_ref),
        )
        self.connection.commit()

    def mark_completed(self, run_id: str) -> None:
        self.connection.execute(
            "UPDATE stage4_asset_usage SET completed=1 WHERE run_id=?",
            (run_id,),
        )
        self.connection.commit()

    def abandon(self, run_id: str) -> None:
        self.connection.execute(
            "DELETE FROM stage4_asset_usage WHERE run_id=? AND completed=0",
            (run_id,),
        )
        self.connection.commit()

    def counts(self) -> dict[str, int]:
        return {
            row[0]: int(row[1])
            for row in self.connection.execute(
                "SELECT asset_ref, COUNT(*) FROM stage4_asset_usage WHERE completed=1 GROUP BY asset_ref"
            )
        }

    def close(self) -> None:
        self.connection.close()
