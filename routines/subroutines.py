import logging
from typing import Any, Dict, List

from .base import Routine
from backend.server import Turtle
import backend.db_state as db_state

logger = logging.getLogger("subroutines")


async def mine_ore_vein(self: Routine, session: Turtle._Session, config: Any | None) -> None:
	"""Flood-fill mine any connected 'ore' vein in 6 directions (includes up/down).

	The turtle will pathfind over already mined cells to the nearest discovered ore,
	then return to the start and restore heading.
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
		await self.turn_left()
		dir_idx = (dir_idx + 3) % 4

	async def turn_right_local() -> None:
		nonlocal dir_idx
		await self.turn_right()
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
		ok = await self.forward()
		if ok:
			pos = add_vec(pos, dir_vecs[dir_idx])
		return ok

	async def step_up_local() -> bool:
		nonlocal pos
		ok = await self.up()
		if ok:
			pos = (pos[0], pos[1]+1, pos[2])
		return ok

	async def step_down_local() -> bool:
		nonlocal pos
		ok = await self.down()
		if ok:
			pos = (pos[0], pos[1]-1, pos[2])
		return ok

	# Mining/bookkeeping
	mined: set[tuple[int,int,int]] = {pos}
	frontier: set[tuple[int,int,int]] = set()
	inspected: Dict[tuple[int,int,int], str | None] = {}
	max_actions = int((config or {}).get("max_actions", 2000) if isinstance(config, dict) else 2000)
	actions = 0

	async def refresh_frontier_here() -> None:
		start = dir_idx
		# four horizontals
		for _ in range(4):
			adj = add_vec(pos, dir_vecs[dir_idx])
			name = inspected.get(adj)
			if name is None and adj not in inspected:
				ok, info = await self.inspect()
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
			ok_u, info_u = await session.inspect_up()
			inspected[adj_u] = str(info_u.get("name")) if ok_u else None
		if is_ore(inspected.get(adj_u)) and adj_u not in mined:
			frontier.add(adj_u)
		# down
		adj_d = (pos[0], pos[1]-1, pos[2])
		if adj_d not in inspected:
			ok_d, info_d = await session.inspect_down()
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
			logger.info("Turtle %d: no reachable ore frontier; mined=%d frontier=%d", session._turtle.id, len(mined), len(frontier))
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
			await self.dig(); await step_forward_local()
		else:
			if delta == (0,1,0):
				await self.dig_up(); await step_up_local()
			elif delta == (0,-1,0):
				await self.dig_down(); await step_down_local()
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
	logger.info("Turtle %d: mine_ore_vein complete", session._turtle.id)


async def move_to_coordinate(self: Routine, session: Turtle._Session, config: Any | None) -> None:
	"""Move to specified coordinates with simple obstacle-aware pathing.

	Config expects: {"x": int, "y": int, "z": int}. The routine:
	- Lifts to ~y=150 first to reduce collisions
	- Moves horizontally (x then z) with inspect/dig before each step
	- Finishes with vertical adjustment to target y
	- Uses an L1 distance-based step threshold: max(500, 4*L1)
	"""
	if not isinstance(config, dict) or not {"x", "y", "z"}.issubset(config.keys()):
		logger.error("Turtle %d: move_to_coordinate missing x/y/z in config", session._turtle.id)
		return

	def get_state() -> Dict[str, Any]:
		try:
			return db_state.get_state(session._turtle.id) or {}
		except Exception:
			return {}

	st = get_state()
	coords = st.get("coords") or {"x": 0, "y": 0, "z": 0}
	x, y, z = int(coords.get("x", 0)), int(coords.get("y", 0)), int(coords.get("z", 0))
	tx, ty, tz = int(config["x"]), int(config["y"]), int(config["z"])

	# Heading 0:+X, 1:+Z, 2:-X, 3:-Z
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
				await self.turn_right(); heading = (heading + 1) % 4
			elif cw == 2:
				await self.turn_right(); await self.turn_right(); heading = (heading + 2) % 4
			else:
				await self.turn_left(); heading = (heading + 3) % 4

	async def step_forward_checked() -> bool:
		nonlocal x, z, steps
		ok, _info = await self.inspect()
		if ok:
			await self.dig()
		# clear headroom before moving
		ok_u, _ = await session.inspect_up()
		if ok_u:
			await self.dig_up()
		ok2 = await self.forward()
		if ok2:
			vx, _, vz = dir_vecs[heading]
			x += vx; z += vz
			# clear headroom after moving
			ok_u2, _ = await session.inspect_up()
			if ok_u2:
				await self.dig_up()
			steps += 1
			return True
		# Try to go up to bypass obstacle
		ok_u, _up = await session.inspect_up()
		if ok_u:
			await self.dig_up()
		if await self.up():
			steps += 1
			ok2 = await step_forward_checked()
			if ok2:
				# come back down to resume height corridor
				await self.down(); steps += 1
				return True
			else:
				await self.down(); steps += 1
		# Try side-step: right then left
		await self.turn_right(); heading = (heading + 1) % 4
		ok_side, _ = await self.inspect()
		if ok_side:
			await self.dig()
		if await self.forward():
			vx,_,vz = dir_vecs[heading]; x += vx; z += vz; steps += 1
			await self.turn_left(); heading = (heading + 3) % 4
			return True
		await self.turn_left(); heading = (heading + 3) % 4
		return False

	async def step_vertical(to_up: bool) -> bool:
		nonlocal y, steps
		if to_up:
			ok_u, _ = await session.inspect_up()
			if ok_u:
				await self.dig_up()
			ok = await self.up()
			if ok: y += 1
		else:
			ok_d, _ = await session.inspect_down()
			if ok_d:
				await self.dig_down()
			ok = await self.down()
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
			# try slight altitude change to bypass
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

	logger.info("Turtle %d: move_to_coordinate finished at (%d,%d,%d) target=(%d,%d,%d) steps=%d threshold=%d",
				 session._turtle.id, x, y, z, tx, ty, tz, steps, threshold)


async def dig_to_coordinate(self: Routine, session: Turtle._Session, config: Any | None) -> None:
	"""Move in a straight L1 path to target coordinates, digging blocks ahead.

	Config expects: {"x": int, "y": int, "z": int}.
	Simplified vs move_to_coordinate: no detours or altitude staging; just inspect/dig then move.
	Order: X, then Z, then Y.
	"""
	if not isinstance(config, dict) or not {"x", "y", "z"}.issubset(config.keys()):
		logger.error("Turtle %d: dig_to_coordinate missing x/y/z in config", session._turtle.id)
		return

	def get_state() -> Dict[str, Any]:
		try:
			return db_state.get_state(session._turtle.id) or {}
		except Exception:
			return {}

	st = get_state()
	coords = st.get("coords") or {"x": 0, "y": 0, "z": 0}
	x, y, z = int(coords.get("x", 0)), int(coords.get("y", 0)), int(coords.get("z", 0))
	tx, ty, tz = int(config["x"]), int(config["y"]), int(config["z"])

	# Heading 0:+X, 1:+Z, 2:-X, 3:-Z
	heading = st.get("heading") if isinstance(st.get("heading"), int) else 0
	dir_vecs: List[tuple[int,int,int]] = [(1,0,0),(0,0,1),(-1,0,0),(0,0,-1)]

	async def face_dir(target_idx: int) -> None:
		nonlocal heading
		while heading != target_idx:
			cw = (target_idx - heading) % 4
			if cw == 1:
				await self.turn_right(); heading = (heading + 1) % 4
			elif cw == 2:
				await self.turn_right(); await self.turn_right(); heading = (heading + 2) % 4
			else:
				await self.turn_left(); heading = (heading + 3) % 4

	async def forward_dig_step() -> bool:
		nonlocal x, z
		ok, _info = await self.inspect()
		if ok:
			await self.dig()
		# clear headroom before moving
		ok_u, _ = await session.inspect_up()
		if ok_u:
			await self.dig_up()
		if await self.forward():
			vx, _, vz = dir_vecs[heading]
			x += vx; z += vz
			# clear headroom after moving
			ok_u2, _ = await session.inspect_up()
			if ok_u2:
				await self.dig_up()
			return True
		return False

	async def vertical_step(up: bool) -> bool:
		nonlocal y
		if up:
			ok_u, _ = await session.inspect_up()
			if ok_u:
				await self.dig_up()
			if await self.up():
				y += 1
				return True
			return False
		else:
			ok_d, _ = await session.inspect_down()
			if ok_d:
				await self.dig_down()
			if await self.down():
				y -= 1
				return True
			return False

	# Move along X directly
	while x != tx:
		dir_idx = 0 if tx > x else 2
		await face_dir(dir_idx)
		if not await forward_dig_step():
			logger.warning("Turtle %d: forward blocked during X traversal; stopping", session._turtle.id)
			break

	# Then Z directly
	while z != tz:
		dir_idx = 1 if tz > z else 3
		await face_dir(dir_idx)
		if not await forward_dig_step():
			logger.warning("Turtle %d: forward blocked during Z traversal; stopping", session._turtle.id)
			break

	# Finally adjust Y
	while y < ty:
		if not await vertical_step(True):
			logger.warning("Turtle %d: up blocked during Y ascent; stopping", session._turtle.id)
			break
	while y > ty:
		if not await vertical_step(False):
			logger.warning("Turtle %d: down blocked during Y descent; stopping", session._turtle.id)
			break

	logger.info("Turtle %d: dig_to_coordinate finished at (%d,%d,%d) target=(%d,%d,%d)",
				 session._turtle.id, x, y, z, tx, ty, tz)


async def update_inventory(self: Routine, session: Turtle._Session) -> List[Dict[str, Any]]:
	"""Fetch inventory details from firmware and store in DB; fallback if needed.

	Returns a list of non-empty slot entries if fallback path is used; otherwise
	returns an empty list (DB is updated regardless).
	"""
	try:
		inv = await session.eval("get_inventory_details()")
		import json as _json
		db_state.set_state(session._turtle.id, inventory_json=_json.dumps(inv))
		return []
	except Exception:
		# Fallback: iterate slots quickly without details
		items: List[Dict[str, Any]] = []
		for slot in range(1, 17):
			try:
				count, _ = await self.get_item_count(slot)
				if count and count > 0:
					items.append({"slot": slot, "count": int(count)})
			except Exception:
				pass
		import json as _json
		db_state.set_state(session._turtle.id, inventory_json=_json.dumps(items))
		return items


async def dump_to_left_chest(self: Routine, session: Turtle._Session, config: Any | None) -> None:
	"""Place a chest to the left and dump all inventory into it (except chests).

	Config options:
	- chest_slot: int (default 1)
	"""
	chest_slot = 1
	if isinstance(config, dict):
		try:
			chest_slot = int(config.get("chest_slot", chest_slot))
		except Exception:
			pass
	chest_slot = max(1, min(16, chest_slot))

	# Ensure chest slot selected and has items
	await self.select(chest_slot)
	count = await self.get_item_count(chest_slot)
	if not count or count <= 0:
		logger.warning("Turtle %d: dump_to_left_chest: no chests in slot %d", session._turtle.id, chest_slot)
		return

	# Turn left and place chest ahead; dig if blocked
	logger.info("Turtle %d: dump_to_left_chest", session._turtle.id)
	await self.turn_left()
	ok, info = await self.inspect()
	if ok:
		await self.dig()
	placed, _ = await self.place()
	await self.dig_up()
	await self.up()
	await self.dig()
	await self.down()
	if not placed:
		logger.warning("Turtle %d: dump_to_left_chest: failed to place chest", session._turtle.id)
		await self.turn_right()
		return

	# Dump all items except chests slot
	for slot in range(1, 17):
		if slot == chest_slot:
			continue
		await self.select(slot)
		await self.drop()

	# Restore heading
	await self.turn_right()


def get_inventory_dump_subroutine(name: str):
	"""Return a dumping subroutine function by name."""
	if name == "dump_to_left_chest":
		return dump_to_left_chest
	return dump_to_left_chest
