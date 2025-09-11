from .routine import routine

@routine(
    label="Dig To Coordinate",
    config_template="""
    # Move turtle to target coordinates with obstacle-aware pathing
    # The turtle will lift to y=150 first to avoid obstacles
    # then move horizontally before adjusting to target altitude
    x: 0
    y: 70
    z: 0
    """
)
async def dig_to_coordinate_routine(turtle, config):
    """Move to target coordinates using pathfinding."""
    
    target = {
        "x": config.get("x", 0),
        "y": config.get("y", 70),
        "z": config.get("z", 0)
    }
    await turtle.dig_to_coordinate(target)
    return
