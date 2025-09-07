-- Kinsky Turtle Firmware (simplified)
-- Minimal WS loop: receive one raw Lua line with a request id, execute, reply

local args = {...}

local WS_URL = "wss://turtle.mykinsky.org/ws"
local PING_INTERVAL = 20
local RECONNECT_BASE_DELAY = 3
local RECONNECT_MAX_DELAY = 30

local function now_ms()
  return os.epoch("utc")
end

local function json_encode(tbl)
  return textutils.serializeJSON(tbl)
end

local function json_decode(str)
  local ok, res = pcall(textutils.unserializeJSON, str)
  if ok then return res else return nil, res end
end

local function generate_message_id()
  local cid = os.getComputerID() or 0
  return ("t_%d_%d_%d"):format(cid, now_ms(), math.random(1000, 9999))
end

local TURTLE_ID = os.getComputerID()
-- Name tag management
local _os = os -- capture original
local NAME_TAG = (_os.getComputerLabel and _os.getComputerLabel()) or tostring(TURTLE_ID)
-- Ensure the label is set to the ID on first boot/run
pcall(function() if _os.setComputerLabel then _os.setComputerLabel(NAME_TAG) end end)

local function shallow_copy_table(obj)
  local t = {}
  for k, v in pairs(obj) do t[k] = v end
  return t
end

local function jsonify_value(value, visited, depth)
  visited = visited or {}
  depth = depth or 0
  if depth > 3 then return tostring(value) end

  local tv = type(value)
  if tv == "nil" or tv == "number" or tv == "boolean" or tv == "string" then
    return value
  elseif tv == "table" then
    if visited[value] then return "<cycle>" end
    visited[value] = true
    local out = {}
    for k, v in pairs(value) do
      local jk = jsonify_value(k, visited, depth + 1)
      local jv = jsonify_value(v, visited, depth + 1)
      out[jk] = jv
    end
    visited[value] = nil
    return out
  else
    return tostring(value)
  end
end

-- Exposed helper to rename the turtle safely from evaluated code
local function set_name_tag(new_name)
  if type(new_name) ~= "string" or #new_name == 0 then return false end
  if _os.setComputerLabel then
    local ok, err = pcall(_os.setComputerLabel, new_name)
    if not ok then return false end
  end
  NAME_TAG = new_name
  return true
end

-- Exposed helper to get all inventory details in one call
local function get_inventory_details()
  local out = {}
  for slot = 1, 16 do
    local ok, d = pcall(turtle.getItemDetail, slot, true)
    if ok and d ~= nil then
      out[slot] = jsonify_value(d)
    else
      out[slot] = nil
    end
  end
  return out
end

local function build_env()
  return {
    turtle = turtle,
    vector = vector,
    gps = gps,
    colours = colours,
    colors = colors,
    math = math,
    string = string,
    table = table,
    pairs = pairs,
    ipairs = ipairs,
    select = select,
    tonumber = tonumber,
    tostring = tostring,
    type = type,
    sleep = sleep,
    textutils = { serializeJSON = textutils.serializeJSON },
    os = { clock = os.clock, time = os.time, day = os.day, epoch = os.epoch, pullEvent = os.pullEvent, pullEventRaw = os.pullEventRaw, getComputerLabel = _os.getComputerLabel },
    peripheral = peripheral,
    -- custom helpers
    set_name_tag = set_name_tag,
    get_name_tag = function() return NAME_TAG end,
    get_inventory_details = get_inventory_details,
  }
end

local function execute_command_line(command_line)
  if type(command_line) ~= "string" or command_line == "" then
    return false, nil, false -- ok, value, is_request
  end
  local env = build_env()
  -- Try as expression (request mode)
  local chunk, err = load("return " .. command_line, "cmd", "t", env)
  local is_request = true
  if not chunk then
    -- Fallback to statement (direct command)
    chunk, err = load(command_line, "cmd", "t", env)
    is_request = false
  end
  if not chunk then return false, err, is_request end
  local ok, v1, v2, v3, v4, v5 = pcall(chunk)
  if not ok then
    return false, tostring(v1), is_request
  end
  if is_request then
    -- If first value is boolean and there is an error/message, treat as direct
    if type(v1) == "boolean" and (v2 ~= nil) then
      return v1 == true, nil, false
    end
    -- Otherwise return captured value(s)
    local values = {}
    if v1 ~= nil then table.insert(values, jsonify_value(v1)) end
    if v2 ~= nil then table.insert(values, jsonify_value(v2)) end
    if v3 ~= nil then table.insert(values, jsonify_value(v3)) end
    if v4 ~= nil then table.insert(values, jsonify_value(v4)) end
    if v5 ~= nil then table.insert(values, jsonify_value(v5)) end
    local value
    if #values == 0 then value = nil
    elseif #values == 1 then value = values[1]
    else value = values end
    return true, value, true
  else
    -- Statement: treat success as ok=true
    return true, nil, false
  end
