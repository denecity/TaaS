from __future__ import annotations

import re
import logging
from abc import ABC, abstractmethod
from typing import Any, Optional, Tuple

from backend.server import Turtle

logger = logging.getLogger("routines")


class Routine(ABC):
    """Base class for all routines.

    Subclasses should override `perform(session, config)` and implement the
    routine logic using the exclusive turtle session provided.
    """

    def __init__(self, name: Optional[str] = None, description: Optional[str] = None, config_template: Optional[str] = None) -> None:
        self.name: str = name or self._default_name()
        self.description: Optional[str] = description
        self.config_template: Optional[str] = config_template
        self._session: Optional[Turtle._Session] = None

    def _default_name(self) -> str:
        # Convert CamelCase -> snake_case as a sensible default
        cls = self.__class__.__name__
        s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", cls)
        return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower().replace("_routine", "")

    async def run(self, turtle: Turtle, config: Any | None = None) -> None:
        """Entry-point called by the orchestrator.

        Handles exclusive session acquisition and delegates to `perform` where
        the subclass implements the actual routine steps.
        """
        async with turtle.session() as session:
            self._session = session
            try:
                await self.perform(session, config)
            finally:
                self._session = None # Clear session after routine completes

    @abstractmethod
    async def perform(self, session: Turtle._Session, config: Any | None) -> None:  # noqa: N802
        """Implement the routine using the provided exclusive session.

        Avoid taking another session inside. Use the `session` methods to
        interact with the turtle.
        """
        raise NotImplementedError

    # Wrapper methods for common turtle commands
    async def forward(self) -> Tuple[bool, str | None]:
        if not self._session:
            raise RuntimeError("Routine session not established.")
        logger.info("Turtle %d: Executing command: turtle.forward()", self._session.turtle.id)
        result = await self._session.forward()
        logger.info("Turtle %d: Command turtle.forward() returned: %s", self._session.turtle.id, repr(result))
        return result

    async def back(self) -> Tuple[bool, str | None]:
        if not self._session:
            raise RuntimeError("Routine session not established.")
        logger.info("Turtle %d: Executing command: turtle.back()", self._session.turtle.id)
        result = await self._session.back()
        logger.info("Turtle %d: Command turtle.back() returned: %s", self._session.turtle.id, repr(result))
        return result

    async def up(self) -> Tuple[bool, str | None]:
        if not self._session:
            raise RuntimeError("Routine session not established.")
        logger.info("Turtle %d: Executing command: turtle.up()", self._session.turtle.id)
        result = await self._session.up()
        logger.info("Turtle %d: Command turtle.up() returned: %s", self._session.turtle.id, repr(result))
        return result

    async def down(self) -> Tuple[bool, str | None]:
        if not self._session:
            raise RuntimeError("Routine session not established.")
        logger.info("Turtle %d: Executing command: turtle.down()", self._session.turtle.id)
        result = await self._session.down()
        logger.info("Turtle %d: Command turtle.down() returned: %s", self._session.turtle.id, repr(result))
        return result

    async def turn_left(self) -> Tuple[bool, str | None]:
        if not self._session:
            raise RuntimeError("Routine session not established.")
        logger.info("Turtle %d: Executing command: turtle.turnLeft()", self._session.turtle.id)
        result = await self._session.turn_left()
        logger.info("Turtle %d: Command turtle.turnLeft() returned: %s", self._session.turtle.id, repr(result))
        return result

    async def turn_right(self) -> Tuple[bool, str | None]:
        if not self._session:
            raise RuntimeError("Routine session not established.")
        logger.info("Turtle %d: Executing command: turtle.turnRight()", self._session.turtle.id)
        result = await self._session.turn_right()
        logger.info("Turtle %d: Command turtle.turnRight() returned: %s", self._session.turtle.id, repr(result))
        return result

    async def dig(self) -> Tuple[bool, str | None]:
        if not self._session:
            raise RuntimeError("Routine session not established.")
        logger.info("Turtle %d: Executing command: turtle.dig()", self._session.turtle.id)
        result = await self._session.dig()
        logger.info("Turtle %d: Command turtle.dig() returned: %s", self._session.turtle.id, repr(result))
        return result

    async def dig_up(self) -> Tuple[bool, str | None]:
        if not self._session:
            raise RuntimeError("Routine session not established.")
        logger.info("Turtle %d: Executing command: turtle.digUp()", self._session.turtle.id)
        result = await self._session.dig_up()
        logger.info("Turtle %d: Command turtle.digUp() returned: %s", self._session.turtle.id, repr(result))
        return result

    async def dig_down(self) -> Tuple[bool, str | None]:
        if not self._session:
            raise RuntimeError("Routine session not established.")
        logger.info("Turtle %d: Executing command: turtle.digDown()", self._session.turtle.id)
        result = await self._session.dig_down()
        logger.info("Turtle %d: Command turtle.digDown() returned: %s", self._session.turtle.id, repr(result))
        return result

    async def place(self) -> Tuple[bool, str | None]:
        if not self._session:
            raise RuntimeError("Routine session not established.")
        logger.info("Turtle %d: Executing command: turtle.place()", self._session.turtle.id)
        result = await self._session.place()
        logger.info("Turtle %d: Command turtle.place() returned: %s", self._session.turtle.id, repr(result))
        return result

    async def place_up(self) -> Tuple[bool, str | None]:
        if not self._session:
            raise RuntimeError("Routine session not established.")
        logger.info("Turtle %d: Executing command: turtle.placeUp()", self._session.turtle.id)
        result = await self._session.place_up()
        logger.info("Turtle %d: Command turtle.placeUp() returned: %s", self._session.turtle.id, repr(result))
        return result

    async def place_down(self) -> Tuple[bool, str | None]:
        if not self._session:
            raise RuntimeError("Routine session not established.")
        logger.info("Turtle %d: Executing command: turtle.placeDown()", self._session.turtle.id)
        result = await self._session.place_down()
        logger.info("Turtle %d: Command turtle.placeDown() returned: %s", self._session.turtle.id, repr(result))
        return result

    async def suck(self) -> Tuple[bool, str | None]:
        if not self._session:
            raise RuntimeError("Routine session not established.")
        logger.info("Turtle %d: Executing command: turtle.suck()", self._session.turtle.id)
        result = await self._session.suck()
        logger.info("Turtle %d: Command turtle.suck() returned: %s", self._session.turtle.id, repr(result))
        return result

    async def suck_up(self) -> Tuple[bool, str | None]:
        if not self._session:
            raise RuntimeError("Routine session not established.")
        logger.info("Turtle %d: Executing command: turtle.suckUp()", self._session.turtle.id)
        result = await self._session.suck_up()
        logger.info("Turtle %d: Command turtle.suckUp() returned: %s", self._session.turtle.id, repr(result))
        return result

    async def suck_down(self) -> Tuple[bool, str | None]:
        if not self._session:
            raise RuntimeError("Routine session not established.")
        logger.info("Turtle %d: Executing command: turtle.suckDown()", self._session.turtle.id)
        result = await self._session.suck_down()
        logger.info("Turtle %d: Command turtle.suckDown() returned: %s", self._session.turtle.id, repr(result))
        return result

    async def drop(self, count: int | None = None) -> Tuple[bool, str | None]:
        if not self._session:
            raise RuntimeError("Routine session not established.")
        logger.info("Turtle %d: Executing command: turtle.drop(%s)", self._session.turtle.id, repr(count))
        result = await self._session.drop(count)
        logger.info("Turtle %d: Command turtle.drop(%s) returned: %s", self._session.turtle.id, repr(count), repr(result))
        return result

    async def drop_up(self, count: int | None = None) -> Tuple[bool, str | None]:
        if not self._session:
            raise RuntimeError("Routine session not established.")
        logger.info("Turtle %d: Executing command: turtle.dropUp(%s)", self._session.turtle.id, repr(count))
        result = await self._session.drop_up(count)
        logger.info("Turtle %d: Command turtle.dropUp(%s) returned: %s", self._session.turtle.id, repr(count), repr(result))
        return result

    async def drop_down(self, count: int | None = None) -> Tuple[bool, str | None]:
        if not self._session:
            raise RuntimeError("Routine session not established.")
        logger.info("Turtle %d: Executing command: turtle.dropDown(%s)", self._session.turtle.id, repr(count))
        result = await self._session.drop_down(count)
        logger.info("Turtle %d: Command turtle.dropDown(%s) returned: %s", self._session.turtle.id, repr(count), repr(result))
        return result

    async def select(self, slot: int) -> Tuple[bool, str | None]:
        if not self._session:
            raise RuntimeError("Routine session not established.")
        logger.info("Turtle %d: Executing command: turtle.select(%s)", self._session.turtle.id, repr(slot))
        result = await self._session.select(slot)
        logger.info("Turtle %d: Command turtle.select(%s) returned: %s", self._session.turtle.id, repr(slot), repr(result))
        return result

    async def get_selected_slot(self) -> Tuple[int, str | None]:
        if not self._session:
            raise RuntimeError("Routine session not established.")
        logger.info("Turtle %d: Executing command: turtle.getSelectedSlot()", self._session.turtle.id)
        result = await self._session.get_selected_slot()
        logger.info("Turtle %d: Command turtle.getSelectedSlot() returned: %s", self._session.turtle.id, repr(result))
        return result

    async def get_item_count(self, slot: int | None = None) -> Tuple[int, str | None]:
        if not self._session:
            raise RuntimeError("Routine session not established.")
        logger.info("Turtle %d: Executing command: turtle.getItemCount(%s)", self._session.turtle.id, repr(slot))
        result = await self._session.get_item_count(slot)
        logger.info("Turtle %d: Command turtle.getItemCount(%s) returned: %s", self._session.turtle.id, repr(slot), repr(result))
        return result

    async def get_item_space(self, slot: int | None = None) -> Tuple[int, str | None]:
        if not self._session:
            raise RuntimeError("Routine session not established.")
        logger.info("Turtle %d: Executing command: turtle.getItemSpace(%s)", self._session.turtle.id, repr(slot))
        result = await self._session.get_item_space(slot)
        logger.info("Turtle %d: Command turtle.getItemSpace(%s) returned: %s", self._session.turtle.id, repr(slot), repr(result))
        return result

    async def compare(self) -> Tuple[bool, str | None]:
        if not self._session:
            raise RuntimeError("Routine session not established.")
        logger.info("Turtle %d: Executing command: turtle.compare()", self._session.turtle.id)
        result = await self._session.compare()
        logger.info("Turtle %d: Command turtle.compare() returned: %s", self._session.turtle.id, repr(result))
        return result

    async def compare_up(self) -> Tuple[bool, str | None]:
        if not self._session:
            raise RuntimeError("Routine session not established.")
        logger.info("Turtle %d: Executing command: turtle.compareUp()", self._session.turtle.id)
        result = await self._session.compare_up()
        logger.info("Turtle %d: Command turtle.compareUp() returned: %s", self._session.turtle.id, repr(result))
        return result

    async def compare_down(self) -> Tuple[bool, str | None]:
        if not self._session:
            raise RuntimeError("Routine session not established.")
        logger.info("Turtle %d: Executing command: turtle.compareDown()", self._session.turtle.id)
        result = await self._session.compare_down()
        logger.info("Turtle %d: Command turtle.compareDown() returned: %s", self._session.turtle.id, repr(result))
        return result

    async def compare_to(self, slot: int) -> Tuple[bool, str | None]:
        if not self._session:
            raise RuntimeError("Routine session not established.")
        logger.info("Turtle %d: Executing command: turtle.compareTo(%s)", self._session.turtle.id, repr(slot))
        result = await self._session.compare_to(slot)
        logger.info("Turtle %d: Command turtle.compareTo(%s) returned: %s", self._session.turtle.id, repr(slot), repr(result))
        return result

    async def transfer_to(self, slot: int, count: int | None = None) -> Tuple[bool, str | None]:
        if not self._session:
            raise RuntimeError("Routine session not established.")
        logger.info("Turtle %d: Executing command: turtle.transferTo(%s, %s)", self._session.turtle.id, repr(slot), repr(count))
        result = await self._session.transfer_to(slot, count)
        logger.info("Turtle %d: Command turtle.transferTo(%s, %s) returned: %s", self._session.turtle.id, repr(slot), repr(count), repr(result))
        return result

    async def get_fuel_level(self) -> Tuple[int, str | None]:
        if not self._session:
            raise RuntimeError("Routine session not established.")
        logger.info("Turtle %d: Executing command: turtle.getFuelLevel()", self._session.turtle.id)
        value = await self._session.get_fuel_level()
        logger.info("Turtle %d: Command turtle.getFuelLevel() returned: %s", self._session.turtle.id, repr(value))
        return value, None

    async def get_fuel_limit(self) -> Tuple[int, str | None]:
        if not self._session:
            raise RuntimeError("Routine session not established.")
        logger.info("Turtle %d: Executing command: turtle.getFuelLimit()", self._session.turtle.id)
        result = await self._session.get_fuel_limit()
        logger.info("Turtle %d: Command turtle.getFuelLimit() returned: %s", self._session.turtle.id, repr(result))
        return result

    async def refuel(self, count: int | None = None) -> Tuple[bool, str | None]:
        if not self._session:
            raise RuntimeError("Routine session not established.")
        logger.info("Turtle %d: Executing command: turtle.refuel(%s)", self._session.turtle.id, repr(count))
        result = await self._session.refuel(count)
        logger.info("Turtle %d: Command turtle.refuel(%s) returned: %s", self._session.turtle.id, repr(count), repr(result))
        return result

    async def equip_left(self) -> Tuple[bool, str | None]:
        if not self._session:
            raise RuntimeError("Routine session not established.")
        logger.info("Turtle %d: Executing command: turtle.equipLeft()", self._session.turtle.id)
        result = await self._session.equip_left()
        logger.info("Turtle %d: Command turtle.equipLeft() returned: %s", self._session.turtle.id, repr(result))
        return result

    async def equip_right(self) -> Tuple[bool, str | None]:
        if not self._session:
            raise RuntimeError("Routine session not established.")
        logger.info("Turtle %d: Executing command: turtle.equipRight()", self._session.turtle.id)
        result = await self._session.equip_right()
        logger.info("Turtle %d: Command turtle.equipRight() returned: %s", self._session.turtle.id, repr(result))
        return result

    async def inspect(self) -> Tuple[bool, dict | None, str | None]:
        if not self._session:
            raise RuntimeError("Routine session not established.")
        logger.info("Turtle %d: Executing command: turtle.inspect()", self._session.turtle.id)
        result = await self._session.inspect()
        logger.info("Turtle %d: Command turtle.inspect() returned: %s", self._session.turtle.id, repr(result))
        return result

    async def inspect_up(self) -> Tuple[bool, dict | None, str | None]:
        if not self._session:
            raise RuntimeError("Routine session not established.")
        logger.info("Turtle %d: Executing command: turtle.inspectUp()", self._session.turtle.id)
        result = await self._session.inspect_up()
        logger.info("Turtle %d: Command turtle.inspectUp() returned: %s", self._session.turtle.id, repr(result))
        return result

    async def inspect_down(self) -> Tuple[bool, dict | None, str | None]:
        if not self._session:
            raise RuntimeError("Routine session not established.")
        logger.info("Turtle %d: Executing command: turtle.inspectDown()", self._session.turtle.id)
        result = await self._session.inspect_down()
        logger.info("Turtle %d: Command turtle.inspectDown() returned: %s", self._session.turtle.id, repr(result))
        return result

    async def get_position(self) -> Tuple[int, int, int, str | None]:
        if not self._session:
            raise RuntimeError("Routine session not established.")
        logger.info("Turtle %d: Executing command: turtle.getPosition()", self._session.turtle.id)
        result = await self._session.get_position()
        logger.info("Turtle %d: Command turtle.getPosition() returned: %s", self._session.turtle.id, repr(result))
        return result

    async def get_facing(self) -> Tuple[int, str | None]:
        if not self._session:
            raise RuntimeError("Routine session not established.")
        logger.info("Turtle %d: Executing command: turtle.getFacing()", self._session.turtle.id)
        result = await self._session.get_facing()
        logger.info("Turtle %d: Command turtle.getFacing() returned: %s", self._session.turtle.id, repr(result))
        return result


    async def get_inventory_detail(self) -> Tuple[dict, str | None]:
        if not self._session:
            raise RuntimeError("Routine session not established.")
        logger.info("Turtle %d: Executing command: turtle.getInventoryDetail()", self._session.turtle.id)
        result = await self._session.get_inventory_detail()
        logger.info("Turtle %d: Command turtle.getInventoryDetail() returned: %s", self._session.turtle.id, repr(result))
        return result
    
    async def get_location(self) -> Tuple[int, int, int, str | None]:
        if not self._session:
            raise RuntimeError("Routine session not established.")
        logger.info("Turtle %d: Executing command: gps.locate()", self._session.turtle.id)
        result = await self._session.get_location()
        logger.info("Turtle %d: Command gps.locate() returned: %s", self._session.turtle.id, repr(result))
        return result