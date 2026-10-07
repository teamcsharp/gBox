-- gBox bridge for REFramework (RE Engine games; written for Resident Evil 4 (2023), Steam).
-- Installed by gBox (`re4r op=install`) as <game>/reframework/autorun/gbox_bridge.lua; removed by `re4r op=uninstall`.
--
-- Command channel (files, because REFramework's Lua has no sockets; REFramework only lets scripts touch
-- <game>/reframework/data/):
--   gBox writes  reframework/data/gbox/req.json    {"seq": N, "ops": [{"op": ..., ...}, ...]}
--   bridge writes reframework/data/gbox/resp.json  {"seq": N, "results": [{"ok": true, "value": ...}, ...]}
--   bridge writes reframework/data/gbox/state.json every ~0.5 s: heartbeat, freezes, watched values
-- Ops run on the game thread (UpdateBehavior). Every value gBox changes is remembered once (its original) so
-- `revert_all` puts the game back exactly; freezes re-apply their value every frame until cleared.
--
-- Paths ("type paths"), '/'-separated:
--   singleton:<type>      managed singleton (sdk.get_managed_singleton), e.g. singleton:chainsaw.CharacterManager
--   type:<type>           static members of a type (next step = static field or static method)
--   addr:0x1234           a managed object by address
--   name()  name(1,true,"s")   call a method (literal args); a full signature is allowed: name(System.Int32)
--   name                  field (backing fields too: <HitPoint>k__BackingField); on set, falls back to set_<name>()
--   [i]                   array / List element
-- Single-player, offline use on the operator's own copy only.

local DIR = "gbox/"
local REQ, RESP, STATE = DIR .. "req.json", DIR .. "resp.json", DIR .. "state.json"
local VERSION = 1

local last_seq = nil
local tick = 0
local freezes = {}       -- path -> value
local freeze_err = {}    -- path -> last error
local originals = {}     -- ordered {path=, value=}
local seen = {}          -- path -> true (original recorded)
local watch = {}         -- name -> path (read into state.json)
local hooks = {}         -- signature -> {skip=bool, ret=value|nil, installed=true, calls=n}
local dump = nil         -- running type dump

-- ------------------------------------------------------------------ values

local function is_obj(v)
    if type(v) ~= "userdata" then return false end
    local ok, r = pcall(sdk.is_managed_object, v)
    return ok and r
end

local function tname(v)
    local ok, td = pcall(function() return v:get_type_definition() end)
    if ok and td then return td:get_full_name() end
    return nil
end

local function ser(v, depth)
    depth = depth or 0
    local t = type(v)
    if v == nil or t == "number" or t == "boolean" or t == "string" then return v end
    if t == "table" then
        if depth > 3 then return "<table>" end
        local o = {}
        for k, x in pairs(v) do o[tostring(k)] = ser(x, depth + 1) end
        return o
    end
    if t == "userdata" then
        if is_obj(v) then
            local n = tname(v) or "?"
            if n == "System.String" then
                local ok, s = pcall(function() return v:call("ToString()") end)
                if ok then return s end
            end
            local o = {_type = n}
            local ok, a = pcall(function() return v:get_address() end)
            if ok and a then o._addr = string.format("0x%X", a) end
            return o
        end
        local okx, x = pcall(function() return v.x end)
        if okx and x ~= nil then
            local o = {x = x}
            local oky, y = pcall(function() return v.y end); if oky then o.y = y end
            local okz, z = pcall(function() return v.z end); if okz then o.z = z end
            local okw, w = pcall(function() return v.w end); if okw and w ~= nil then o.w = w end
            return o
        end
        return tostring(v)
    end
    return tostring(v)
end

-- JSON {x,y,z[,w]} -> Vector3f/Vector4f for setters that need one
local function to_native(v)
    if type(v) == "table" and v.x ~= nil and v.y ~= nil and v.z ~= nil then
        if v.w ~= nil then return Vector4f.new(v.x, v.y, v.z, v.w) end
        return Vector3f.new(v.x, v.y, v.z)
    end
    return v
end

-- ------------------------------------------------------------------ paths

