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
        self.session: Optional[Turtle.session] = None

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
            self.session = session
            try:
                await self.perform(session, config)
            finally:
                self.session = None # Clear session after routine completes

    @abstractmethod
    async def perform(self, session: Turtle.session, config: Any | None) -> None:  # noqa: N802
        """Implement the routine using the provided exclusive session.

        Avoid taking another session inside. Use the `session` methods to
        interact with the turtle.
        """
        raise NotImplementedError