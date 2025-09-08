import importlib
import pkgutil
from typing import Dict

from .routine import RoutineWrapper, list_routines


def discover_routines() -> Dict[str, RoutineWrapper]:
    """Discover all routines with @routine decorator."""
    # Import all modules to trigger @routine decorators
    package = __name__
    for _, mod_name, _ in pkgutil.iter_modules(__path__):  # type: ignore[name-defined]
        if mod_name.startswith('_'):
            continue
        try:
            importlib.import_module(f"{package}.{mod_name}")
        except ImportError as e:
            # Skip modules that can't be imported
            continue
    
    # Return the registry populated by @routine decorators
    return list_routines()