local function split(path)
    local out, cur, depth = {}, "", 0
    for c in path:gmatch(".") do
        if c == "(" then depth = depth + 1 elseif c == ")" then depth = depth - 1 end
        if c == "/" and depth == 0 then out[#out + 1] = cur; cur = "" else cur = cur .. c end
    end
    if cur ~= "" then out[#out + 1] = cur end
    return out
end

local function literal(s)
    s = s:match("^%s*(.-)%s*$")
    if s == "true" then return true, true end
    if s == "false" then return true, false end
    if s == "nil" or s == "null" then return true, nil end
    local n = tonumber(s)
    if n ~= nil then return true, n end
    local q = s:match('^"(.*)"$') or s:match("^'(.*)'$")
    if q ~= nil then return true, q end
    return false, nil
end

-- "name(args)" -> name, args (literal list) | signature (string) ; nil when not a call
local function parse_call(step)
    local name, inner = step:match("^([%w_%.`<>]+)%((.*)%)$")
    if not name then return nil end
    if inner == "" then return name, {}, nil end
    local args, all_lit = {}, true
    for tok in (inner .. ","):gmatch("([^,]*),") do
        local ok, v = literal(tok)
        if not ok then all_lit = false; break end
        args[#args + 1] = v
    end
    if all_lit then return name, args, nil end
    return name, {}, step                     -- a signature like name(System.Int32): no args
end

local function call(obj, td, step, extra_args)
    local name, args, sig = parse_call(step)
    if extra_args then args = extra_args end
    local nargs = {}
    for i, a in ipairs(args) do nargs[i] = to_native(a) end
    if obj == nil then                         -- static
        local m = td:get_method(sig or name)
        if not m then error("no static method " .. step .. " on " .. td:get_full_name()) end
        return m:call(nil, table.unpack(nargs))
    end
    return obj:call(sig or name, table.unpack(nargs))
end

local function field(obj, td, name)
    if obj == nil then
        local f = td:get_field(name)
        if not f then error("no static field " .. name .. " on " .. td:get_full_name()) end
        return f:get_data(nil)
    end
    local otd = obj:get_type_definition()
    if otd and otd:get_field(name) == nil then
        -- property fallback: get_<name>()
        local ok, v = pcall(function() return obj:call("get_" .. name) end)
        if ok then return v end
        error("no field " .. name .. " on " .. otd:get_full_name())
    end
    return obj:get_field(name)
end

local function index(obj, i)
    local td = obj:get_type_definition()
    if td and td:is_array() then return obj:get_element(i) end
    return obj:call("get_Item", i)
end

-- returns value, parent object, parent typedef, last step
local function resolve(path)
    local steps = type(path) == "table" and path or split(path)
    if #steps == 0 then error("empty path") end
    local root = steps[1]
    local cur, td
    local kind, rest = root:match("^(%w+):(.+)$")
    if kind == "singleton" then
        cur = sdk.get_managed_singleton(rest)
        if cur == nil then error("singleton " .. rest .. " is not alive (not in game yet?)") end
    elseif kind == "type" then
        td = sdk.find_type_definition(rest)
        if not td then error("unknown type " .. rest) end
        cur = nil
    elseif kind == "addr" then
        cur = sdk.to_managed_object(tonumber(rest))
        if cur == nil then error("no managed object at " .. rest) end
    else
        error("path must start with singleton:<type>, type:<type> or addr:0x..")
    end
    local parent, ptd, last = nil, nil, nil
    for i = 2, #steps do
        local s = steps[i]
        parent, ptd, last = cur, td, s
        if cur == nil and td == nil then error("nil at step " .. (i - 1) .. " (" .. steps[i - 1] .. ")") end
        local idx = s:match("^%[(%-?%d+)%]$")
        if idx then
            cur = index(cur, tonumber(idx))
        elseif parse_call(s) then
            cur = call(cur, td, s)
        else
            cur = field(cur, td, s)
        end
        td = nil                               -- static context only applies to the first step after type:
    end
    return cur, parent, ptd, last
end

local function assign(path, value)
    local steps = type(path) == "table" and path or split(path)
    local _, parent, ptd, last = resolve(steps)
    if parse_call(last) then error("the last step of a set path must be a field or property, not a call") end
    local v = to_native(value)
    if parent == nil and ptd ~= nil then
        local f = ptd:get_field(last)
        if not f then error("no static field " .. last) end
        f:set_data(nil, v)
        return
    end
    if parent == nil then error("nothing to set at " .. tostring(last)) end
    local td = parent:get_type_definition()
    if td and td:get_field(last) ~= nil then
        parent:set_field(last, v)
    else
        parent:call("set_" .. last, v)
    end
end

local function remember(path)
    if seen[path] then return end
    local ok, v = pcall(resolve, path)
    if ok then
        originals[#originals + 1] = {path = path, value = v}
        seen[path] = true
    end
end

-- ------------------------------------------------------------------ type info / dump

local function tdname(t)
    if t == nil then return nil end
    local ok, n = pcall(function() return t:get_full_name() end)
    return ok and n or nil
end

local function type_info(name, limit)
    local td = sdk.find_type_definition(name)
    if not td then return nil end
    limit = limit or 400
    local o = {name = td:get_full_name(), parent = tdname(td:get_parent_type()), fields = {}, methods = {}}
    local okv, vt = pcall(function() return td:is_value_type() end); o.value_type = okv and vt or nil
    for _, f in ipairs(td:get_fields() or {}) do
        if #o.fields >= limit then break end
        local okf, e = pcall(function()
            return {f:get_name(), tdname(f:get_type()), f:is_static()}
        end)
        if okf then o.fields[#o.fields + 1] = e end
    end
    for _, m in ipairs(td:get_methods() or {}) do
        if #o.methods >= limit then break end
        local okm, e = pcall(function()
            local ps = {}
            for _, p in ipairs(m:get_param_types() or {}) do ps[#ps + 1] = tdname(p) or "?" end
            return {m:get_name(), tdname(m:get_return_type()), table.concat(ps, ","), m:is_static()}
        end)
        if okm then o.methods[#o.methods + 1] = e end
    end
    return o, td
end

local function dump_step()
    local d = dump
    local n = 0
    while #d.queue > 0 and n < d.per_tick do
        local name = table.remove(d.queue)
        n = n + 1
        local ok, info, td = pcall(type_info, name, 2000)
        if ok and info then
            d.chunk[#d.chunk + 1] = info
            d.count = d.count + 1
            local function add(t)
                if t and not d.visited[t] and d.count + #d.queue < d.max then
                    d.visited[t] = true
                    d.queue[#d.queue + 1] = t
                end
            end
            add(info.parent)
            for _, f in ipairs(info.fields) do add(f[2]) end
            for _, m in ipairs(info.methods) do
                add(m[2])
                for p in (m[3] or ""):gmatch("[^,]+") do add(p) end
            end
        end
        if #d.chunk >= 500 then
            json.dump_file(d.out .. string.format("types_%04d.json", d.file), d.chunk)
            d.file, d.chunk = d.file + 1, {}
        end
    end
    if #d.queue == 0 then
        if #d.chunk > 0 then json.dump_file(d.out .. string.format("types_%04d.json", d.file), d.chunk); d.file = d.file + 1 end
        json.dump_file(d.out .. "done.json", {types = d.count, files = d.file})
        d.done = true
    end
end

-- ------------------------------------------------------------------ hooks (flag-guarded: REFramework can't unhook)

local function hook(sig, opts)
    local h = hooks[sig]
    if h == nil then
        local tdn, mname = sig:match("^(.-)%.([^%.]+%b())$")
        if not tdn then tdn, mname = sig:match("^(.*)%.([^%.]+)$") end
        local td = tdn and sdk.find_type_definition(tdn)
        if not td then error("unknown type in " .. sig) end
        local m = td:get_method(mname)
        if not m then error("no method " .. mname .. " on " .. tdn) end
        h = {skip = false, ret = nil, calls = 0}
        hooks[sig] = h
        sdk.hook(m, function(args)
            h.calls = h.calls + 1
            if h.skip then return sdk.PreHookResult.SKIP_ORIGINAL end
        end, function(retval)
            if h.ret ~= nil then
                if type(h.ret) == "boolean" then return sdk.to_ptr(h.ret and 1 or 0) end
                return sdk.to_ptr(h.ret)
            end
            return retval
        end)
    end
    if opts.skip ~= nil then h.skip = opts.skip end
    if opts.ret ~= nil then h.ret = opts.ret end
    if opts.clear_ret then h.ret = nil end
    return {sig = sig, skip = h.skip, ret = h.ret, calls = h.calls}
end

-- ------------------------------------------------------------------ ops

local OPS = {}

OPS.ping = function(r)
    return {bridge = VERSION, game = reframework:get_game_name(), tick = tick, tdb = sdk.get_tdb_version()}
end

OPS.get = function(r)
    local v = resolve(r.path)
    if r.raw then return v end
    return ser(v)
end

OPS.get_many = function(r)
    local o = {}
    for k, p in pairs(r.paths) do
        local ok, v = pcall(resolve, p)
        o[k] = ok and ser(v) or {error = tostring(v)}
    end
    return o
end

OPS.set = function(r)
    remember(r.path)
    local before = ser((resolve(r.path)))
    assign(r.path, r.value)
    local after = ser((resolve(r.path)))
    return {before = before, after = after}
end

OPS.call = function(r)
    local obj, td
    local steps = split(r.path)
    if #steps == 1 and steps[1]:match("^type:") then
        td = sdk.find_type_definition(steps[1]:sub(6))
        if not td then error("unknown type " .. steps[1]) end
    else
        obj = resolve(r.path)
        if obj == nil then error("path resolved to nil") end
    end
    local v = call(obj, td, r.method, r.args or {})
    return ser(v)
end

OPS.fields = function(r)                     -- live dump of an object's fields (values) for exploration
    local obj = resolve(r.path)
    if not is_obj(obj) then return ser(obj) end
    local td = obj:get_type_definition()
    local o = {_type = td:get_full_name()}
    local t = td
    while t do
        for _, f in ipairs(t:get_fields() or {}) do
            if not f:is_static() then
                local ok, v = pcall(function() return obj:get_field(f:get_name()) end)
                o[f:get_name()] = ok and ser(v) or "?"
            end
        end
        if not r.inherited then break end
        t = t:get_parent_type()
        if t and t:get_full_name():match("^System%.") then break end
    end
    return o
end

OPS.type_info = function(r)
    local o = type_info(r.name, r.limit)
    if not o then error("unknown type " .. r.name) end
    return o
end

OPS.find_types = function(r)                 -- which of these names exist
    local o = {}
    for _, n in ipairs(r.names) do
        if sdk.find_type_definition(n) then o[#o + 1] = n end
    end
    return o
end

OPS.freeze = function(r)
    if r.on == false then
        freezes[r.path] = nil
        return {path = r.path, frozen = false}
    end
    remember(r.path)
    assign(r.path, r.value)
    freezes[r.path] = r.value
    return {path = r.path, frozen = true, value = r.value}
end

OPS.hook = function(r)
    if r.sig then
        local res = hook(r.sig, r)
        return res
    end
    local o = {}
    for s, h in pairs(hooks) do o[s] = {skip = h.skip, ret = h.ret, calls = h.calls} end
    return o
end

OPS.watch = function(r)
    for k, p in pairs(r.paths or {}) do watch[k] = p end
    if r.clear then watch = {} end
    return watch
end

OPS.revert_all = function(r)
    local n_freeze = 0
    for _ in pairs(freezes) do n_freeze = n_freeze + 1 end
    freezes = {}
    local restored, failed = 0, {}
    for i = #originals, 1, -1 do
        local e = originals[i]
        local ok, err = pcall(assign, e.path, e.value)
        if ok then restored = restored + 1 else failed[#failed + 1] = {path = e.path, error = tostring(err)} end
    end
    originals, seen = {}, {}
    local n_hooks = 0
    for _, h in pairs(hooks) do
        if h.skip or h.ret ~= nil then n_hooks = n_hooks + 1 end
        h.skip, h.ret = false, nil
    end
    return {restored = restored, freezes_cleared = n_freeze, hooks_disabled = n_hooks, failed = failed}
end

OPS.changes = function(r)
    local o = {originals = {}, freezes = {}}
    for _, e in ipairs(originals) do o.originals[#o.originals + 1] = {path = e.path, value = ser(e.value)} end
    for p, v in pairs(freezes) do o.freezes[p] = v end
    for s, h in pairs(hooks) do
        if h.skip or h.ret ~= nil then o.hooks = o.hooks or {}; o.hooks[s] = {skip = h.skip, ret = h.ret} end
    end
    return o
end

OPS.lua = function(r)                        -- gBox's LLM / operator: arbitrary Lua on the game thread
    local fn, err = load(r.code, "gbox", "t", setmetatable({resolve = resolve, ser = ser, assign = assign,
                                                              remember = remember}, {__index = _G}))
    if not fn then error(err) end
    return ser(fn())
end

OPS.dump_types = function(r)
    if dump and not dump.done and not r.restart then
        return {running = true, count = dump.count, queued = #dump.queue}
    end
    dump = {queue = {}, visited = {}, chunk = {}, count = 0, file = 0, max = r.max or 60000,
            per_tick = r.per_tick or 40, out = DIR .. "tdb/", done = false}
    for _, s in ipairs(r.seeds or {}) do
        if not dump.visited[s] then dump.visited[s] = true; dump.queue[#dump.queue + 1] = s end
    end
    return {started = true, seeds = #dump.queue}
end

OPS.dump_status = function(r)
    if not dump then return {running = false} end
    return {running = not dump.done, done = dump.done, count = dump.count, queued = #dump.queue, files = dump.file}
end

-- ------------------------------------------------------------------ loop

local function handle(req)
    local results = {}
    for i, r in ipairs(req.ops or {}) do
        local f = OPS[r.op]
        if not f then
            results[i] = {ok = false, error = "unknown op " .. tostring(r.op)}
        else
            local ok, v = pcall(f, r)
            results[i] = ok and {ok = true, value = v} or {ok = false, error = tostring(v)}
        end
    end
    json.dump_file(RESP, {seq = req.seq, results = results, tick = tick})
end

local function write_state()
    local w = {}
    for k, p in pairs(watch) do
        local ok, v = pcall(resolve, p)
        w[k] = ok and ser(v) or nil
    end
    local fz = {}
    for p, v in pairs(freezes) do fz[#fz + 1] = p end
    local clock = (os and os.clock) and os.clock() or 0
    json.dump_file(STATE, {bridge = VERSION, tick = tick, clock = clock, seq = last_seq, watch = w,
                           freezes = fz, changed = #originals, freeze_errors = freeze_err})
end

local function on_tick()
    tick = tick + 1
    for p, v in pairs(freezes) do
        local ok, err = pcall(assign, p, v)
        freeze_err[p] = (not ok) and tostring(err) or nil
    end
    if dump and not dump.done then pcall(dump_step) end
    if tick % 3 == 0 then
        local req = json.load_file(REQ)
        if req and req.seq ~= nil and req.seq ~= last_seq then
            last_seq = req.seq
            handle(req)
        end
    end
    if tick % 30 == 0 then pcall(write_state) end
end

re.on_pre_application_entry("UpdateBehavior", function()
    local ok, err = pcall(on_tick)
    if not ok then log.info("[gBox bridge] " .. tostring(err)) end
end)

-- the game thread stops in menus/loading on some titles: answer pings from the render loop too
re.on_frame(function()
    if tick == 0 then
        local req = json.load_file(REQ)
        if req and req.seq ~= nil and req.seq ~= last_seq then
            last_seq = req.seq
            json.dump_file(RESP, {seq = req.seq, results = {{ok = false, error = "game thread not running yet (title/loading)"}}})
        end
    end
end)

log.info("[gBox bridge] loaded v" .. VERSION)
