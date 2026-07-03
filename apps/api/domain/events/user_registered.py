"""Domain event emitted on successful registration.

Not wired to a message bus yet (no such infra exists in MVP) -- exists so
the observability layer and a future email-verification-nudge worker have
a typed event to hook into without a Tech Lead redesign later.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class UserRegistered:
    user_id: uuid.UUID
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
