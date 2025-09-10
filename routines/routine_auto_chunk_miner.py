import logging
from typing import Any, Dict, List, Tuple

from .routine import routine
import backend.db_state as db_state


def _chunk_origin(x: int, z: int) -> Tuple[int, int]:
	"""Return (min_x, min_z) for the chunk containing (x,z). 16x16 chunks."""
	return (x // 16 * 16, z // 16 * 16)


@routine(
    label="Auto Chunk Miner",
    config_template="""
# Auto chunk mining configuration
start_y: 50
stop_y: 20
empty_slots_threshold: 4
chest_slot: 1
dump_strategy: dump_to_left_chest
chunks_x: 1
chunks_z: 1
tunnel_spacing: 3
layer_step: 3
    """
)
async def auto_chunk_miner_routine(turtle, config):
	"""Mine rectangular area of chunks in zig-zag strips per layer, triggering ore vein mining."""
	
	# Config parsing with defaults
	start_y = config.get("start_y", 50)
	stop_y = config.get("stop_y", 20)
	empty_slots_threshold = config.get("empty_slots_threshold", 4)
	chest_slot = config.get("chest_slot", 1)
	dump_strategy = config.get("dump_strategy", "dump_to_left_chest")
	chunks_x = max(1, config.get("chunks_x", 1))
	chunks_z = max(1, config.get("chunks_z", 1))
	tunnel_spacing = max(1, config.get("tunnel_spacing", 3))
	layer_step = max(1, config.get("layer_step", 3))

	async def check_and_trigger_ore_mining(ok: bool, info: Dict[str, Any] | None) -> bool:
		"""Check if block is ore and trigger vein mining if so."""
		try:
			name = str(info.get("name")) if ok and isinstance(info, dict) else None
		except Exception:
			name = None
		if name and "ore" in name.lower():
			turtle.logger.info(f"Ore detected ({name}); triggering mine_ore_vein")
			await turtle.mine_ore_vein({})
			turtle.logger.info("Vein mining complete, updating inventory")

			await turtle.refuel_if_possible()
			await maybe_dump(dump_strategy)
			return True
		return False

	async def scan_and_maybe_mine():
		"""Scan 6 directions for ores and trigger vein mining if found."""
		turtle.logger.debug("Scanning for ores")
		
		# Check forward
		ok, info = await turtle.inspect()
		if await check_and_trigger_ore_mining(ok, info): 
			return
		
		# Check up
		ok, info = await turtle.inspect_up()
		if await check_and_trigger_ore_mining(ok, info): 
			return
		
		# Check down
		ok, info = await turtle.inspect_down()
		if await check_and_trigger_ore_mining(ok, info): 
			return
		
		# Check left
		await turtle.turn_left()
		ok, info = await turtle.inspect()
		left_found = await check_and_trigger_ore_mining(ok, info)
		await turtle.turn_right()
		
		# Check right
		await turtle.turn_right()
		ok, info = await turtle.inspect()
		right_found = await check_and_trigger_ore_mining(ok, info)
		await turtle.turn_left()
		
		if left_found or right_found:
			return

	async def maybe_dump(dump_strategy):
		"""Dump inventory if too full."""
		try:
			empty_slots = await turtle.count_empty_slots()
			if empty_slots > empty_slots_threshold:
				return
			
			if dump_strategy == "dump_to_left_chest":
				turtle.logger.info("Inventory low on space, dumping to left chest")
				await turtle.dump_to_left_chest(chest_slot)
			else:
				turtle.logger.warning(f"Unknown dump strategy: {dump_strategy}")
		except Exception as e:
			turtle.logger.warning(f"Dump failed: {e}")
   
   
   	# Get starting position
	# Get current position and determine chunk boundaries
	position = await turtle.get_location()
	if not position:
		turtle.logger.error("Could not get current position")
		return
	
	x0, y0, z0 = position
	cx, cz = _chunk_origin(x0, z0)
	width = 16 * chunks_x
	depth = 16 * chunks_z
	
	# Calculate south-east corner of the chunk area (highest X, highest Z)
	se_x = cx + width - 1
	se_z = cz + depth - 1
	
	turtle.logger.info(f"AutoChunkMiner: Current position ({x0},{y0},{z0}), chunk area x:[{cx}..{cx+width-1}] z:[{cz}..{cz+depth-1}]")
	turtle.logger.info(f"Moving to south-east corner at ({se_x},{start_y},{se_z}) to begin mining")
	
	# Move to south-east corner at start_y
	await turtle.dig_to_coordinate({"x": se_x, "y": start_y, "z": se_z})
	
	# Face north (heading=3, -Z direction) to start mining consistently
	for _ in range(4):
		if db_state.get_state(turtle.session._turtle.id).get("heading") == 3:
			break
		await turtle.turn_right()
	
	turtle.logger.info("Positioned at south-east corner, facing north, ready to start systematic mining")
	
	# Systematic mining from south-east corner, going north in strips
	current_y = start_y
	while current_y >= stop_y:
		turtle.logger.info(f"Mining layer {current_y}")
		
		# Return to south-east corner for this layer
		await turtle.dig_to_coordinate({"x": se_x, "y": current_y, "z": se_z})
		
		# Face north for consistent mining direction
		for _ in range(4):
			if db_state.get_state(turtle.session._turtle.id).get("heading") == 3:
				break
			await turtle.turn_right()
		
		# Mine strips going north, spaced by tunnel_spacing
		for strip_x in range(se_x, cx - 1, -tunnel_spacing):  # Go from east to west
			# Go to start of this strip
			await turtle.dig_to_coordinate({"x": strip_x, "y": current_y, "z": se_z})
			
			# Face north
			for _ in range(4):
				if db_state.get_state(turtle.session._turtle.id).get("heading") == 3:
					break 
				await turtle.turn_right()
			
			# Mine north across the depth
			for _ in range(depth - 1):
				await scan_and_maybe_mine()
				if not await turtle.dig_forward():
					break
				await turtle.dig_up()
				await turtle.refuel_if_possible()
				await maybe_dump(dump_strategy)
		
		# Drop down to next layer
		for _ in range(layer_step):
			ok_d, _ = await turtle.inspect_down()
			if ok_d:
				await turtle.dig_down()
			if not await turtle.down():
				break
		current_y -= layer_step

	turtle.logger.info(f"AutoChunkMiner completed down to layer {current_y}")
