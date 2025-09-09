import logging
from typing import Any, Dict, List
import json

from backend.server import Turtle
import backend.db_state as db_state

logger = logging.getLogger("subroutines")


async def mine_ore_vein(turtle, config: dict = None) -> None:
	"""Flood-fill mine any connected 'ore' vein in 6 directions (includes up/down).

	The turtle will pathfind over already mined cells to the nearest discovered ore,
	then return to the start and restore heading.
	
	Config options:
	- max_actions: int (default 2000) - maximum actions before stopping
	"""
	def is_ore(name: str | None) -> bool:
		if not name:
			return False
		return "ore" in name.lower()

	# Local pose tracking (origin and heading 0:+X,1:+Z,2:-X,3:-Z)
	dir_idx = 0
	start_dir_idx = dir_idx
	dir_vecs: List[tuple[int,int,int]] = [(1,0,0),(0,0,1),(-1,0,0),(0,0,-1)]
	pos: tuple[int,int,int] = (0,0,0)
	start_pos = pos

	def add_vec(a: tuple[int,int,int], b: tuple[int,int,int]) -> tuple[int,int,int]:
		return (a[0]+b[0], a[1]+b[1], a[2]+b[2])

	async def turn_left_local() -> None:
		nonlocal dir_idx
		await turtle.turn_left()
		dir_idx = (dir_idx + 3) % 4

	async def turn_right_local() -> None:
		nonlocal dir_idx
		await turtle.turn_right()
		dir_idx = (dir_idx + 1) % 4

	async def face_dir(target_idx: int) -> None:
		nonlocal dir_idx
		while dir_idx != target_idx:
			cw = (target_idx - dir_idx) % 4
			if cw == 1:
				await turn_right_local()
			elif cw == 2:
				await turn_right_local(); await turn_right_local()
			else:
				await turn_left_local()

	async def step_forward_local() -> bool:
		nonlocal pos
		ok = await force_dig_forward(turtle)
		if ok:
			pos = add_vec(pos, dir_vecs[dir_idx])
		return ok

	async def step_up_local() -> bool:
		nonlocal pos
		ok = await turtle.up()
		if ok:
			pos = (pos[0], pos[1]+1, pos[2])
		return ok

	async def step_down_local() -> bool:
		nonlocal pos
		ok = await turtle.down()
		if ok:
			pos = (pos[0], pos[1]-1, pos[2])
		return ok

	# Mining/bookkeeping
	mined: set[tuple[int,int,int]] = {pos}
	frontier: set[tuple[int,int,int]] = set()
	inspected: Dict[tuple[int,int,int], str | None] = {}
	max_actions = 2000
	if isinstance(config, dict):
		max_actions = config.get("max_actions", max_actions)
	actions = 0

	async def refresh_frontier_here() -> None:
		start = dir_idx
		# four horizontals
		for _ in range(4):
			adj = add_vec(pos, dir_vecs[dir_idx])
			name = inspected.get(adj)
			if name is None and adj not in inspected:
				ok, info = await turtle.inspect()
				name = str(info.get("name")) if ok else None
				inspected[adj] = name
			if is_ore(name) and adj not in mined:
				frontier.add(adj)
			await turn_right_local()
		while dir_idx != start:
			await turn_left_local()
		# up
		adj_u = (pos[0], pos[1]+1, pos[2])
		if adj_u not in inspected:
			ok_u, info_u = await turtle.inspect_up()
			inspected[adj_u] = str(info_u.get("name")) if ok_u else None
		if is_ore(inspected.get(adj_u)) and adj_u not in mined:
			frontier.add(adj_u)
		# down
		adj_d = (pos[0], pos[1]-1, pos[2])
		if adj_d not in inspected:
			ok_d, info_d = await turtle.inspect_down()
			inspected[adj_d] = str(info_d.get("name")) if ok_d else None
		if is_ore(inspected.get(adj_d)) and adj_d not in mined:
			frontier.add(adj_d)

	from collections import deque
	def bfs_path(start: tuple[int,int,int], goal: tuple[int,int,int]) -> list[tuple[int,int,int]] | None:
		if start == goal:
			return [start]
		q = deque([start])
		came: Dict[tuple[int,int,int], tuple[int,int,int] | None] = {start: None}
		neighbors = [(1,0,0),(-1,0,0),(0,0,1),(0,0,-1),(0,1,0),(0,-1,0)]
		while q:
			cur = q.popleft()
			if cur == goal:
				break
			for dv in neighbors:
				nxt = (cur[0]+dv[0], cur[1]+dv[1], cur[2]+dv[2])
				if nxt in mined and nxt not in came:
					came[nxt] = cur
					q.append(nxt)
		if goal not in came:
			return None
		path: list[tuple[int,int,int]] = []
		cur = goal
		while cur is not None:
			path.append(cur)
			cur = came[cur]
		path.reverse()
		return path

	def adjacent_mined_neighbors(target: tuple[int,int,int]) -> list[tuple[tuple[int,int,int], tuple[int,int,int], int]]:
		outs: list[tuple[tuple[int,int,int], tuple[int,int,int], int]] = []
		cands = [((1,0,0),0),((0,0,1),1),((-1,0,0),2),((0,0,-1),3),((0,1,0),-1),((0,-1,0),-1)]
		for dv, fdir in cands:
			adj = (target[0]-dv[0], target[1]-dv[1], target[2]-dv[2])
			if adj in mined:
				outs.append((adj, dv, fdir))
		return outs

	await refresh_frontier_here()

	while frontier and actions < max_actions:
		best: tuple[list[tuple[int,int,int]], tuple[int,int,int], tuple[int,int,int], int] | None = None
		for tgt in list(frontier):
			for adj, dv, fdir in adjacent_mined_neighbors(tgt):
				path = bfs_path(pos, adj)
				if path is None:
					continue
				if best is None or len(path) < len(best[0]):
					best = (path, tgt, dv, fdir)
		if best is None:
			turtle.logger.info(f"no reachable ore frontier; mined={len(mined)} frontier={len(frontier)}")
			break
		path, target, delta, face_idx = best
		for step in path[1:]:
			dv = (step[0]-pos[0], step[1]-pos[1], step[2]-pos[2])
			if dv == (0,1,0):
				await step_up_local()
			elif dv == (0,-1,0):
				await step_down_local()
			else:
				for i, v in enumerate(dir_vecs):
					if v == dv:
						await face_dir(i)
						break
				await step_forward_local()
			actions += 1
			if actions >= max_actions:
				break
		if actions >= max_actions:
			break
		if face_idx >= 0:
			await face_dir(face_idx)
			await turtle.dig(); await step_forward_local()
		else:
			if delta == (0,1,0):
				await turtle.dig_up(); await step_up_local()
			elif delta == (0,-1,0):
				await turtle.dig_down(); await step_down_local()
		mined.add(pos)
		frontier.discard(target)
		actions += 1
		await refresh_frontier_here()

	# Return home and realign
	if pos != start_pos:
		ph = bfs_path(pos, start_pos)
		if ph:
			for step in ph[1:]:
				dv = (step[0]-pos[0], step[1]-pos[1], step[2]-pos[2])
				if dv == (0,1,0):
					await step_up_local()
				elif dv == (0,-1,0):
					await step_down_local()
				else:
					for i, v in enumerate(dir_vecs):
						if v == dv:
							await face_dir(i)
							break
					await step_forward_local()
	await face_dir(start_dir_idx)
	turtle.logger.info("mine_ore_vein complete")


