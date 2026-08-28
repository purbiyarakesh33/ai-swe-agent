"""Durable, human-readable audit history for workflow runs."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone


class RunHistory:
    def __init__(self, path: str = "workflow_history.sqlite"):
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, run_id TEXT, event TEXT, details TEXT, created_at TEXT)"
        )
        self.connection.commit()

    def record(self, run_id: str, event: str, details: dict | None = None) -> None:
        self.connection.execute(
            "INSERT INTO events(run_id,event,details,created_at) VALUES (?,?,?,?)",
            (run_id, event, json.dumps(details or {}, default=str), datetime.now(timezone.utc).isoformat()),
        )
        self.connection.commit()

    def list_events(self, run_id: str | None = None) -> list[dict]:
        query = "SELECT run_id,event,details,created_at FROM events"
        params = ()
        if run_id:
            query += " WHERE run_id=?"
            params = (run_id,)
        query += " ORDER BY id"
        return [
            {"run_id": r[0], "event": r[1], "details": json.loads(r[2]), "created_at": r[3]}
            for r in self.connection.execute(query, params)
        ]