end

-- No predefined requests in simplified mode

local function build_response(request_id, ok, value)
  local resp = { turtle_id = TURTLE_ID, request_id = request_id, ok = ok }
  if value ~= nil then resp.value = value end
  -- Keep compatibility with server correlator
  resp.in_reply_to = request_id
  return resp
end

local function ws_send_json(ws, tbl)
  local okEncode, data = pcall(json_encode, tbl)
  if not okEncode then return false, data end
  local okSend, res = pcall(function() return ws.send(data) end)
  if not okSend then return false, res end
  return true
end

local function connect_ws(url)
  local ok, ws_or_err = pcall(function() return http.websocket(url) end)
  if not ok then
    return nil, tostring(ws_or_err)
  end
  if ws_or_err == nil then
    return nil, "unknown error"
  end
  -- http.websocket returns ws or nil, err
  if type(ws_or_err) == "table" and ws_or_err.receive then
    return ws_or_err, nil
  else
    return nil, tostring(select(2, pcall(function() return ws_or_err end)))
  end
end

local function run_ws_session(ws)
  -- Minimal hello with id only
  if not ws_send_json(ws, { type = "hello", computer_id = TURTLE_ID }) then return end

  local last_activity = now_ms()
  while true do
    local timeout = 1
    local ok, data = pcall(function() return ws.receive(timeout) end)
    if not ok then
      break
    end

    if data ~= nil then
      last_activity = now_ms()
      local msg, perr = json_decode(data)
      if not msg then
        -- ignore invalid
      else
        local req_id = msg.id or msg.request_id
        local line = msg.command or msg.src or msg.line
        if type(req_id) == "string" or type(req_id) == "number" then
          if type(line) == "string" then
            local okc, value, is_request = execute_command_line(line)
            if not ws_send_json(ws, build_response(req_id, okc, is_request and value or nil)) then break end
          end
        end
      end
    end

    if now_ms() - last_activity >= (PING_INTERVAL * 1000) then
      if not ws_send_json(ws, { type = "ping", time = now_ms(), turtle_id = TURTLE_ID, name_tag = NAME_TAG }) then break end
      last_activity = now_ms()
    end
  end
end

local function main()
  math.randomseed(now_ms() % 2147483647)
  print(("Kinsky Turtle starting. URL: %s"):format(WS_URL))

  local attempt = 0
  local first_phase_tries = 5 -- quick retries before backoff
  while true do
    attempt = attempt + 1
    print(("Connecting (attempt %d) ..."):format(attempt))

    local ws, err = connect_ws(WS_URL)
    if ws then
      print("Connected.")
      local ok, run_err = pcall(run_ws_session, ws)
      if not ok then
        print(("Session error: %s"):format(tostring(run_err)))
      end
      pcall(function() ws.close() end)
      print("Disconnected. Reconnecting...")
    else
      print(("Connection failed: %s"):format(tostring(err)))
    end

    -- Reconnect policy: quick retries first, then exponential backoff
    if attempt < first_phase_tries then
      sleep(1)
    else
      local base = math.min(RECONNECT_BASE_DELAY * (2 ^ math.min(attempt - first_phase_tries, 6)), RECONNECT_MAX_DELAY)
      local jitter = base * (math.random() * 0.4 - 0.2) -- +/-20%
      local backoff = math.max(0.5, base + jitter)
      sleep(backoff)
    end
  end
end

local function monitor_terminate()
  while true do
    local ev = { os.pullEventRaw() }
    if ev[1] == "terminate" then
      print("Terminated by user.")
      return
    end
  end
end

local function run()
  parallel.waitForAny(main, monitor_terminate)
end

run()


