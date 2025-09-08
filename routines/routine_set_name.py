import logging
from typing import Any

from .routine import routine


@routine(
    label="Set Label",
    config_template="""
    # Set the turtle's label (name tag)
    name: "My Turtle"
    """
)
async def set_label_routine(turtle, config):
    """Set the turtle's label using the provided configuration."""
    name = config.get("name", "")
    if not name:
        turtle.logger.error("Set Label routine: missing 'name' parameter")
        return

    await turtle.set_label(name)
    turtle.logger.info(f"Set Label routine: turtle label set to '{name}'")



