const el = {
    list: document.getElementById('turtles'),
    badge: document.getElementById('connection-status'),
};

// simple in-memory state to keep logs across UI updates
const state = {
    logs: new Map(), // turtleId -> string[]
    expanded: new Set(), // turtleIds kept expanded
};
const LOG_LIMIT = 200;

// DEBUG helpers
function dbg(...args) { try { console.log('[ui]', ...args); } catch (_) { } }

function sinceString(ms) {
    if (!ms) return '—';
    const diff = Math.max(0, Date.now() - ms);
    const s = Math.floor(diff / 1000);
    const d = Math.floor(s / 86400);
    const h = Math.floor((s % 86400) / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    const parts = [];
    if (d) parts.push(`${d}d`);
    if (h) parts.push(`${h}h`);
    if (m) parts.push(`${m}m`);
    parts.push(`${sec}s`);
    return parts.join(' ');
}

async function fetchJSON(url) {
    dbg('fetchJSON', url);
    const r = await fetch(url);
    dbg('fetchJSON resp', url, r.status);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
}

function inventoryGrid(inv) {
    const getSlotDetail = (i) => {
        if (!inv) return null;
        if (Array.isArray(inv)) return inv[i - 1] || null; // zero-based arrays
        return inv[i] || null; // object keyed by slot number strings/ints
    };
    const cells = [];
    for (let i = 1; i <= 16; i++) {
        const d = getSlotDetail(i);
        const count = d && (d.count ?? d.Count ?? d.COUNT ?? null);
        const name = d && (d.displayName ?? d.name ?? null);
        const countText = (count != null) ? String(count) : '';
        const nameText = name || '';
        cells.push(
            `<div class="slot">
                <div class="slot-count">${countText}</div>
                <div class="slot-name">${nameText}</div>
            </div>`
        );
    }
    return cells.join('');
}

function turtleConsole(id) {
    return {
        push(line) {
            const buffer = state.logs.get(id) || [];
            buffer.push(line);
            if (buffer.length > LOG_LIMIT) buffer.splice(0, buffer.length - LOG_LIMIT);
            state.logs.set(id, buffer);
            const c = document.querySelector(`.turtle[data-id="${id}"] .console`);
            if (!c) return;
            const div = document.createElement('div');
            div.textContent = line;
            c.appendChild(div);
            // keep view anchored at bottom where newest entries appear
            c.scrollTop = c.scrollHeight;
        }
    }
}

function hydrateConsoleFromState(id) {
    const c = document.querySelector(`.turtle[data-id="${id}"] .console`);
    if (!c) return;
    c.innerHTML = '';
    const buffer = state.logs.get(id) || [];
    for (const line of buffer) {
        const div = document.createElement('div');
        div.textContent = line;
        c.appendChild(div);
    }
    c.scrollTop = c.scrollHeight;
}

function currentButtonLabelFromAssignment(assign) {
    if (!assign || !assign.status) return 'Start';
    if (assign.status === 'running') return 'Stop';
    if (assign.status === 'paused') return 'Continue';
    return 'Start';
}

function headingToText(h) {
    if (h === 0) return 'East';
    if (h === 1) return 'South';
    if (h === 2) return 'West';
    if (h === 3) return 'North';
    return '—';
}

function renderTurtle(t) {
    const statusClass = t.alive ? 'connected' : 'disconnected';
    const fuel = t.fuel_level ?? '—';
    const inv = t.inventory ?? null;
    const coords = t.coords ?? {};
    const heading = (t.heading ?? null);
    const btnLabel = currentButtonLabelFromAssignment(t.assignment);
    const routineName = (t.assignment && t.assignment.routine) ? t.assignment.routine : '—';
    const titleText = t.label ? `${t.label} (#${t.id})` : `Turtle #${t.id}`;
    return `
    <div class="turtle" data-id="${t.id}">
      <div class="avatar">T</div>
      <div class="meta">
        <div class="title">${titleText}</div>
        <div class="status ${statusClass}">${t.alive ? 'connected' : 'disconnected'}</div>
        <div class="fuel">Fuel: ${fuel}</div>
        <div class="routine-label">Routine: <span class="routine-name">${routineName}</span></div>
      </div>
      <div class="coords-col">
        <div class="coord-line">x: <span class="coord-x">${coords.x ?? '—'}</span></div>
        <div class="coord-line">y: <span class="coord-y">${coords.y ?? '—'}</span></div>
        <div class="coord-line">z: <span class="coord-z">${coords.z ?? '—'}</span></div>
        <div class="coord-line">h: <span class="coord-heading">${headingToText(heading)}</span></div>
      </div>
      <div class="console" aria-label="console"></div>
      <div class="controls">
        <button class="btn primary toggle">${btnLabel}</button>
        <button class="btn stop">Stop</button>
      </div>
      <div class="uptime" data-since="${t.last_seen_ms || 0}">${sinceString(t.last_seen_ms || 0)}</div>
      <div class="expand" title="Expand">▾</div>
      <div class="details">
        <div class="detail-grid">
          <div class="detail-section">
            <h4>Routine</h4>
            <select class="select routine"></select>
            <textarea class="textarea config" placeholder="YAML or JSON"></textarea>
          </div>
          <div class="detail-section">
            <h4>Inventory</h4>
            <div class="inventory">${inventoryGrid(inv)}</div>
          </div>
        </div>
      </div>
    </div>
  `;
}

function bindItemHandlers(root, routines) {
    dbg('bindItemHandlers: routines raw', routines);
    const expander = root.querySelector('.expand');
    expander.addEventListener('click', () => {
        const details = root.querySelector('.details');
        const open = details.classList.toggle('open');
        expander.classList.toggle('rot', open);
        const id = root.dataset.id;
        if (open) state.expanded.add(id); else state.expanded.delete(id);
    });
    const select = root.querySelector('.routine');
    const cfg = root.querySelector('.config');

    const norm = Array.isArray(routines) ? routines.map(r => {
        if (typeof r === 'string') return { name: r, description: '', config_template: '' };
        return r;
    }) : [];
    dbg('bindItemHandlers: routines normalized', norm);

    select.innerHTML = '';
    norm.forEach(r => {
        const opt = new Option(r.name, r.name);
        if (r.description) opt.title = r.description;
        opt.dataset.template = r.config_template || '';
        select.append(opt);
    });
    dbg('bindItemHandlers: options populated', select.options.length);

    if (select.options.length > 0) select.value = select.options[0].value;

    if (cfg) {
        cfg.addEventListener('input', () => {
            cfg.dataset.autofilled = 'false';
        });
    }

    function applyTemplateFromSelection() {
        const sel = select.selectedOptions[0];
        dbg('applyTemplateFromSelection: selected', sel?.value);
        if (!sel || !cfg) return;
        const tpl = sel.dataset.template || '';
        dbg('applyTemplateFromSelection: template len', tpl.length);
        if (tpl) {
            cfg.value = tpl.trimStart();
            cfg.dataset.autofilled = 'true';
        }
    }

    applyTemplateFromSelection();
    select.addEventListener('change', applyTemplateFromSelection);

    root.querySelector('.toggle').addEventListener('click', async (e) => {
        const id = root.dataset.id;
        const btn = e.currentTarget;
        const label = btn.textContent.trim();
        const wantsStop = label.toLowerCase() === 'stop';
        const cfg = root.querySelector('.config');
        const select = root.querySelector('.routine');
        btn.disabled = true;
        try {
            if (wantsStop) {
                dbg('action: stop', id);
                const r = await fetch(`/turtles/${id}/cancel`, { method: 'POST' });
                dbg('resp: cancel', r.status);
                if (r.ok) {
                    btn.textContent = 'Start';
                    turtleConsole(id).push('[client] requested stop');
                } else {
                    turtleConsole(id).push(`[client] stop failed: HTTP ${r.status}`);
                }
            } else {
                let r;
                if (label.toLowerCase() === 'continue') {
                    dbg('action: continue', id);
                    r = await fetch(`/turtles/${id}/continue`, { method: 'POST' });
                    dbg('resp: continue', r.status);
                    if (!r.ok) {
                        const routineName = select.value || (norm[0]?.name || '');
                        dbg('fallback start routine', routineName);
                        if (!routineName) {
                            turtleConsole(id).push('[client] no routines available to run');
                        } else {
                            r = await fetch(`/turtles/${id}/run`, {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ routine: routineName, config: cfg?.value || '' }),
                            });
                            dbg('resp: run (fallback)', r.status);
                        }
                    }
                } else { // Start
                    const routineName = select.value || (norm[0]?.name || '');
                    dbg('action: start', id, routineName);
                    if (!routineName) {
                        turtleConsole(id).push('[client] no routines available to run');
                    } else {
                        r = await fetch(`/turtles/${id}/run`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ routine: routineName, config: cfg?.value || '' }),
                        });
                        dbg('resp: run', r.status);
                    }
                }
                if (r && r.ok) {
                    btn.textContent = 'Stop';
                    turtleConsole(id).push('[client] requested continue/start');
                } else if (r && !r.ok) {
                    turtleConsole(id).push(`[client] run/continue failed: HTTP ${r.status}`);
                }
            }
        } catch (err) {
            dbg('action error', err);
            turtleConsole(id).push(`[client] error: ${err}`);
        } finally {
            btn.disabled = false;
        }
    });
    root.querySelector('.stop').addEventListener('click', async () => {
        const id = root.dataset.id;
        dbg('action: stop', id);
        const r = await fetch(`/turtles/${id}/cancel`, { method: 'POST' });
        dbg('resp: stop', r.status);
        if (r.ok) {
            turtleConsole(id).push('[client] routine stopped');
        } else {
            turtleConsole(id).push(`[client] stop failed: HTTP ${r.status}`);
        }
    });
}

