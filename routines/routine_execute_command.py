import logging
from typing import Any

from .routine import routine


@routine(
    label="Execute Command",
    config_template="""
# Execute a single subroutine

subroutine: forward 
 
# Example: forward, turn_left, dig, move_to_coordinate
"""
)
async def execute_subroutine_routine(turtle, config):
    """Execute a single subroutine using the provided configuration."""
    subroutine_name = config.get("subroutine", "")
    if not subroutine_name:
        turtle.logger.error("Execute Subroutine routine: missing 'subroutine' parameter")
        return

    # Check if the subroutine exists on the turtle wrapper
    if not hasattr(turtle, subroutine_name):
        turtle.logger.error(f"Execute Subroutine routine: unknown subroutine '{subroutine_name}'")
        return

    try:
        # Get the subroutine method and execute it
        subroutine_method = getattr(turtle, subroutine_name)
        result = await subroutine_method()
        turtle.logger.info(f"Execute Subroutine routine: '{subroutine_name}' executed successfully. Result: {repr(result)}")
    except Exception as e:
        turtle.logger.error(f"Execute Subroutine routine: '{subroutine_name}' failed: {e}")
