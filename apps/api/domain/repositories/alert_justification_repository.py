"""Port (interface) for alert-justification persistence. Infrastructure
provides the adapter. Story: FINTRACK-25.
"""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from typing import Optional

from apps.api.domain.models.alert_justification import AlertJustification


class AlertJustificationRepository(ABC):
    @abstractmethod
    async def get_for_user_and_category(
        self, user_id: uuid.UUID, category: str
    ) -> Optional[AlertJustification]:
        ...

    @abstractmethod
    async def add(self, justification: AlertJustification) -> None:
        ...

    @abstractmethod
    async def update(self, justification: AlertJustification) -> None:
        ...