function sortTurtles(turtles) {
    return [...turtles].sort((a, b) => {
        const al = a.alive ? 1 : 0;
        const bl = b.alive ? 1 : 0;
        if (bl !== al) return bl - al; // connected first
        return (a.id || 0) - (b.id || 0); // then by id
    });
}

function renderList(turtles, routines) {
    const sorted = sortTurtles(turtles);
    el.list.innerHTML = sorted.map(renderTurtle).join('');
    for (const item of el.list.querySelectorAll('.turtle')) {
        bindItemHandlers(item, routines);
    }
    // Re-apply expanded state after render
    for (const item of el.list.querySelectorAll('.turtle')) {
        const id = item.dataset.id;
        if (state.expanded.has(id)) {
            const details = item.querySelector('.details');
            const exp = item.querySelector('.expand');
            if (details) details.classList.add('open');
            if (exp) exp.classList.add('rot');
        }
    }
    for (const t of sorted) {
        hydrateConsoleFromState(t.id);
    }
}

function updateTurtleData(turtles) {
    // Update only the data fields without rebuilding HTML to preserve focus
    for (const t of turtles) {
        const item = el.list.querySelector(`.turtle[data-id="${t.id}"]`);
        if (!item) continue;

        // Check if any element in this turtle has focus - if so, skip updates
        const hasFocus = item.contains(document.activeElement);
        if (hasFocus) continue;

        // Update fuel
        const fuelEl = item.querySelector('.fuel');
        if (fuelEl) fuelEl.textContent = `Fuel: ${t.fuel_level ?? '—'}`;

        // Update coordinates
        const coords = t.coords ?? {};
        const xEl = item.querySelector('.coord-x');
        const yEl = item.querySelector('.coord-y');
        const zEl = item.querySelector('.coord-z');
        const hEl = item.querySelector('.coord-heading');
        if (xEl) xEl.textContent = coords.x ?? '—';
        if (yEl) yEl.textContent = coords.y ?? '—';
        if (zEl) zEl.textContent = coords.z ?? '—';
        if (hEl) hEl.textContent = headingToText(t.heading);

        // Update turtle title/label
        const titleEl = item.querySelector('.title');
        if (titleEl) {
            if (t.label) {
                titleEl.textContent = `${t.label} (#${t.id})`;
            } else {
                titleEl.textContent = `Turtle #${t.id}`;
            }
        }

        // Update inventory only if details panel is not expanded (to avoid focus issues)
        const details = item.querySelector('.details');
        if (!details || !details.classList.contains('open')) {
            const invEl = item.querySelector('.inventory');
            if (invEl) invEl.innerHTML = inventoryGrid(t.inventory);
        }

        // Update last seen
        const uptimeEl = item.querySelector('.uptime');
        if (uptimeEl) {
            uptimeEl.dataset.since = t.last_seen_ms || 0;
            uptimeEl.textContent = sinceString(t.last_seen_ms || 0);
        }
    }
}

