import logging
from typing import Any, Dict, List, Tuple

from backend import turtle

from .routine import routine
import backend.db_state as db_state


def _chunk_origin(x: int, z: int) -> Tuple[int, int]:
	"""Return (min_x, min_z) for the chunk containing (x,z). 16x16 chunks."""
	return (x // 16 * 16, z // 16 * 16)


@routine(
    label="Full Chunk Miner",
    config_template="""
# Auto chunk mining configuration
start_y: 50
stop_y: 20
empty_slots_threshold: 4
chest_slot: 1
dump_strategy: dump_to_ender_chest
"""
)
async def full_chunk_miner_routine(turtle, config):
    # Config parsing with defaults
    start_y = config.get("start_y", 50)
    stop_y = config.get("stop_y", 20)
    empty_slots_threshold = config.get("empty_slots_threshold", 4)
    chest_slot = config.get("chest_slot", 1)
    dump_strategy = config.get("dump_strategy", "dump_to_left_chest")
    
    def _chunk_origin(x: int, z: int) -> Tuple[int, int]:
        """Return (min_x, min_z) for the chunk containing (x,z). 16x16 chunks."""
        return (x // 16 * 16, z // 16 * 16)
    
    async def maybe_dump(turtle, dump_strategy):
        """Dump inventory if too full."""
        try:
            empty_slots = await turtle.count_empty_slots()
            if empty_slots > empty_slots_threshold:
                return
            
            if dump_strategy == "dump_to_left_chest":
                turtle.logger.info("Inventory low on space, dumping to left chest")
                await turtle.dump_to_left_chest(chest_slot)
            if dump_strategy == "dump_to_ender_chest":
                turtle.logger.info("Inventory low on space, dumping to ender chest")
                await turtle.dump_to_ender_chest()
            else:
                turtle.logger.warning(f"Unknown dump strategy: {dump_strategy}")
        except Exception as e:
            turtle.logger.warning(f"Dump failed: {e}")

    position = await turtle.get_location()
    x0, y0, z0 = position

    cx, cz = _chunk_origin(x0, z0)
    se_x = cx + 16 - 1  
    se_z = cz + 16 - 1

    await turtle.dig_to_coordinate({"x": se_x, "y": start_y, "z": se_z})
    
    # Face north (heading=3, -Z direction) to start mining consistently
    for _ in range(4):
        if db_state.get_state(turtle.session._turtle.id).get("heading") == 3:
            break
        await turtle.turn_right()

    for height in range(start_y, stop_y - 1, -1):

        
        for width in range(8):
            for depth in range(15):
                await turtle.dig_forward()
            await turtle.turn_left()
            await turtle.dig_forward()
            await turtle.turn_left()
            
            for depth in range(15):
                await turtle.dig_forward()
            await turtle.turn_right()
            await turtle.dig_forward()
            await turtle.turn_right()
            
            await turtle.get_inventory_details()
            if await turtle.count_empty_slots() < empty_slots_threshold:
                await turtle.refuel_if_possible()
                await turtle.select(chest_slot)
                await maybe_dump(turtle, dump_strategy)
                
        await turtle.turn_right()
        for i in range(16):
            await turtle.dig_forward()
        await turtle.turn_left()
        await turtle.dig_down()
        await turtle.down()
        
    turtle.logger.info(f"ChunkMiner completed")
        
                
            