async def move_to_coordinate(turtle, config: dict = None) -> None:
	"""Move to specified coordinates with simple obstacle-aware pathing.
	
	Config expects: {"x": int, "y": int, "z": int}
	- Lifts to ~y=150 first to reduce collisions
	- Moves horizontally (x then z) with inspect/dig before each step
	- Finishes with vertical adjustment to target y
	- Uses an L1 distance-based step hold: max(500, 4*L1)
	"""
	if not isinstance(config, dict) or not {"x", "y", "z"}.issubset(config.keys()):
		turtle.logger.error("move_to_coordinate missing x/y/z in config")
		return
	
	# Get current position
	position = await turtle.get_location()
	if not position:
		turtle.logger.error("Could not get current position")
		return
	
	x, y, z = position
	tx, ty, tz = int(config["x"]), int(config["y"]), int(config["z"])
	
	# Get current heading from database
	def get_state() -> Dict[str, Any]:
		try:
			return db_state.get_state(turtle.session._turtle.id) or {}
		except Exception:
			return {}
	
	st = get_state()
	heading = st.get("heading") if isinstance(st.get("heading"), int) else 0
	dir_vecs: List[tuple[int,int,int]] = [(1,0,0),(0,0,1),(-1,0,0),(0,0,-1)]

	def l1(a: tuple[int,int,int], b: tuple[int,int,int]) -> int:
		return abs(a[0]-b[0]) + abs(a[1]-b[1]) + abs(a[2]-b[2])

	threshold = max(500, 4 * l1((x,y,z), (tx,ty,tz)))
	steps = 0

	async def face_dir(target_idx: int) -> None:
		nonlocal heading
		while heading != target_idx:
			cw = (target_idx - heading) % 4
			if cw == 1:
				await turtle.turn_right(); heading = (heading + 1) % 4
			elif cw == 2:
				await turtle.turn_right(); await turtle.turn_right(); heading = (heading + 2) % 4
			else:
				await turtle.turn_left(); heading = (heading + 3) % 4

	async def step_forward_checked() -> bool:
		nonlocal x, z, steps
		# Check for block ahead and dig if needed
		ok, _info = await turtle.inspect()
		if ok:
			await turtle.dig()
		
		# Clear headroom before moving
		ok_u, _ = await turtle.inspect_up()
		if ok_u:
			await turtle.dig_up()
		
		# Try to move forward
		if await turtle.forward():
			vx, _, vz = dir_vecs[heading]
			x += vx; z += vz
			
			# Clear headroom after moving
			ok_u2, _ = await turtle.inspect_up()
			if ok_u2:
				await turtle.dig_up()
			
			steps += 1
			return True
		
		# Try to go up to bypass obstacle
		ok_u_bypass, _ = await turtle.inspect_up()
		if ok_u_bypass:
			await turtle.dig_up()
		
		if await turtle.up():
			steps += 1
			if await step_forward_checked():
				# Come back down to resume height corridor
				await turtle.down(); steps += 1
				return True
			else:
				await turtle.down(); steps += 1
		
		# Try side-step: right then left
		await turtle.turn_right(); heading = (heading + 1) % 4
		ok_side, _ = await turtle.inspect()
		if ok_side:
			await turtle.dig()
		
		if await turtle.forward():
			vx, _, vz = dir_vecs[heading]; x += vx; z += vz; steps += 1
			await turtle.turn_left(); heading = (heading + 3) % 4
			return True
		
		await turtle.turn_left(); heading = (heading + 3) % 4
		return False

	async def step_vertical(to_up: bool) -> bool:
		nonlocal y, steps
		if to_up:
			ok_u, _ = await turtle.inspect_up()
			if ok_u:
				await turtle.dig_up()
			ok = await turtle.up()
			if ok: y += 1
		else:
			ok_d, _ = await turtle.inspect_down()
			if ok_d:
				await turtle.dig_down()
			ok = await turtle.down()
			if ok: y -= 1
		
		if ok:
			steps += 1
		return ok

	# Stage 1: lift to ~150 if below
	stage_y = 150
	while y < stage_y and steps < threshold:
		if not await step_vertical(True):
			break

	# Stage 2: move along X
	while x != tx and steps < threshold:
		dir_idx = 0 if tx > x else 2
		await face_dir(dir_idx)
		if not await step_forward_checked():
			# Try slight altitude change to bypass
			if not await step_vertical(True):
				await step_vertical(False)

	# Stage 3: move along Z
	while z != tz and steps < threshold:
		dir_idx = 1 if tz > z else 3
		await face_dir(dir_idx)
		if not await step_forward_checked():
			if not await step_vertical(True):
				await step_vertical(False)

	# Stage 4: adjust Y to target
	while y < ty and steps < threshold:
		if not await step_vertical(True):
			break
	while y > ty and steps < threshold:
		if not await step_vertical(False):
			break

	turtle.logger.info(f"move_to_coordinate finished at ({x},{y},{z}) target=({tx},{ty},{tz}) steps={steps} threshold={threshold}")


