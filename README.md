# Turtles-as-a-Service (TaAS)

Server-driven control plane for ComputerCraft turtles (and future CC computers). Centralizes logic on auxiliary servers—nothing runs “on the turtle.”

## Features
- Manage and run routines against connected turtles
- Live updates via WebSocket + safe polling fallback
- Normalized snapshots (coords, heading, fuel, label, inventory)
- Terminal logging with filenames; colored warnings/errors

## Quick start
- Python 3.11+ on Linux
- Create venv and install deps (pip/requirements as in project)
- Run:
  - `make frontend` or `python -m uvicorn main:app --host 0.0.0.0 --port 8000`
  - CC gateway server listens on its configured WS port (see logs)

Open http://localhost:8000

## Development notes
- Frontend: static HTML/JS under `web/static/` (no build step)
- Events: `/events` WebSocket streams turtle snapshots and routine events
- REST: `/turtles`, `/routines`, and routine control endpoints
- Logging: global formatter includes filename; colors on TTY

## License
No license. All rights reserved.

You may view this repository. No permission is granted to use, modify, distribute, or host this software. The author may relicense at any time.

## Contributing
Not currently accepting external contributions.