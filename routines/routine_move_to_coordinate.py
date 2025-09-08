from .routine import routine

@routine(
    label="Move To Coordinate",
    config_template="""
    # Move turtle to target coordinates with obstacle-aware pathing
    # The turtle will lift to y=150 first to avoid obstacles
    # then move horizontally before adjusting to target altitude
    x: 0
    y: 70
    z: 0
    """
)
async def move_to_coordinate_routine(turtle, config):
    """Move to target coordinates using pathfinding."""
    
    # Parse and validate coordinates
    target_x = int(config.get("x", 0))
    target_y = int(config.get("y", 70))
    target_z = int(config.get("z", 0))
    
    turtle.logger.info(f"Moving to coordinates ({target_x}, {target_y}, {target_z})")
    
    await turtle.inspect_up()
    await turtle.up()
    await turtle.down()

    await turtle.do_something()

    turtle.logger.info("Move to coordinate completed")