async def dig_to_coordinate(turtle, config: dict = None) -> None:
	"""Move in a straight path to target coordinates, digging blocks ahead.

	Config expects: {"x": int, "y": int, "z": int}.
	Order: X, then Z, then Y.
	"""

	# Get current position and heading from database
	st = db_state.get_state(turtle.session._turtle.id) or {}
	coords = st.get("coords") or {"x": 0, "y": 0, "z": 0}
	x, y, z = int(coords.get("x", 0)), int(coords.get("y", 0)), int(coords.get("z", 0))
	tx, ty, tz = int(config["x"]), int(config["y"]), int(config["z"])
	heading = st.get("heading", 0)

	async def face_direction(target_heading: int) -> None:
		"""Turn to face the target heading."""
		nonlocal heading
		while heading != target_heading:
			cw = (target_heading - heading) % 4
			if cw == 1:
				await turtle.turn_right()
				heading = (heading + 1) % 4
			elif cw == 2:
				await turtle.turn_right()
				await turtle.turn_right()
				heading = (heading + 2) % 4
			else:
				await turtle.turn_left()
				heading = (heading + 3) % 4
		# Update heading in database
		return heading

	# Move along X axis
	while x != tx:
		target_heading = 0 if tx > x else 2  # 0: +X, 2: -X
		heading = await face_direction(target_heading)
  
		if await turtle.force_dig_forward():
			x += 1 if tx > x else -1
		else:
			turtle.logger.warning("X movement blocked")
			break

	# Move along Z axis  
	while z != tz:
		target_heading = 1 if tz > z else 3  # 1: +Z, 3: -Z
		heading = await face_direction(target_heading)
		if await turtle.force_dig_forward():
			z += 1 if tz > z else -1
		else:
			turtle.logger.warning("Z movement blocked")
			break

	# Move along Y axis
	while y < ty:
		await turtle.dig_up()
		if await turtle.up():
			y += 1
		else:
			turtle.logger.warning("Y upward movement blocked")
			break
	
	while y > ty:
		await turtle.dig_down()
		if await turtle.down():
			y -= 1
		else:
			turtle.logger.warning("Y downward movement blocked")
			break

	turtle.logger.info(f"dig_to_coordinate finished at ({x},{y},{z}) target=({tx},{ty},{tz})")