async function bootstrap() {
    const [turtles, routinesRaw] = await Promise.all([
        fetchJSON('/turtles'),
        fetchJSON('/routines'),
    ]);
    renderList(turtles, routinesRaw);
    // Uptime clock
    setInterval(() => {
        for (const item of el.list.querySelectorAll('.turtle')) {
            const since = Number(item.querySelector('.uptime')?.dataset.since || '0');
            const up = item.querySelector('.uptime');
            if (up) up.textContent = sinceString(since);
        }
    }, 1000);

    // Real-time updates via WebSocket events only - no polling needed
    let cachedRoutines = routinesRaw;

    // WebSocket events
    let wsProto = location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${wsProto}://${location.host}/events`);
    ws.addEventListener('open', () => {
        dbg('ws open');
        el.badge.textContent = 'Live';
    });
    ws.addEventListener('close', () => {
        dbg('ws close');
        el.badge.textContent = 'Disconnected';
    });
    ws.addEventListener('message', async (ev) => {
        try {
            const data = JSON.parse(ev.data);
            dbg('ws msg', data);
            if (!data || !data.type) return;

            // Handle turtle connection/disconnection and state updates
            if (data.type === 'connected' || data.type === 'disconnected' || data.type === 'state_updated') {
                const t = data.turtle;
                if (t && typeof t === 'object') {
                    // Check if this turtle already exists in the UI
                    const existingTurtle = el.list.querySelector(`.turtle[data-id="${t.id}"]`);

                    if (!existingTurtle && data.type === 'connected') {
                        // New turtle connected - need to add it to the list
                        dbg('New turtle connected, refreshing list');
                        try {
                            const [turtles] = await Promise.all([fetchJSON('/turtles')]);
                            renderList(turtles, cachedRoutines);
                        } catch (e) {
                            dbg('Error refreshing turtle list for new connection', e);
                        }
                    } else if (existingTurtle) {
                        // Update existing turtle's data in real-time
                        updateTurtleData([t]);

                        // Update connection status
                        const statusEl = existingTurtle.querySelector('.status');
                        const titleEl = existingTurtle.querySelector('.title');

                        if (statusEl) {
                            if (data.type === 'connected') {
                                statusEl.textContent = 'connected';
                                statusEl.className = 'status connected';
                            } else if (data.type === 'disconnected') {
                                statusEl.textContent = 'disconnected';
                                statusEl.className = 'status disconnected';
                            }
                        }

                        // Update title if label changed
                        if (titleEl && t.label) {
                            titleEl.textContent = `${t.label} (#${t.id})`;
                        } else if (titleEl) {
                            titleEl.textContent = `Turtle #${t.id}`;
                        }
                    }
                }
            }
            // Handle routine lifecycle events
            else if (data.type?.startsWith('routine_')) {
                const tEl = el.list.querySelector(`.turtle[data-id="${data.turtle_id}"]`);
                if (tEl) {
                    turtleConsole(data.turtle_id).push(`[event] ${data.type}${data.error ? ' ' + data.error : ''}`);

                    const toggle = tEl.querySelector('.toggle');
                    const routineEl = tEl.querySelector('.routine-name');

                    if (toggle) {
                        if (data.type === 'routine_started') {
                            toggle.textContent = 'Stop';
                        } else if (data.type === 'routine_paused') {
                            toggle.textContent = 'Continue';
                        } else if (data.type === 'routine_finished' || data.type === 'routine_cancelled' || data.type === 'routine_failed') {
                            toggle.textContent = 'Start';
                        }
                    }

                    // Update routine name display
                    if (routineEl) {
                        if (data.routine) {
                            routineEl.textContent = data.routine;
                        } else if (data.type === 'routine_finished' || data.type === 'routine_cancelled' || data.type === 'routine_failed') {
                            routineEl.textContent = '—';
                        }
                    }
                }
            }
            // Handle log messages
            else if (data.type === 'log') {
                if (data.turtle_id != null) {
                    turtleConsole(data.turtle_id).push(data.message);
                }
            }
        } catch (e) {
            dbg('ws message handler error', e);
        }
    });
}

bootstrap().catch(err => {
    console.error(err);
    el.badge.textContent = 'Error';
});


