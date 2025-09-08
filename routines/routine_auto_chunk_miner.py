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
fuel_threshold: 500
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
	fuel_threshold = config.get("fuel_threshold", 500)
	chunks_x = max(1, config.get("chunks_x", 1))
	chunks_z = max(1, config.get("chunks_z", 1))
	tunnel_spacing = max(1, config.get("tunnel_spacing", 3))
	layer_step = max(1, config.get("layer_step", 3))

	# Get starting position
	st = db_state.get_state(turtle.session._turtle.id)
	coords = st.get("coords") or {"x": 0, "y": 0, "z": 0}
	x0, y0, z0 = int(coords.get("x", 0)), int(coords.get("y", 0)), int(coords.get("z", 0))
	cx, cz = _chunk_origin(x0, z0)
	width = 16 * chunks_x
	depth = 16 * chunks_z
	ne_x, ne_z = cx + width - 1, cz  # north-east corner

	turtle.logger.info(f"AutoChunkMiner start at ({x0},{y0},{z0}); area x:[{cx}..{cx+width-1}] z:[{cz}..{cz+depth-1}] (chunks_x={chunks_x}, chunks_z={chunks_z})")

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
			await update_inventory_helper()
			await maybe_refuel()
			await maybe_dump()
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

	async def update_inventory_helper():
		"""Update inventory in database."""
		try:
			await turtle.get_inventory_details()
			turtle.logger.info("Inventory updated successfully")
		except Exception as e:
			turtle.logger.warning(f"Inventory update failed: {e}")

	async def maybe_refuel():
		"""Refuel if fuel is low and coal is available."""
		try:
			fuel = await turtle.get_fuel_level()
			if fuel is None or fuel >= fuel_threshold:
				return
			
			# Get inventory from DB to find coal
			st = db_state.get_state(turtle.session._turtle.id)
			inv = st.get("inventory_json")
			if not inv:
				return
				
			import json as _json
			obj = _json.loads(inv) if isinstance(inv, str) else inv
			coal_slot = None
			
			if isinstance(obj, dict):
				for k, v in obj.items():
					if not v: 
						continue
					try:
						name = str(v.get("name") or "")
						display = str(v.get("displayName") or "")
						if ("coal" in name.lower()) or ("coal" in display.lower()):
							coal_slot = int(k)
							break
					except Exception:
						continue
			
			if coal_slot is None:
				return
				
			await turtle.select(coal_slot)
			await turtle.refuel(100000)
		except Exception as e:
			turtle.logger.debug(f"Refuel failed: {e}")

	async def count_empty_slots() -> int:
		"""Count empty inventory slots."""
		try:
			st = db_state.get_state(turtle.session._turtle.id)
			inv = st.get("inventory_json")
			if not inv:
				return 0
				
			import json as _json
			obj = _json.loads(inv) if isinstance(inv, str) else inv
			
			if isinstance(obj, dict):
				return sum(1 for v in obj.values() if not v)
			elif isinstance(obj, list):
				occupied = len(obj)
				return max(0, 16 - occupied)
		except Exception:
			pass
		return 0

	async def maybe_dump():
		"""Dump inventory if too full."""
		try:
			empty_slots = await count_empty_slots()
			if empty_slots > empty_slots_threshold:
				return
			
			# Call the appropriate dump subroutine
			if hasattr(turtle, dump_strategy):
				dump_fn = getattr(turtle, dump_strategy)
				await dump_fn({"chest_slot": chest_slot})
			else:
				turtle.logger.warning(f"Unknown dump strategy: {dump_strategy}")
		except Exception as e:
			turtle.logger.warning(f"Dump failed: {e}")

	# Move to NE corner at start_y
	await turtle.dig_to_coordinate({"x": ne_x, "y": start_y, "z": ne_z})

	# Zig-zag strip mining for each layer
	current_y = start_y
	while current_y >= stop_y:
		turtle.logger.info(f"Mining layer {current_y} in area x:[{cx}..{cx+width-1}] z:[{cz}..{cz+depth-1}]")

		# Ensure we are at NE corner at this layer
		await turtle.dig_to_coordinate({"x": ne_x, "y": current_y, "z": ne_z})

		# Snake along Z direction with configurable spacing
		go_east_to_west = True
		for row_z in range(cz, cz + depth, tunnel_spacing):
			if go_east_to_west:
				# Start from east edge, go west
				await turtle.dig_to_coordinate({"x": ne_x, "y": current_y, "z": row_z})
				
				# Face west (-X direction, heading=2)
				for _ in range(4):
					if db_state.get_state(turtle.session._turtle.id).get("heading") == 2:
						break
					await turtle.turn_right()
				
				# Traverse west across the width
				for _ in range(max(0, width - 1)):
					await scan_and_maybe_mine()
					ok, _ = await turtle.inspect()
					if ok: 
						await turtle.dig()
					
					# Clear headroom before move
					ok_u, _ = await turtle.inspect_up()
					if ok_u: 
						await turtle.dig_up()
					
					if not await turtle.forward(): 
						break
					
					# Clear headroom after move
					ok_u2, _ = await turtle.inspect_up()
					if ok_u2: 
						await turtle.dig_up()
			else:
				# Start from west edge, go east
				await turtle.dig_to_coordinate({"x": cx, "y": current_y, "z": row_z})
				
				# Face east (+X direction, heading=0)
				for _ in range(4):
					if db_state.get_state(turtle.session._turtle.id).get("heading") == 0:
						break
					await turtle.turn_right()
				
				# Traverse east across the width
				for _ in range(max(0, width - 1)):
					await scan_and_maybe_mine()
					ok, _ = await turtle.inspect()
					if ok: 
						await turtle.dig()
					
					# Clear headroom before move
					ok_u, _ = await turtle.inspect_up()
					if ok_u: 
						await turtle.dig_up()
					
					if not await turtle.forward(): 
						break
					
					# Clear headroom after move
					ok_u2, _ = await turtle.inspect_up()
					if ok_u2: 
						await turtle.dig_up()

			# Alternate direction for next row
			go_east_to_west = not go_east_to_west

		# Drop down to next layer
		for _ in range(layer_step):
			ok_d, _ = await turtle.inspect_down()
			if ok_d: 
				await turtle.dig_down()
			if not await turtle.down(): 
				break
		current_y -= layer_step

	turtle.logger.info(f"AutoChunkMiner completed down to layer {current_y}")
