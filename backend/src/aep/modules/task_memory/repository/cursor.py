"""Opaque keyset-pagination cursor shared by TaskRepository and ExecutionHistoryRepository —
both are the "high-volume/append-only" category that docs/architecture/04-api-design.md §0.3
specifies cursor pagination for, as opposed to Project Service's offset pagination.

The cursor encodes `(created_at, id)` of the last row seen; encoding it opaquely (base64) rather
than exposing raw values keeps callers from depending on the encoding, so it can change later
without breaking the API contract.
"""

from __future__ import annotations

import base64
from datetime import datetime
from uuid import UUID


def encode_cursor(created_at: datetime, row_id: UUID) -> str:
    raw = f"{created_at.isoformat()}|{row_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    raw = base64.urlsafe_b64decode(cursor.encode()).decode()
    created_at_str, id_str = raw.split("|", 1)
    return datetime.fromisoformat(created_at_str), UUID(id_str)
