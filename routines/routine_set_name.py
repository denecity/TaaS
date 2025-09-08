import logging
from typing import Any

from .base import Routine
from backend.server import Turtle


class SetNameRoutine(Routine):
	def __init__(self) -> None:
		super().__init__(
			description="Set the turtle nametag (computer label)",
			config_template="""
name: "My Turtle"
"""
		)

	async def perform(self, session: Turtle._Session, config: Any | None) -> None:
		logger = logging.getLogger("routine.set_name")
		
		# Validate config
		if not isinstance(config, dict) or not config.get("name") or not isinstance(config.get("name"), str):
			logger.error("Turtle %d: SetNameRoutine missing valid 'name' in config", session._turtle.id)
			return
		
		name: str = config["name"]
		
		# Use the new set_label method which handles everything (firmware + database + frontend notification)
		try:
			success = await session.set_label(name)
			if success:
				logger.info("Turtle %d: Name tag set to '%s'", session._turtle.id, name)
			else:
				logger.warning("Turtle %d: Failed to set name tag to '%s'", session._turtle.id, name)
		except Exception as e:
			logger.error("Turtle %d: set_label failed: %s", session._turtle.id, e)


