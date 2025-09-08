import importlib
import pkgutil
from typing import Dict

from .routine import Routine


def discover_routines() -> Dict[str, Routine]:
    registry: Dict[str, Routine] = {}
    package = __name__
    for _, mod_name, _ in pkgutil.iter_modules(__path__):  # type: ignore[name-defined]
        if mod_name.startswith('_'):
            continue
        module = importlib.import_module(f"{package}.{mod_name}")
        for attr in dir(module):
            obj = getattr(module, attr)
            if isinstance(obj, type) and issubclass(obj, Routine) and obj is not Routine:
                inst: Routine = obj()  # type: ignore[call-arg]
                registry[inst.name] = inst
    return registry



