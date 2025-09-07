import logging
from typing import Any

from .base import Routine
from server import Turtle


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
        iterations = 100
        try:
            if isinstance(config, dict):
                iterations = int(config.get("iterations", iterations))
        except Exception:
            pass
        for _ in range(iterations):
            await self.select(1)
            await self.dig()
            await self.forward()
            await self.turn_right()
            await self.turn_right()
            await self.place()
            await self.turn_right()
            await self.turn_right()

            await self.dig()
            await self.forward()
            await self.turn_right()
            await self.turn_right()
            await self.place()
            await self.turn_right()
            await self.turn_right()

            await self.turn_left()

            fuel_level, error_message = await self.get_fuel_level()
            if fuel_level is not None:
                logger.info(f"Turtle {session._turtle.id}, fuel level: {fuel_level}")
            else:
                logger.warning(f"Turtle {session._turtle.id}, failed to get fuel level: {error_message or 'Unknown error'}")


