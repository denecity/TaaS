import asyncio
import logging
from typing import Optional

from server import Server, Turtle

from routines.routine_simple_dig import simple_dig_routine
from routines.routine_simple_walk import simple_walk_routine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")



async def main() -> None:
    server = Server()

    async def on_connect(t: Turtle) -> None:
        logging.getLogger("handler").info("turtle connected: %s", t.id)
        if t.id == 12:
            asyncio.create_task(simple_walk_routine(t))
        elif t.id == 11:
            asyncio.create_task(simple_dig_routine(t))

    async def on_disconnect(turtle_id: int) -> None:
        logging.getLogger("handler").info("turtle disconnected: %s", turtle_id)

    server.on_connect(on_connect)
    server.on_disconnect(on_disconnect)

    await server.start()

    # Run until Ctrl+C
    try:
        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        await server.stop()


if __name__ == "__main__":
    asyncio.run(main())

