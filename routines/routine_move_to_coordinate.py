import logging
from typing import Any

from .base import Routine
from backend.server import Turtle
from .subroutines import move_to_coordinate

logger = logging.getLogger("routine.move_to_coordinate")


class MoveToCoordinateRoutine(Routine):
	def __init__(self) -> None:
		super().__init__(
			description="Move to target coordinates with obstacle-aware pathing",
			config_template="""
	x: 0
	y: 70
	z: 0
	"""
		)

	async def perform(self, session: Turtle._Session, config: Any | None) -> None:
		# Validate/normalize config
		if not isinstance(config, dict):
			logger.warning("Turtle %d: Config not dict, using defaults for MoveToCoordinateRoutine", session._turtle.id)
			config = {"x": 0, "y": 70, "z": 0}
		for key in ("x", "y", "z"):
			if key not in config:
				config[key] = 0 if key != "y" else 70
		try:
			config = {"x": int(config["x"]), "y": int(config["y"]), "z": int(config["z"])}
		except Exception:
			logger.warning("Turtle %d: Failed to parse coordinates, using defaults", session._turtle.id)
			config = {"x": 0, "y": 70, "z": 0}

		logger.info("Turtle %d: MoveToCoordinateRoutine to (%d,%d,%d)", session._turtle.id, config["x"], config["y"], config["z"])
		await move_to_coordinate(self, session, config)