async def dump_to_left_chest(turtle, config: dict = None) -> None:
	"""Place a chest to the left and dump all inventory into it (except chests).

	Config options:
	- chest_slot: int (default 1)
	"""
	chest_slot = 1
	if isinstance(config, dict):
		chest_slot = config.get("chest_slot", chest_slot)
	chest_slot = max(1, min(16, chest_slot))

	# Ensure chest slot selected and has items
	await turtle.select(chest_slot)
	count = await turtle.get_item_count()
	if not count or count <= 0:
		turtle.logger.warning(f"dump_to_left_chest: no chests in slot {chest_slot}")
		return

	# Turn left and place chest ahead; dig if blocked
	turtle.logger.info("dump_to_left_chest")
	await turtle.turn_left()
	ok, info = await turtle.inspect()
	if ok:
		await turtle.dig()
	
	placed = await turtle.place()
	await turtle.dig_up()
	await turtle.up()
	await turtle.dig()
	await turtle.down()
	
	if not placed:
		turtle.logger.warning("dump_to_left_chest: failed to place chest")
		await turtle.turn_right()
		return

	# Dump all items except chests slot
	for slot in range(1, 17):
		if slot == chest_slot:
			continue
		await turtle.select(slot)
		await turtle.drop()

	# Restore heading
	await turtle.turn_right()


