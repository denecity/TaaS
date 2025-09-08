import logging
from typing import Any

from .base import Routine
from backend.server import Turtle


class SimpleDigRoutine(Routine):
    def __init__(self) -> None:
        super().__init__(
            description="Simple dig and place pattern",
            config_template="""
iterations: 100
"""
        )

    async def perform(self, session: Turtle._Session, config: Any | None) -> None:
        # The logger for routines/base.py will handle command logging.
        # Any additional routine-specific logging can be done here.
        logger = logging.getLogger("routine.simple_dig")
        logger.info("Turtle %d: Starting SimpleDigRoutine with config: %s", session._turtle.id, config)

        await self.session.select(1)
        await self.session.get_item_count()
        await self.session.get_item_detail()

        await self.session.place()

        for slot in range(1, 17):
            if slot == 1:
                continue
            await self.session.select(slot)
            await self.session.drop()

        return

