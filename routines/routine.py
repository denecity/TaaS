from __future__ import annotations

import logging
from typing import Any, Optional, Tuple, Set, Callable, Dict

from backend.server import Turtle

logger = logging.getLogger("routines")

Vec3 = Tuple[int, int, int]

# Global registry of routines
_routine_registry: Dict[str, 'RoutineWrapper'] = {}

# Import and bind subroutines
def _bind_subroutines():
    """Automatically bind all subroutines."""
    try:
        from . import subroutines
        return subroutines
    except ImportError:
        logger.warning("No subroutines module found")
        return None

class RoutineWrapper:
    """Simple wrapper for routine functions."""
    
    def __init__(self, func: Callable, name: str = None, label: str = None, config_template: str = None):
        self.func = func
        self.name = name or func.__name__.replace("_routine", "").replace("routine_", "")
        self.label = label or self.name.replace("_", " ").title()
        self.config_template = config_template
        self.logger = logging.getLogger(f"routine.{self.name}")
        
        # Bind subroutines
        self.subroutines = _bind_subroutines()
    
    async def run(self, turtle: Turtle, config: Any | None = None) -> None:
        """Run the routine with session management."""
        async with turtle.session() as session:
            # Create turtle wrapper with subroutines bound
            turtle_wrapper = TurtleWrapper(session, self.logger, self.subroutines)
            try:
                await self.func(turtle_wrapper, config)
            except Exception as e:
                self.logger.error(f"Routine failed: {e}")
                raise

class TurtleWrapper:
    """Turtle wrapper that binds subroutines."""
    
    def __init__(self, session: Turtle._Session, logger: logging.Logger, subroutines=None):
        self.session = session
        self.logger = logger
        
        # Bind all session methods
        for attr_name in dir(session):
            if not attr_name.startswith('_') and callable(getattr(session, attr_name)):
                setattr(self, attr_name, getattr(session, attr_name))
                
        # Bind subroutines if available
        if subroutines:
            for attr_name in dir(subroutines):
                if not attr_name.startswith('_') and callable(getattr(subroutines, attr_name)):
                    # Bind subroutine with session as first argument
                    subroutine_func = getattr(subroutines, attr_name)
                    def make_bound_subroutine(func):
                        async def bound_subroutine(*args, **kwargs):
                            return await func(self, *args, **kwargs)
                        return bound_subroutine
                    setattr(self, attr_name, make_bound_subroutine(subroutine_func))

# Simple decorator for defining routines
def routine(name: str = None, label: str = None, config_template: str = None):
    """Decorator to register a function as a routine."""
    def decorator(func: Callable):
        routine_name = name or func.__name__
        wrapper = RoutineWrapper(func, routine_name, label, config_template)
        _routine_registry[routine_name] = wrapper
        return wrapper
    return decorator

# Function to get routines
def get_routine(name: str) -> Optional[RoutineWrapper]:
    """Get a routine by name."""
    return _routine_registry.get(name)

def list_routines() -> Dict[str, RoutineWrapper]:
    """Get all registered routines."""
    return _routine_registry.copy()