async def force_dig_forward(turtle) -> bool:
	attempts = 0
	max_attempts = 20
	while attempts < max_attempts:
		if await turtle.forward():
			turtle.logger.debug(f"force_dig_forward: success after {attempts + 1} attempts")
			return True
		await turtle.dig()
		attempts += 1
	turtle.logger.warning(f"force_dig_forward: failed after {max_attempts} attempts")
	return False


def get_inventory_dump_subroutine(name: str):
	"""Return a dumping subroutine function by name."""
	if name == "dump_to_left_chest":
		return dump_to_left_chest
	# Add other dump strategies here as needed
	return dump_to_left_chest


async def do_something(turtle) -> None:
	await turtle.inspect_up()
	await turtle.up()
	await turtle.down()

	return
 
 
async def count_empty_slots(turtle) -> int:
	"""Count empty inventory slots."""
	try:
		# Get turtle ID from the session
		turtle_id = turtle.session._turtle.id
		st = db_state.get_state(turtle_id)
		inv = st.get("inventory")
			
		obj = json.loads(inv) if isinstance(inv, str) else inv
		if isinstance(obj, dict):
			# Count slots that are None (empty)
			return sum(1 for v in obj.values() if v is None)
	except Exception:
		logging.error("Error counting empty slots", exc_info=True)
		return 16  # If error, assume all slots are empty for safety


async def refuel_if_possible(turtle) -> None:
		"""Refuel if coal is available in inventory."""
		await turtle.get_inventory_details()
		inventory = json.loads(db_state.get_state(turtle.session._turtle.id).get("inventory"))

		for key, item in inventory.items():
			if not item:
				continue
			if item.get("name") == "minecraft:coal" and await turtle.get_fuel_level() < await turtle.get_fuel_limit()-5000:
				await turtle.select(int(key))
				await turtle.refuel(100000)
				continue

		if await turtle.get_fuel_level() < await turtle.get_fuel_limit() - 5000:
			logging.warning("Turtle could be losing fuel over time")
			return
		else:
			logging.info("Turtle fuel level is sufficient")
			return


# ============================================================================
# Basic Turtle Operation Wrappers
# ============================================================================
# These functions provide clean syntax for basic turtle operations in routines

# Movement operations
async def forward(turtle) -> bool:
	"""Move turtle forward one block."""
	return await turtle.session.forward()

async def back(turtle) -> bool:
	"""Move turtle backward one block."""
	return await turtle.session.back()

async def up(turtle) -> bool:
	"""Move turtle up one block."""
	return await turtle.session.up()

async def down(turtle) -> bool:
	"""Move turtle down one block."""
	return await turtle.session.down()

async def turn_left(turtle) -> bool:
	"""Turn turtle left 90 degrees."""
	return await turtle.session.turn_left()

async def turn_right(turtle) -> bool:
	"""Turn turtle right 90 degrees."""
	return await turtle.session.turn_right()

# Digging operations
async def dig(turtle) -> bool:
	"""Dig block in front of turtle."""
	return await turtle.session.dig()

async def dig_up(turtle) -> bool:
	"""Dig block above turtle."""
	return await turtle.session.dig_up()

async def dig_down(turtle) -> bool:
	"""Dig block below turtle."""
	return await turtle.session.dig_down()

# Placing operations
async def place(turtle) -> bool:
	"""Place block in front of turtle."""
	return await turtle.session.place()

async def place_up(turtle) -> bool:
	"""Place block above turtle."""
	return await turtle.session.place_up()

