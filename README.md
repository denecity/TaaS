# Turtles-as-a-Service (TaaS)

Server-driven control plane for ComputerCraft turtles with real-time state management and unified routine execution. Centralizes logic on auxiliary servers—nothing runs "on the turtle."

## Features

### Core System
- **Execute/Abort Control**: Single-button interface for routine management (replaces confusing pause/resume)
- **Real-time State Sync**: Database-driven updates with automatic frontend notifications
- **Comprehensive State Tracking**: GPS coordinates, heading, fuel, inventory, and custom labels
- **Session-based Architecture**: Exclusive turtle access with consistent state management patterns

### State Management
- **Automatic Detection**: GPS coordinates, heading, fuel levels on connection
- **Inventory Tracking**: Real-time inventory updates with frontend synchronization  
- **Label System**: Custom turtle naming with database persistence
- **Movement Tracking**: Accurate position updates with fuel cost calculation

### API & Communication
- **WebSocket Events**: Real-time updates for connections, state changes, and routine status
- **RESTful Endpoints**: `/turtles/{id}/execute` and `/turtles/{id}/abort` for routine control
- **Database-Driven**: SQLite backend with automatic change notifications
- **Robust Error Handling**: Proper ComputerCraft return value parsing for all turtle operations

### Frontend
- **Live Dashboard**: Real-time turtle monitoring with dynamic inventory display
- **Routine Management**: Clean routine names (auto-formatting removes prefixes/underscores)
- **Event-Driven Updates**: No manual refresh needed - all updates via WebSocket
- **Smart UI Updates**: Inventory updates respect user interaction state

## Quick Start

### Prerequisites
- Python 3.11+ on Linux
- ComputerCraft turtles with WebSocket capability

### Installation
```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Running
```bash
# Start the server
make run
# OR manually:
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

Open http://localhost:8000 to access the dashboard.

## Usage

### Turtle Control
1. **Connection**: Turtles auto-connect via WebSocket and appear in dashboard
2. **State Detection**: GPS, fuel, heading, and inventory are automatically detected
3. **Routine Execution**: Select routine, configure parameters, click "Execute"
4. **Real-time Monitoring**: Watch coordinates, fuel, and inventory update live
5. **Abort/Restart**: Use "Abort" to stop routines; "Execute" always starts from beginning

### API Endpoints
- `GET /turtles` - List all known turtles with state
- `GET /turtles/{id}` - Get specific turtle status  
- `GET /routines` - List available routines
- `POST /turtles/{id}/execute` - Start routine execution
- `POST /turtles/{id}/abort` - Stop running routine
- `WebSocket /events` - Real-time event stream

### Routine Development
```python
from routines.base import Routine

class MyRoutine(Routine):
    async def perform(self, session, config):
        # Use session methods for turtle control
        await session.forward()           # Auto-updates position & fuel
        await session.dig()               # Basic turtle operations
        detail = await session.get_item_detail()  # Get current slot info
        await session.get_inventory_details()     # Update full inventory
        await session.set_label("My Turtle")      # Set custom name
```

## Development Notes

### Architecture
- **Frontend**: Static HTML/JS under `web/static/` (no build step required)
- **Backend**: FastAPI with SQLite database and WebSocket support
- **State Management**: Unified `_apply_*` pattern for all turtle state changes
- **Communication**: Event-driven WebSocket with automatic reconnection

### Key Components
- `backend/turtle.py`: Turtle session management with state tracking
- `backend/db_state.py`: Database operations with change notifications  
- `main.py`: FastAPI app with logging and WebSocket orchestration
- `web/static/app.js`: Frontend with real-time updates and smart UI

### Logging
- **File Output**: Comprehensive logs in `logs/taas.log`
- **Console Output**: Color-coded by log level for easy debugging
- **WebSocket Forwarding**: Selected logs broadcast to frontend

### Database Schema
```sql
CREATE TABLE turtles (
    turtle_id INTEGER PRIMARY KEY,
    fuel_level INTEGER,
    inventory TEXT,
    x INTEGER, y INTEGER, z INTEGER,
    heading INTEGER,
    connection_status TEXT,
    label TEXT
);
```

## Recent Improvements

### v2.0 State Management Overhaul
- ✅ **Execute/Abort Model**: Honest about restart-only behavior vs misleading pause/resume
- ✅ **Unified State Updates**: All turtle actions trigger database + frontend updates  
- ✅ **Real-time Inventory**: Frontend automatically updates when inventory changes
- ✅ **Label System**: Custom turtle naming with persistence and frontend display
- ✅ **Smart Frontend**: Only skip updates during active user input, not panel expansion
- ✅ **Robust Movement**: Proper ComputerCraft return value handling for all movement functions
- ✅ **Automatic State Detection**: GPS, heading, fuel, inventory, and labels on connection

### API Evolution  
- ✅ **Endpoint Renaming**: `/run` → `/execute`, `/cancel` → `/abort` for clarity
- ✅ **Event Updates**: `routine_paused` → `routine_aborted` for accuracy
- ✅ **Consistent Patterns**: All turtle operations follow `_apply_*` database update pattern

## License
No license. All rights reserved.

You may view this repository. No permission is granted to use, modify, distribute, or host this software. The author may relicense at any time.

## Contributing
Not currently accepting external contributions.
