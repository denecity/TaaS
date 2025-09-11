import logging
from typing import Any, Dict, List, Tuple

from backend import turtle

from .routine import routine
import backend.db_state as db_state


def dig_calculation(start_x, start_z, width, height) -> list:
    starting_points = []
    for i in range(int((height + width))):
        starting_points.append([-1 * i, 3 * i])
        
    points = []
    for start in starting_points:
        for i in range(int((height + width))):
            curr_x = start[0] + 2 * i
            curr_y = start[1] - i
            points.append([curr_x, curr_y])
            
    valid_points = []
    ext_allowed_area = [[-1, -1], [width, height]]
    for point in points:
        if point[0] >= ext_allowed_area[0][0] and point[0] <= ext_allowed_area[1][0] and point[1] >= ext_allowed_area[0][1] and point[1] <= ext_allowed_area[1][1]:
            valid_points.append(point)
            
    fixed_points = []

    point_class = [] # 1: moved, 2: corner, 3: edge, 4: inside
    edge_direction = [] # 0: no edge, 1: top, 2: right, 3: bottom, 4: left; checks for moved or edge points on which edge they are
    corner_direction = [] # 0: not corner, 1: bottom-left, 2: top-left, 3: top-right, 4: bottom-right
    real_allowed_area = [[0, 0], [width-1, height-1]]
    for point in valid_points:
        if point[0] < real_allowed_area[0][0]:
            point_class.append(1)
            fixed_points.append([point[0] + 1, point[1]])
            edge_direction.append(4)
            corner_direction.append(0)  # Not a corner
        elif point[1] < real_allowed_area[0][1]:
            point_class.append(1)
            fixed_points.append([point[0], point[1] + 1])
            edge_direction.append(3)
            corner_direction.append(0)  # Not a corner
        elif point[0] > real_allowed_area[1][0]:
            point_class.append(1)
            fixed_points.append([point[0] - 1, point[1]])
            edge_direction.append(2)
            corner_direction.append(0)  # Not a corner
        elif point[1] > real_allowed_area[1][1]:
            point_class.append(1)
            fixed_points.append([point[0], point[1] - 1])
            edge_direction.append(1)
            corner_direction.append(0)  # Not a corner
        else:
            fixed_points.append(point)
            if point[0] == real_allowed_area[0][0] or point[0] == real_allowed_area[1][0]:
                if point[1] == real_allowed_area[0][1] or point[1] == real_allowed_area[1][1]:
                    point_class.append(2)
                    edge_direction.append(0)  # No direction for corner points
                    
                    # Determine which corner
                    if point[0] == real_allowed_area[0][0] and point[1] == real_allowed_area[0][1]:
                        corner_direction.append(1)  # Bottom-left corner
                    elif point[0] == real_allowed_area[0][0] and point[1] == real_allowed_area[1][1]:
                        corner_direction.append(2)  # Top-left corner
                    elif point[0] == real_allowed_area[1][0] and point[1] == real_allowed_area[1][1]:
                        corner_direction.append(3)  # Top-right corner
                    else:  # point[0] == real_allowed_area[1][0] and point[1] == real_allowed_area[0][1]
                        corner_direction.append(4)  # Bottom-right corner
                else:
                    point_class.append(3)
                    # Determine which edge
                    if point[0] == real_allowed_area[0][0]:
                        edge_direction.append(4)  # Left edge
                    else:  # point[0] == real_allowed_area[1][0]
                        edge_direction.append(2)  # Right edge
                    corner_direction.append(0)  # Not a corner
            elif point[1] == real_allowed_area[0][1] or point[1] == real_allowed_area[1][1]:
                point_class.append(3)
                # Determine which edge
                if point[1] == real_allowed_area[0][1]:
                    edge_direction.append(3)  # Bottom edge
                else:  # point[1] == real_allowed_area[1][1]
                    edge_direction.append(1)  # Top edge
                corner_direction.append(0)  # Not a corner
            else:
                point_class.append(4)
                edge_direction.append(0)  # No direction for inside points
                corner_direction.append(0)  # Not a corner
                
    for i in range(len(fixed_points)):
        fixed_points[i][0] += start_x
        fixed_points[i][1] += start_z
                
    return fixed_points, point_class, edge_direction, corner_direction


