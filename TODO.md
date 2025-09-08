# TaAS Development TODO

## ✅ Completed (v2.0 State Management Overhaul)

### Core Architecture Improvements
- [x] **Execute/Abort Model**: Replaced confusing pause/resume with honest restart-only execution
- [x] **Unified State Management**: Implemented consistent `_apply_*` pattern for all turtle state changes
- [x] **Database-Driven Updates**: All state changes trigger automatic frontend notifications
- [x] **Real-time Inventory Sync**: Frontend automatically updates when turtle inventory changes
- [x] **Smart UI Updates**: Fixed inventory update blocking during panel expansion

### API & Communication
- [x] **Event-Driven Frontend**: Eliminated manual HTTP refresh calls, pure WebSocket updates
- [x] **Endpoint Renaming**: `/run` → `/execute`, `/cancel` → `/abort` for clarity
- [x] **Event Accuracy**: `routine_paused` → `routine_aborted` to reflect actual behavior
- [x] **Return Value Handling**: Proper ComputerCraft tuple/boolean parsing for movement/refuel

### State Detection & Management
- [x] **Automatic State Collection**: GPS, heading, fuel, inventory, labels on turtle connection
- [x] **Label System**: Custom turtle naming with database persistence and frontend display
- [x] **Movement Tracking**: Accurate position updates with fuel cost calculation
- [x] **Inventory Management**: `get_inventory_details()` with automatic database updates

### Code Quality & Patterns
- [x] **Deprecated Code Removal**: Eliminated `_collect_firmware_state()` in favor of unified detection
- [x] **Method Consistency**: Fixed `get_item_*` methods to match ComputerCraft API (no slot params)
- [x] **Session Methods**: Added `get_item_detail()`, `get_location()`, improved `refuel()`
- [x] **Logging Improvements**: Color-coded console output with file logging

## 🚧 In Progress / Next Priority

### Routine System Enhancements
- [ ] **Routine State Persistence**: Save routine progress for better restart behavior
- [ ] **Routine Templates**: Pre-configured routine setups for common tasks
- [ ] **Batch Operations**: Execute routines on multiple turtles simultaneously

### Advanced State Management  
- [ ] **Inventory Change Tracking**: Detect what items were gained/lost during operations
- [ ] **Fuel Optimization**: Smart refueling strategies based on routine requirements
- [ ] **Error Recovery**: Automatic recovery from common failure states (stuck, out of fuel, etc.)

### UI/UX Improvements
- [ ] **Routine Progress Indicators**: Visual progress bars for long-running routines
- [ ] **Turtle Grouping**: Organize turtles by location, task, or custom groups
- [ ] **Configuration Presets**: Save and reuse routine configurations
- [ ] **Performance Metrics**: Track routine execution times and success rates

## 🔮 Future Considerations

### Scalability & Performance
- [ ] **Multi-server Support**: Distribute turtle management across multiple servers
- [ ] **Database Optimization**: Connection pooling and query optimization for large turtle fleets
- [ ] **WebSocket Optimization**: Efficient event batching for high-frequency updates

### Advanced Features
- [ ] **Turtle Coordination**: Multi-turtle collaborative routines
- [ ] **Resource Management**: Shared inventory and fuel management systems
- [ ] **Pathfinding Integration**: Advanced movement with obstacle avoidance
- [ ] **World Mapping**: Build maps of explored areas across turtle fleet

### Development & Operations
- [ ] **API Documentation**: OpenAPI/Swagger documentation generation
- [ ] **Testing Framework**: Comprehensive test suite for turtle operations
- [ ] **Deployment Tools**: Docker containers and deployment scripts
- [ ] **Monitoring**: Health checks and performance monitoring

## 📝 Notes

### Architecture Decisions Made
- **Execute/Abort over Pause/Resume**: Honest about technical limitations
- **Database-First State Management**: Single source of truth with automatic notifications  
- **WebSocket-Primary Communication**: Real-time updates with HTTP only for user actions
- **Session-Based Turtle Access**: Exclusive access model prevents state conflicts

### Patterns Established
- **`_apply_*` Methods**: Consistent pattern for state updates (movement, heading, label, fuel, inventory)
- **Error Handling**: Proper ComputerCraft return value parsing throughout
- **Event-Driven UI**: Frontend updates via database change notifications, not polling
- **Unified APIs**: Session methods that automatically update database and trigger frontend sync

- make event calls on sent command from frontend