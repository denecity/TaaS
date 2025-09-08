import logging
from typing import Any

from .routine import Routine
from backend.server import Turtle

logger = logging.getLogger("routine.execute_command")

class ExecuteCommandRoutine(Routine):
    def __init__(self) -> None:
        super().__init__(
            description="Execute a single turtle command from config",
            config_template="""
command: forward # Example: forward, turn_left, select 1, drop 10, get_inventory_details, set_name_tag("Turtle")
"""
        )

    async def perform(self, session: Turtle._Session, config: Any | None) -> None:
        logger = logging.getLogger("routine.execute_command")
        if not isinstance(config, dict) or "command" not in config:
            logger.error("Turtle %d: Missing 'command' in config for ExecuteCommandRoutine", session._turtle.id)
            return

        command_string = str(config["command"]).strip()
        logger.info("Turtle %d: Attempting to execute command: %s", session._turtle.id, command_string)

        # Raw eval if it looks like an expression with parentheses
        if "(" in command_string and ")" in command_string:
            try:
                res = await session.eval(command_string)
                logger.info("Turtle %d: Eval result: %s", session._turtle.id, repr(res))
                return
            except Exception as e:
                logger.error("Turtle %d: Eval failed for '%s': %s", session._turtle.id, command_string, e)
                return

        # Basic parsing: command name followed by optional arguments (space-separated)
        parts = command_string.split(" ")
        method_name = parts[0]
        args_str = parts[1:]

        # Convert string arguments to appropriate types (e.g., int)
        parsed_args = []
        for arg in args_str:
            try:
                parsed_args.append(int(arg))
            except ValueError:
                parsed_args.append(arg)

        # Support firmware helpers without parentheses
        firmware_helpers = {"get_inventory_details", "get_name_tag", "set_name_tag"}
        if method_name in firmware_helpers:
            try:
                if method_name == "set_name_tag":
                    name_arg = parsed_args[0] if parsed_args else ""
                    escaped = str(name_arg).replace("\\", "\\\\").replace('"', '\\"')
                    res = await session.eval(f'set_name_tag("{escaped}")')
                else:
                    res = await session.eval(f'{method_name}()')
                logger.info("Turtle %d: Helper '%s' executed. Result: %s", session._turtle.id, method_name, repr(res))
                return
            except Exception as e:
                logger.error("Turtle %d: Helper '%s' failed: %s", session._turtle.id, method_name, e)
                return

        # Fall back to base Routine wrappers
        if hasattr(self, method_name):
            method_to_call = getattr(self, method_name)
            try:
                result = await method_to_call(*parsed_args) if parsed_args else await method_to_call()
                logger.info("Turtle %d: Command '%s' executed successfully. Result: %s", session._turtle.id, command_string, repr(result))
            except TypeError as e:
                logger.error("Turtle %d: Error executing command '%s'. Possible incorrect arguments: %s", session._turtle.id, command_string, e)
            except Exception as e:
                logger.error("Turtle %d: Unexpected error executing command '%s': %s", session._turtle.id, command_string, e)
        else:
            logger.error("Turtle %d: Unknown command '%s'", session._turtle.id, method_name)