@routine(
    label="Smart Full Miner",
    config_template="""
# Auto chunk mining configuration
corner_1: [296, 9]  # (x, z) of one corner of the area to mine
corner_2: [315, -11]  # (x, z) of the opposite corner of the area to mine
start_y: 63
stop_y: -20
empty_slots_threshold: 4
chest_slot: 1
dump_strategy: dump_to_ender_chest
"""
)
async def smart_mine_full_routine(turtle, config):
    # Config parsing with defaults
    corner_1 = config.get("corner_1", [0, 0])
    corner_2 = config.get("corner_2", [15, 15])
    start_y = config.get("start_y", 50)
    stop_y = config.get("stop_y", 20)
    empty_slots_threshold = config.get("empty_slots_threshold", 4)
    chest_slot = config.get("chest_slot", 1)
    dump_strategy = config.get("dump_strategy", "dump_to_left_chest")
    
    bottom_left_corner = [min(corner_1[0], corner_2[0]), min(corner_1[1], corner_2[1])]
    top_right_corner = [max(corner_1[0], corner_2[0]), max(corner_1[1], corner_2[1])]
    width = top_right_corner[0] - bottom_left_corner[0] + 1
    height = top_right_corner[1] - bottom_left_corner[1] + 1
    
    fixed_points, point_class, edge_direction, corner_direction = dig_calculation(bottom_left_corner[0], bottom_left_corner[1], width, height)
    
    logging.getLogger("turtle").info(f"Starting smart full mining from Y={start_y} to Y={stop_y} in area from {bottom_left_corner} to {top_right_corner} (width={width}, height={height})")
    logging.getLogger("turtle").info(f" Points: {fixed_points}, Classes: {point_class}, Edges: {edge_direction}, Corners: {corner_direction}")
    
    logging.getLogger("turtle").info(f"Calculated {len(fixed_points)} dig points for area from {bottom_left_corner} to {top_right_corner}")
    
    async def checks_and_breaks(turtle, dump_strategy):
        """Perform checks and breaks as needed."""
        try:
            await turtle.refuel_if_possible()
            empty_slots = await turtle.count_empty_slots()
            if empty_slots <= empty_slots_threshold:
                if dump_strategy == "dump_to_left_chest":
                    logging.getLogger("turtle").info("Inventory low on space, dumping to left chest")
                    await turtle.dump_to_left_chest(chest_slot)
                elif dump_strategy == "dump_to_ender_chest":
                    logging.getLogger("turtle").info("Inventory low on space, dumping to ender chest")
                    await turtle.dump_to_ender_chest()
                else:
                    turtle.logger.warning(f"Unknown dump strategy: {dump_strategy}")
        except Exception as e:
            turtle.logger.warning(f"Checks and breaks failed: {e}")
        return
    
    async def dig_in_cross_pattern(turtle, point_class_i, edge_direction_i, corner_direction_i):
        """Dig in a specific cross pattern based on the type.
        Cross: dig forward, left, right, back
        T North: forward, left, right
        T East: left, forward, back
        T South: right, back, left
        T West: back, right, forward
        L Bottom-Left: forward, right
        L Top-Left: right, back
        L Top-Right: back, left
        L Bottom-Right: left, forward
        Moved: pass
                        
        point_class: 1: moved, 2: corner, 3: edge, 4: inside
        edge_direction:  0: no edge, 1: top, 2: right, 3: bottom, 4: left; checks for moved or edge points on which edge they are
        corner_direction:  0: not corner, 1: bottom-left, 2: top-left, 3: top-right, 4: bottom-right
        """
        
        if point_class_i == 1:  # Moved point
            return
        elif point_class_i == 4:  # Inside point
            logging.getLogger("turtle").info("Digging in cross pattern for inside point")
            await turtle.dig()
            await turtle.turn_left()
            await turtle.dig()
            await turtle.turn_left()
            await turtle.dig()
            await turtle.turn_left()
            await turtle.dig()
            await turtle.turn_left()
            return
        elif point_class_i == 3:  # Edge point
            if edge_direction_i == 2:  # Top edge
                logging.getLogger("turtle").info("Digging in T pattern for top edge")
                await turtle.turn_right()
                await turtle.dig()
                await turtle.turn_right()
                await turtle.dig()
                await turtle.turn_right()
                await turtle.dig()
                await turtle.turn_right()
                return
            elif edge_direction_i == 1:  # Right edge
                logging.getLogger("turtle").info("Digging in T pattern for right edge")
                await turtle.dig()
                await turtle.turn_left()
                await turtle.dig()
                await turtle.turn_left()
                await turtle.dig()
                await turtle.turn_left()
                await turtle.turn_left()
                return
            elif edge_direction_i == 4:  # Bottom edge
                logging.getLogger("turtle").info("Digging in T pattern for bottom edge")
                await turtle.turn_left()
                await turtle.dig()
                await turtle.turn_right()
                await turtle.dig()
                await turtle.turn_right()
                await turtle.dig()
                await turtle.turn_left()
                return
            elif edge_direction_i == 3:  # Left edge
                logging.getLogger("turtle").info("Digging in T pattern for left edge")
                await turtle.dig()
                await turtle.turn_right()
                await turtle.dig()
                await turtle.turn_right()
                await turtle.dig()
                await turtle.turn_right()
                await turtle.turn_right()
                return
        elif point_class_i == 2:  # Corner point
            if corner_direction_i == 1:  # Bottom-left corner
                logging.getLogger("turtle").info("Digging in L pattern for bottom-left corner")
                await turtle.dig()
                await turtle.turn_right()
                await turtle.dig()
                await turtle.turn_left()
                return
            elif corner_direction_i == 4:  # Top-left corner
                logging.getLogger("turtle").info("Digging in L pattern for top-left corner")
                await turtle.turn_right()
                await turtle.dig()
                await turtle.turn_right()
                await turtle.dig()
                await turtle.turn_left()
                await turtle.turn_left()
                return
            elif corner_direction_i == 3:  # Top-right corner
                logging.getLogger("turtle").info("Digging in L pattern for top-right corner")
                await turtle.turn_left()
                await turtle.dig()
                await turtle.turn_left()
                await turtle.dig()
                await turtle.turn_right()
                await turtle.turn_right()
                return
            elif corner_direction_i == 2:  # Bottom-right corner
                logging.getLogger("turtle").info("Digging in L pattern for bottom-right corner")
                await turtle.dig()
                await turtle.turn_left()
                await turtle.dig()
                await turtle.turn_right()
                return
        else:
            turtle.logger.warning(f"Unknown point class: {point_class_i}")
            return            
                 
    async def dig_chute(turtle, top_or_bottom, start_y, stop_y, point_class_i, edge_direction_i, corner_direction_i):
        """Dig a chute from start_y to stop_y based on point classification.
        before calling dig_in_cross_pattern make absolutely sure that turtle is north facing (heading=3, -Z direction)
        """
        
        await turtle.set_heading(0)  # Face east (heading=0, -Z direction)
        
        if top_or_bottom == 1:  # Top -> Bottom
            logging.getLogger("turtle").info(f"Turtle is at top. Digging down {start_y-stop_y} times")
            print("start_y, stop_y:", start_y, stop_y)
            for step in range(start_y-stop_y):
                await dig_in_cross_pattern(turtle, point_class_i, edge_direction_i, corner_direction_i)
                await checks_and_breaks(turtle, dump_strategy)
                await turtle.dig_down()
                await turtle.down()
            await dig_in_cross_pattern(turtle, point_class_i, edge_direction_i, corner_direction_i)
            await checks_and_breaks(turtle, dump_strategy)
            return
        elif top_or_bottom == 2:  # Bottom -> Top
            logging.getLogger("turtle").info(f"Turtle is at bottom. Digging up {start_y-stop_y} times")
            print("start_y, stop_y:", start_y, stop_y)
            for step in range(start_y-stop_y):
                await dig_in_cross_pattern(turtle, point_class_i, edge_direction_i, corner_direction_i)
                await checks_and_breaks(turtle, dump_strategy)
                await turtle.dig_up()
                await turtle.up()
            await dig_in_cross_pattern(turtle, point_class_i, edge_direction_i, corner_direction_i)
            await checks_and_breaks(turtle, dump_strategy)
            return
                
        
    # Move to starting position
    await turtle.get_location()
    
    await turtle.dig_to_coordinate({"x": bottom_left_corner[0], "y": start_y, "z": bottom_left_corner[1]})
    
    top_or_bottom = 1  # 1: top, 2: bottom
    for i_chute in range(len(fixed_points)):
        curr_chute_x = fixed_points[i_chute][0]
        curr_chute_z = fixed_points[i_chute][1]
        
        if top_or_bottom == 1:
            logging.getLogger("turtle").info(f"Starting chute {i_chute + 1}/{len(fixed_points)} at ({curr_chute_x}, {start_y}, {curr_chute_z})")
            await turtle.dig_to_coordinate({"x": curr_chute_x, "y": start_y, "z": curr_chute_z})
            await dig_chute(turtle, top_or_bottom, start_y, stop_y, point_class[i_chute], edge_direction[i_chute], corner_direction[i_chute])
            top_or_bottom = 2
        elif top_or_bottom == 2:
            logging.getLogger("turtle").info(f"Starting chute {i_chute + 1}/{len(fixed_points)} at ({curr_chute_x}, {stop_y}, {curr_chute_z})")
            await turtle.dig_to_coordinate({"x": curr_chute_x, "y": stop_y, "z": curr_chute_z})
            await dig_chute(turtle, top_or_bottom, start_y, stop_y, point_class[i_chute], edge_direction[i_chute], corner_direction[i_chute])
            top_or_bottom = 1
    
    logging.getLogger("turtle").info("Full rectangle mining completed")
    return
    
    
    
    
    
    