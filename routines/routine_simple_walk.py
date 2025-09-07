import logging
from typing import Any

from .base import Routine
from backend.server import Turtle


class SimpleWalkRoutine(Routine):
    def __init__(self) -> None:
        super().__init__(
            description="Simple walking and turning pattern",
            config_template="""
steps: 100
"""
        )

    async def perform(self, session: Turtle._Session, config: Any | None) -> None:
        logger = logging.getLogger("routine.simple_walk")
        logger.info("Turtle %d: Starting SimpleWalkRoutine with config: %s", session._turtle.id, config)
        steps = 100
        try:
            if isinstance(config, dict):
                steps = int(config.get("steps", steps))
        except Exception:
            pass
        for _ in range(steps):
            await self.forward()
            await self.forward()
            await self.up()
            await self.turn_left()
            await self.down()
            fuel_level, error_message = await self.get_fuel_level()
            if fuel_level is not None:
                logger.info(f"Turtle {session._turtle.id}, fuel level: {fuel_level}")
            else:
                logger.warning(f"Turtle {session._turtle.id}, failed to get fuel level: {error_message or 'Unknown error'}")