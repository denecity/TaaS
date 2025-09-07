import logging
from collections import deque
from typing import Any, Dict, List, Optional, Set, Tuple

from .base import Routine
from server import Turtle


Vec3 = Tuple[int, int, int]


class AvoidGoldDigDiamondRoutine(Routine):
	def __init__(self) -> None:
		super().__init__(
			description="BFS frontier miner for connected diamond clusters; avoids configured blocks; explores up/down",
			config_template="""
# Blocks to mine as part of the cluster
# Add modded ore/block ids as needed
targets:
  - minecraft:diamond_block
# Blocks to explicitly avoid (never mine into)
avoid:
  - minecraft:gold_block
# Safety limit on number of actions (moves/digs)
max_actions: 1500
"""
		)

	async def perform(self, session: Turtle._Session, config: Any | None) -> None:
		logger = logging.getLogger("routine.avoid_gold_dig_diamond")
		# Parse config
		targets: Set[str] = {"minecraft:diamond_block"}
		avoid: Set[str] = {"minecraft:gold_block"}
		max_actions = 1500
		if isinstance(config, dict):
			try:
				cfg_targets = config.get("targets")
				if isinstance(cfg_targets, list):
					targets = {str(x) for x in cfg_targets}
				cfg_avoid = config.get("avoid")
				if isinstance(cfg_avoid, list):
					avoid = {str(x) for x in cfg_avoid}
				ma = config.get("max_actions")
				if ma is not None:
					max_actions = int(ma)
			except Exception:
				pass

		# Local coordinate and heading tracking
		# Heading indices: 0:+X, 1:+Z, 2:-X, 3:-Z
		dir_idx = 0
		start_dir_idx = dir_idx
		dir_vecs: List[Vec3] = [(1, 0, 0), (0, 0, 1), (-1, 0, 0), (0, 0, -1)]
		pos: Vec3 = (0, 0, 0)
		start_pos: Vec3 = pos

		def add_vec(a: Vec3, b: Vec3) -> Vec3:
			return (a[0] + b[0], a[1] + b[1], a[2] + b[2])

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
				# choose shortest rotation
				cw = (target_idx - dir_idx) % 4
				if cw == 1:
					await turn_right_local()
				elif cw == 2:
					await turn_right_local()
					await turn_right_local()
				else:
					await turn_left_local()

		async def step_forward_local() -> bool:
			nonlocal pos
			ok = await self.forward()
			if ok:
				vec = dir_vecs[dir_idx]
				pos = add_vec(pos, vec)
			return ok

		async def step_up_local() -> bool:
			nonlocal pos
			ok = await self.up()
			if ok:
				pos = (pos[0], pos[1] + 1, pos[2])
			return ok

		async def step_down_local() -> bool:
			nonlocal pos
			ok = await self.down()
			if ok:
				pos = (pos[0], pos[1] - 1, pos[2])
			return ok

		# Mining state
		mined: Set[Vec3] = {pos}
		frontier: Set[Vec3] = set()
		# Cache of inspections: position -> block name (or None if empty/unknown)
		inspected: Dict[Vec3, Optional[str]] = {}
		actions = 0

		# Utility: explore surroundings and add target neighbors to frontier (uses cache)
		async def refresh_frontier_here() -> None:
			start_dir = dir_idx
			# Horizontal 4 directions
			for i in range(4):
				adj = add_vec(pos, dir_vecs[dir_idx])
				name: Optional[str]
				if adj in inspected:
					name = inspected[adj]
				else:
					ok, info = await self.inspect()
					if ok:
						name = str(info.get("name"))
						inspected[adj] = name
					else:
						name = None
						inspected[adj] = None
				if name and name in targets and name not in avoid and adj not in mined:
					frontier.add(adj)
				await turn_right_local()
			# restore heading
			while dir_idx != start_dir:
				await turn_left_local()
			# Up
			adj_u = (pos[0], pos[1] + 1, pos[2])
			if adj_u in inspected:
				name_u = inspected[adj_u]
			else:
				ok_u, info_u = await self.inspect_up()
				if ok_u:
					name_u = str(info_u.get("name"))
					inspected[adj_u] = name_u
				else:
					name_u = None
					inspected[adj_u] = None
			if name_u and name_u in targets and name_u not in avoid and adj_u not in mined:
				frontier.add(adj_u)
			# Down
			adj_d = (pos[0], pos[1] - 1, pos[2])
			if adj_d in inspected:
				name_d = inspected[adj_d]
			else:
				ok_d, info_d = await self.inspect_down()
				if ok_d:
					name_d = str(info_d.get("name"))
					inspected[adj_d] = name_d
				else:
					name_d = None
					inspected[adj_d] = None
			if name_d and name_d in targets and name_d not in avoid and adj_d not in mined:
				frontier.add(adj_d)

		# BFS pathfinding over mined cells
		def bfs_path(start: Vec3, goal: Vec3) -> Optional[List[Vec3]]:
			if start == goal:
				return [start]
			q = deque([start])
			came: Dict[Vec3, Optional[Vec3]] = {start: None}
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
			# reconstruct from goal to start
			path: List[Vec3] = []
			cur: Optional[Vec3] = goal
			while cur is not None:
				path.append(cur)
				cur = came[cur]
			path.reverse()
			return path

		# From a frontier target position, pick an adjacent mined cell to stand on
		def adjacent_mined_neighbors(target: Vec3) -> List[Tuple[Vec3, Vec3, int]]:
			# returns list of tuples: (neighbor_cell, delta, facing_dir_idx_if_horizontal)
			outs: List[Tuple[Vec3, Vec3, int]] = []
			candidates = [((1,0,0),0), ((0,0,1),1), ((-1,0,0),2), ((0,0,-1),3), ((0,1,0),-1), ((0,-1,0),-1)]
			for dv, fdir in candidates:
				adj = (target[0]-dv[0], target[1]-dv[1], target[2]-dv[2])
				if adj in mined:
					outs.append((adj, dv, fdir))
			return outs

		# Initial discovery
		await refresh_frontier_here()

		while frontier and actions < max_actions:
			# Choose nearest frontier target by BFS distance
			best: Optional[Tuple[List[Vec3], Vec3, Vec3, int]] = None  # (path_to_adjacent, target, delta, face_dir_idx)
			for tgt in list(frontier):
				adjs = adjacent_mined_neighbors(tgt)
				for adj, dv, fdir in adjs:
					path = bfs_path(pos, adj)
					if path is None:
						continue
					if best is None or len(path) < len(best[0]):
						best = (path, tgt, dv, fdir)
			if best is None:
				# unreachable with current mined set; log and break
				logger.info("Turtle %d: no reachable frontier; mined=%d frontier=%d", session._turtle.id, len(mined), len(frontier))
				break

			path, target, delta, face_idx = best
			# Follow path (skip first, which is current pos)
			for step in path[1:]:
				# Determine move vector
				dv = (step[0]-pos[0], step[1]-pos[1], step[2]-pos[2])
				if dv == (0,1,0):
					await step_up_local()
				elif dv == (0,-1,0):
					await step_down_local()
				else:
					# horizontal move: face dv
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

			# Now at adjacent mined cell; mine into target
			# Face correct direction for horizontal target
			if face_idx >= 0:
				await face_dir(face_idx)
				await self.dig()
				await step_forward_local()
			else:
				# Vertical target
				if delta == (0,1,0):
					await self.dig_up()
					await step_up_local()
				elif delta == (0,-1,0):
					await self.dig_down()
					await step_down_local()
			# Mark newly mined position and refresh frontier
			mined.add(pos)
			# Mined block now empty -> update cache
			inspected[pos] = None
			frontier.discard(target)
			actions += 1
			await refresh_frontier_here()

		logger.info("Turtle %d: BFS cluster mining done. actions=%d mined=%d pending_frontier=%d", session._turtle.id, actions, len(mined), len(frontier))
		# Return to start and realign heading
		if pos != start_pos:
			path_home = bfs_path(pos, start_pos)
			if path_home:
				for step in path_home[1:]:
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
					if actions < max_actions:
						actions += 1
		# Final heading
		await face_dir(start_dir_idx)
		logger.info("Turtle %d: Returned to start and realigned. pos=%s dir=%d", session._turtle.id, start_pos, start_dir_idx)
