import logging
from typing import Any, Dict, List, Tuple

from .base import Routine
from backend.server import Turtle
from .subroutines import dig_to_coordinate, mine_ore_vein, update_inventory, get_inventory_dump_subroutine
import backend.db_state as db_state

logger = logging.getLogger("routine.auto_chunk_miner")


def _chunk_origin(x: int, z: int) -> Tuple[int, int]:
	"""Return (min_x, min_z) for the chunk containing (x,z). 16x16 chunks."""
	return (x // 16 * 16, z // 16 * 16)


class AutoChunkMinerRoutine(Routine):
	def __init__(self) -> None:
		super().__init__(
			description=(
				"Mine rectangular area of chunks in zig-zag strips per layer, triggering ore vein mining, "
				"and dumping inventory via a configurable strategy when nearly full."
			),
			config_template="""
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

	async def perform(self, session: Turtle._Session, config: Any | None) -> None:
		# Config parsing
		start_y = 50
		stop_y = 20
		empty_slots_threshold = 4
		chest_slot = 1
		dump_strategy = "dump_to_left_chest"
		fuel_threshold = 500
		chunks_x = 1
		chunks_z = 1
		tunnel_spacing = 2
		layer_step = 3
		if isinstance(config, dict):
			try: start_y = int(config.get("start_y", start_y))
			except Exception: pass
			try: stop_y = int(config.get("stop_y", stop_y))
			except Exception: pass
			try: empty_slots_threshold = int(config.get("empty_slots_threshold", empty_slots_threshold))
			except Exception: pass
			try: chest_slot = int(config.get("chest_slot", chest_slot))
			except Exception: pass
			try: dump_strategy = str(config.get("dump_strategy", dump_strategy))
			except Exception: pass
			try: fuel_threshold = int(config.get("fuel_threshold", fuel_threshold))
			except Exception: pass
			try: chunks_x = max(1, int(config.get("chunks_x", chunks_x)))
			except Exception: pass
			try: chunks_z = max(1, int(config.get("chunks_z", chunks_z)))
			except Exception: pass
			try: tunnel_spacing = max(1, int(config.get("tunnel_spacing", tunnel_spacing)))
			except Exception: pass
			try: layer_step = max(1, int(config.get("layer_step", layer_step)))
			except Exception: pass

		dump_fn = get_inventory_dump_subroutine(dump_strategy)

		st = db_state.get_state(session.turtle.id)
		coords = st.get("coords") or {"x": 0, "y": 0, "z": 0}
		x0, y0, z0 = int(coords.get("x", 0)), int(coords.get("y", 0)), int(coords.get("z", 0))
		cx, cz = _chunk_origin(x0, z0)
		width = 16 * chunks_x
		depth = 16 * chunks_z
		ne_x, ne_z = cx + width - 1, cz  # north-east corner: z=min, x=max (assuming +Z south, +X east)

		logger.info("Turtle %d: AutoChunkMiner start at (%d,%d,%d); area x:[%d..%d] z:[%d..%d] (chunks_x=%d, chunks_z=%d)",
					session.turtle.id, x0, y0, z0, cx, cx+width-1, cz, cz+depth-1, chunks_x, chunks_z)

		async def check_and_trigger(ok: bool, info: Dict[str, Any] | None) -> bool:
			try:
				name = str(info.get("name")) if ok and isinstance(info, dict) else None
			except Exception:
				name = None
			if name and "ore" in name.lower():
				logger.info("Turtle %d: Ore detected (%s); triggering mine_ore_vein", session.turtle.id, name)
				await mine_ore_vein(self, session, {})
				logger.info("Turtle %d: Vein mining complete, updating inventory", session.turtle.id)
				await _update_inventory()
				await _maybe_refuel()
				await _maybe_dump()
				return True
			return False

		# Helper to inspect 6 directions for ores and trigger vein mining if found
		async def scan_and_maybe_mine() -> None:
			logger.debug("Turtle %d: Scanning for ores", session.turtle.id)
			
			ok, info = await self.inspect();
			if await check_and_trigger(ok, info): return
			ok, info = await self.inspect_up();
			if await check_and_trigger(ok, info): return
			ok, info = await self.inspect_down();
			if await check_and_trigger(ok, info): return
			# check left and right by turning (restore heading)
			await self.turn_left()
			ok, info = await self.inspect();
			left_found = await check_and_trigger(ok, info)
			await self.turn_right()
			await self.turn_right()
			ok, info = await self.inspect();
			right_found = await check_and_trigger(ok, info)
			await self.turn_left()
			if left_found or right_found:
				return

		async def _update_inventory() -> None:
			try:
				# Firmware-side bulk inventory
				logger.info("Turtle %d: Calling get_inventory_details()", session.turtle.id)
				inv = await session.eval("get_inventory_details()")
				import json as _json
				db_state.set_state(session.turtle.id, inventory_json=_json.dumps(inv))
				logger.info("Turtle %d: Inventory updated successfully with %d slots", session.turtle.id, len(inv) if inv else 0)
			except Exception as e:
				logger.warning("Turtle %d: Firmware inventory failed: %s, trying fallback", session.turtle.id, e)
				try:
					items = await update_inventory(self, session)
					import json as _json
					db_state.set_state(session.turtle.id, inventory_json=_json.dumps(items))
					logger.info("Turtle %d: Fallback inventory updated with %d items", session.turtle.id, len(items) if items else 0)
				except Exception as e2:
					logger.error("Turtle %d: Both inventory methods failed: %s", session.turtle.id, e2)

		async def _maybe_refuel() -> None:
			try:
				fuel, _ = await self.get_fuel_level()
				if fuel is None or fuel >= fuel_threshold:
					return
				# Read latest inventory from DB
				inv = db_state.get_state(session.turtle.id).get("inventory")
				import json as _json
				obj = _json.loads(inv) if isinstance(inv, str) else inv
				coal_slot: int | None = None
				if isinstance(obj, dict):
					for k, v in obj.items():
						if not v: continue
						try:
							name = str(v.get("name") or "")
							display = str(v.get("displayName") or "")
							if ("coal" in name.lower()) or ("coal" in display.lower()):
								coal_slot = int(k)
								break
						except Exception:
							continue
				elif isinstance(obj, list):
					# Fallback list entries may include slot
					for entry in obj:
						try:
							name = str(entry.get("name") or "")
							display = str(entry.get("displayName") or "")
							slot = int(entry.get("slot")) if "slot" in entry else None
							if slot and (("coal" in name.lower()) or ("coal" in display.lower())):
								coal_slot = slot
								break
						except Exception:
							continue
				if coal_slot is None:
					return
				await self.select(coal_slot)
				await self.refuel(100000)
			except Exception:
				pass

		async def _count_empty_slots() -> int:
			try:
				inv = db_state.get_state(session.turtle.id).get("inventory")
				import json as _json
				obj = _json.loads(inv) if isinstance(inv, str) else inv
				if isinstance(obj, dict):
					# firmware structure: {"1": {...}|None, ...}
					return sum(1 for v in obj.values() if not v)
				if isinstance(obj, list):
					# fallback list of entries -> 16 - occupied
					# approximate by item count
					occupied = len(obj)
					return max(0, 16 - occupied)
			except Exception:
				pass
			return 0

		async def _maybe_dump() -> None:
			try:
				empty_slots = await _count_empty_slots()
				if empty_slots > empty_slots_threshold:
					return
				await dump_fn(self, session, {"chest_slot": chest_slot})
			except Exception as e:
				logger.warning("Turtle %d: dump failed (%s)", session.turtle.id, e)

		# Move to NE corner at start_y using direct dig path
		await dig_to_coordinate(self, session, {"x": ne_x, "y": start_y, "z": ne_z})

		# Zig-zag strip mining within the area for each layer
		current_y = start_y
		while current_y >= stop_y:
			logger.info("Turtle %d: Mining layer %d in area x:[%d..%d] z:[%d..%d]",
						session.turtle.id, current_y, cx, cx+width-1, cz, cz+depth-1)

			# Ensure we are at NE corner at this layer
			await dig_to_coordinate(self, session, {"x": ne_x, "y": current_y, "z": ne_z})

			# We'll snake along Z from cz..cz+depth-1 with configurable spacing.
			go_east_to_west = True  # alternate horizontal direction each row
			for row_z in range(cz, cz + depth, tunnel_spacing):
				if go_east_to_west:
					# Start from east edge
					await dig_to_coordinate(self, session, {"x": ne_x, "y": current_y, "z": row_z})
					# Face -X
					for _ in range(4):
						if db_state.get_state(session.turtle.id).get("heading") == 2:
							break
						await self.turn_right()
					# Traverse west across width-1
					for _ in range(max(0, width - 1)):
						await scan_and_maybe_mine()
						ok, _ = await self.inspect()
						if ok: await self.dig()
						# headroom before move
						ok_u, _ = await self.inspect_up()
						if ok_u: await self.dig_up()
						if not await self.forward(): break
						# headroom after move
						ok_u2, _ = await self.inspect_up()
						if ok_u2: await self.dig_up()
				else:
					# Start from west edge
					await dig_to_coordinate(self, session, {"x": cx, "y": current_y, "z": row_z})
					# Face +X
					for _ in range(4):
						if db_state.get_state(session.turtle.id).get("heading") == 0:
							break
						await self.turn_right()
					# Traverse east across width-1
					for _ in range(max(0, width - 1)):
						await scan_and_maybe_mine()
						ok, _ = await self.inspect()
						if ok: await self.dig()
						# headroom before move
						ok_u, _ = await self.inspect_up()
						if ok_u: await self.dig_up()
						if not await self.forward(): break
						# headroom after move
						ok_u2, _ = await self.inspect_up()
						if ok_u2: await self.dig_up()

				# Prepare for next row (we'll reposition at start of loop)
				go_east_to_west = not go_east_to_west

			# Finished layer; drop down layer_step levels
			for _ in range(layer_step):
				ok_d, _ = await self.inspect_down()
				if ok_d: await self.dig_down()
				if not await self.down(): break
			current_y -= layer_step

		logger.info("Turtle %d: AutoChunkMiner completed down to layer %d", session.turtle.id, current_y)