async def place_down(turtle) -> bool:
	"""Place block below turtle."""
	return await turtle.session.place_down()

# Item operations
async def select(turtle, slot: int) -> bool:
	"""Select inventory slot."""
	return await turtle.session.select(slot)

async def suck(turtle) -> bool:
	"""Suck items from in front."""
	return await turtle.session.suck()

async def suck_up(turtle) -> bool:
	"""Suck items from above."""
	return await turtle.session.suck_up()

async def suck_down(turtle) -> bool:
	"""Suck items from below."""
	return await turtle.session.suck_down()

async def drop(turtle, count: int = None) -> bool:
	"""Drop items in front."""
	return await turtle.session.drop(count)

async def drop_up(turtle, count: int = None) -> bool:
	"""Drop items above."""
	return await turtle.session.drop_up(count)

async def drop_down(turtle, count: int = None) -> bool:
	"""Drop items below."""
	return await turtle.session.drop_down(count)

# Inventory information
async def get_selected_slot(turtle) -> int:
	"""Get currently selected slot number."""
	return await turtle.session.get_selected_slot()

async def get_item_count(turtle) -> int:
	"""Get item count in selected slot."""
	return await turtle.session.get_item_count()

async def get_item_space(turtle) -> int:
	"""Get available space in selected slot."""
	return await turtle.session.get_item_space()

async def get_item_detail(turtle):
	"""Get details of item in selected slot."""
	return await turtle.session.get_item_detail()

# Comparison operations
async def compare(turtle) -> bool:
	"""Compare selected item with block in front."""
	return await turtle.session.compare()

async def compare_up(turtle) -> bool:
	"""Compare selected item with block above."""
	return await turtle.session.compare_up()

async def compare_down(turtle) -> bool:
	"""Compare selected item with block below."""
	return await turtle.session.compare_down()

async def compare_to(turtle, slot: int) -> bool:
	"""Compare selected item with item in specified slot."""
	return await turtle.session.compare_to(slot)

async def transfer_to(turtle, slot: int, count: int = None) -> bool:
	"""Transfer items to specified slot."""
	return await turtle.session.transfer_to(slot, count)

# Fuel operations
async def get_fuel_level(turtle):
	"""Get current fuel level."""
	return await turtle.session.get_fuel_level()

async def get_fuel_limit(turtle) -> int:
	"""Get maximum fuel capacity."""
	return await turtle.session.get_fuel_limit()

async def refuel(turtle, count: int) -> bool:
	"""Refuel using items from selected slot."""
	return await turtle.session.refuel(count)

# Equipment operations
async def equip_left(turtle) -> bool:
	"""Equip item from selected slot to left side."""
	return await turtle.session.equip_left()

async def equip_right(turtle) -> bool:
	"""Equip item from selected slot to right side."""
	return await turtle.session.equip_right()

# Inspection operations
async def inspect(turtle):
	"""Inspect block in front of turtle."""
	return await turtle.session.inspect()

async def inspect_up(turtle):
	"""Inspect block above turtle."""
	return await turtle.session.inspect_up()

async def inspect_down(turtle):
	"""Inspect block below turtle."""
	return await turtle.session.inspect_down()

# Location operations
async def get_location(turtle):
	"""Get current GPS coordinates."""
	return await turtle.session.get_location()

# Inventory operations
async def get_inventory_details(turtle):
	"""Get detailed inventory information."""
	return await turtle.session.get_inventory_details()

# Label operations
async def get_label(turtle):
	"""Get turtle's current label."""
	return await turtle.session.get_label()

async def set_label(turtle, label: str) -> bool:
	"""Set turtle's label."""
	return await turtle.session.set_label(label)

# Command operations
async def send_command(turtle, command: str) -> bool:
	"""Send a raw command to turtle."""
	return await turtle.session.send_command(command)

async def eval(turtle, code: str):
	"""Evaluate Lua code on turtle."""
	return await turtle.session.eval(code)