// Codex self-heal guard: runs inside the Codex desktop renderer (main world).
//
// The desktop app routes every renderer->host request through the
// `codex-message-from-view` window event and every host->renderer reply
// through window `message` events. Several renderer awaits have no timeout,
// so one reply that never resolves its waiter (observed: thread/queue/list,
// skills/list, vscode://codex/* fetches) wedges the queue, the composer or
// startup. The guard watches that bus. For an exact list of read-only
// requests it sends the same request again under its own id and hands the
// real reply to the original request. It never re-sends or fails writes.
//
// Two app-version-specific corrections (enabled only for verified versions):
// - Resume: the app-server queue's resume() returns early while the thread is
//   open in this window, so Resume after an interrupt never starts the queue.
// - Startup: a cold start can miss the one-off app-server "initialized"
//   message; the guard asks the host to re-send the initialization snapshot.
(() => {
  const VERSION = '2.0.1';
  const existing = window.__codexSelfHealGuard;
  if (existing && existing.version === VERSION) return existing.status();
  if (existing && typeof existing.dispose === 'function') existing.dispose();

  // App versions whose internals the two corrections were verified against.
  // Values of electronBridge.getSentryInitOptions().appVersion (package 26.928.3736.0 reports 26.928.31416, 26.928.4866.0 reports 26.928.40906).
  const VERIFIED_APP_VERSIONS = ['26.928.31416', '26.928.40906'];

  const cfg = {
    tickMs: 5000,
    mcpReplayAfterMs: 45000,
    mcpConfirmedReplayAfterMs: 5000,
    mcpCandidateReportAfterMs: 5000,
    fetchReplayAfterMs: 30000,
    replayIntervalMs: 45000,
    maxReplays: 3,
    replayTtlMs: 120000,
    lateReplyTtlMs: 120000,
    maxTransfers: 4,
    transferTtlMs: 60000,
    resumeFix: true,
    initSnapshotFix: true,
    initSnapshotAfterMs: 8000,
    now: () => Date.now(),
  };

  // Requests seen in this app version that only read state. Exact names only.
  const MCP_REPLAYABLE = new Set([
    'thread/queue/list', 'thread/list', 'thread/read', 'thread/turns/list', 'thread/items/list',
    'thread/attachment/list', 'thread/goal/get', 'thread/loaded/list', 'skills/list', 'app/read',
    'app/installed', 'plugin/installed', 'plugin/list', 'plugin/read', 'config/read',
    'configRequirements/read', 'account/read', 'account/gatewayOAuth/read', 'getAuthStatus', 'model/list',
    'experimentalFeature/list', 'mcpServerStatus/list', 'hooks/list', 'collaborationMode/list',
    'permissionProfile/list', 'windowsSandbox/readiness', 'remoteControl/status/read',
    'fs/getMetadata', 'fs/readDirectory', 'fs/readFile',
  ]);
  const FETCH_REPLAYABLE = new Set([
    'get-global-state', 'get-setting', 'codex-home', 'workspace-root-options', 'projectless-workspace-root',
    'os-info', 'locale-info', 'inbox-items', 'list-automations', 'git-origins', 'paths-exist',
    'codex-command-keymap-state', 'is-copilot-api-available', 'is-packaged', 'read-file-metadata',
  ]);
  const CHUNK_MARKER = 'codex-host-chunked-message-v1';
  const OWN_PREFIX = 'guard-';

  const pending = { mcp: new Map(), fetch: new Map() };  // original id -> entry
  const replays = new Map();     // own id -> { bus, entry, createdAt }
  const recovered = new Map();   // original id -> expiry; late original replies are dropped
  const transfers = new Map();
  const ring = [];
  const outbox = [];
  const counters = { replayed: 0, recovered: 0, lateDropped: 0, confirmedLost: 0 };
  let generation = 0;
  let disposed = false;

  function report(event) {
    const record = { t: cfg.now(), ...event };
    ring.push(record);
    if (ring.length > 200) ring.splice(0, ring.length - 200);
    outbox.push(record);
    if (outbox.length > 500) outbox.splice(0, outbox.length - 500);
  }

  function appVersion() {
    try {
      const options = window.electronBridge && window.electronBridge.getSentryInitOptions && window.electronBridge.getSentryInitOptions();
      return options && typeof options.appVersion === 'string' ? options.appVersion : null;
    } catch {
      return null;
    }
  }
  let verifiedApp = (() => {
    const version = appVersion();
    return !!version && VERIFIED_APP_VERSIONS.some((v) => version === v || version.startsWith(v + '.'));
  })();

  function snapshot(value) {
    try { return structuredClone(value); } catch { return JSON.parse(JSON.stringify(value)); }
  }

  function bridgeSend(message) {
    const bridge = window.electronBridge;
    if (!bridge || typeof bridge.sendMessageFromView !== 'function') throw new Error('bridge unavailable');
    const result = bridge.sendMessageFromView(message);
    if (result && typeof result.catch === 'function') result.catch(() => {});
  }

  function deliver(data) {
    const event = new MessageEvent('message', { data });
    Object.defineProperty(event, '__codexGuardSynthetic', { value: true });
    window.dispatchEvent(event);
  }

  function fetchPath(url) {
    return typeof url === 'string' && url.startsWith('vscode://codex/') ? url.slice(15).split('?')[0] : null;
  }

  function own(id) {
    return typeof id === 'string' && id.startsWith(OWN_PREFIX);
  }

  function track(bus, id, entry) {
    recovered.delete(id); // the id now belongs to a new request
    pending[bus].set(id, entry);
  }

  function onOutgoing(event) {
    if (disposed) return;
    const d = event.detail;
    if (!d || typeof d !== 'object') return;
    if (d.type === 'mcp-request' && d.request && typeof d.request.id === 'string' && typeof d.request.method === 'string') {
      if (own(d.request.id)) return;
      if (!MCP_REPLAYABLE.has(d.request.method)) { recovered.delete(d.request.id); pending.mcp.delete(d.request.id); return; }
      track('mcp', d.request.id, {
        gen: ++generation, detail: snapshot(d), name: d.request.method, hostId: d.hostId, startedAt: cfg.now(),
        replayCount: 0, lastReplayAt: 0, confirmedLost: false, candidateReported: false,
      });
    } else if (d.type === 'fetch' && typeof d.requestId === 'string') {
      if (own(d.requestId)) return;
      const path = fetchPath(d.url);
      if (path == null || !FETCH_REPLAYABLE.has(path)) { recovered.delete(d.requestId); pending.fetch.delete(d.requestId); return; }
      track('fetch', d.requestId, {
        gen: ++generation, detail: snapshot(d), name: path, startedAt: cfg.now(), replayCount: 0, lastReplayAt: 0,
      });
    } else if (d.type === 'cancel-fetch' && typeof d.requestId === 'string') {
      pending.fetch.delete(d.requestId);
    } else if (d.type === 'mcp-request-abandon' && typeof d.requestId === 'string') {
      pending.mcp.delete(d.requestId);
    }
  }

  // A reply arrived on the bus (event is null for reassembled chunked replies).
  function settle(bus, id, data, event) {
    const replay = replays.get(id);
    if (replay && replay.bus === bus) {
      replays.delete(id);
      if (event) event.stopImmediatePropagation();
      const entry = replay.entry;
      const originalId = entry.id;
      // Deliver only to the very request this replay was made for.
      if (pending[bus].get(originalId) !== entry) return;
      if (bus === 'mcp' && data.hostId !== entry.hostId) return;
      pending[bus].delete(originalId);
      recovered.set(originalId, cfg.now() + cfg.lateReplyTtlMs);
      counters.recovered++;
      const failed = bus === 'mcp' ? !!(data.message && data.message.error) : data.responseType === 'error';
      report({ kind: 'recovered', bus, [bus === 'mcp' ? 'method' : 'path']: entry.name, ageMs: cfg.now() - entry.startedAt, replays: entry.replayCount, error: failed || undefined });
      deliver(bus === 'mcp' ? { ...data, message: { ...data.message, id: originalId } } : { ...data, requestId: originalId });
      return;
    }
    const until = recovered.get(id);
    if (until != null) {
      // The original reply arrived after the replay already answered it.
      recovered.delete(id);
      if (until >= cfg.now()) {
        if (event) event.stopImmediatePropagation();
        counters.lateDropped++;
        return;
      }
    }
    pending[bus].delete(id);
  }

  // Chunked replies: the app reassembles and acknowledges the parts itself and
  // never re-dispatches the result on window, so the guard reads the parts too.
  // It extracts the reply id cheaply for every transfer and keeps the full
  // value only while one of its own replays is outstanding.
  function onChunk(part) {
    if (part.kind === 'start') {
      if (transfers.size >= cfg.maxTransfers) {
        const oldest = [...transfers.entries()].sort((a, b) => a[1].startedAt - b[1].startedAt)[0];
        if (oldest) transfers.delete(oldest[0]);
      }
      transfers.set(part.transferId, {
        next: part.sequence + 1, startedAt: cfg.now(), keep: replays.size > 0,
        stack: [], root: undefined, hasRoot: false, str: null, strTarget: null, type: null, id: null, failed: false,
      });
      return;
    }
    const t = transfers.get(part.transferId);
    if (!t) return;
    if (part.sequence !== t.next) { transfers.delete(part.transferId); return; }
    t.next++;
    if (part.kind === 'chunk') {
      try { consume(t, part.tokens); } catch { t.failed = true; }
      return;
    }
    transfers.delete(part.transferId);
    if (part.kind !== 'end' || t.failed || t.stack.length || t.str) return;
    const bus = t.type === 'mcp-response' ? 'mcp' : t.type === 'fetch-response' ? 'fetch' : null;
    if (!bus || typeof t.id !== 'string') return;
    if (replays.has(t.id)) {
      if (t.keep && t.hasRoot) settle(bus, t.id, t.root, null);
      else replays.delete(t.id); // too large to keep; the next replay retries
      return;
    }
    settle(bus, t.id, null, null);
  }

  function consume(t, tokens) {
    const path = () => t.stack.map((frame) => frame.key);
    // Containers stay attached to their parent key until their own end token.
    const save = (value, container) => {
      const top = t.stack[t.stack.length - 1];
      if (!container) {
        const at = path();
        if (at.length === 1 && at[0] === 'type' && t.type == null) t.type = value;
        if (at.length === 1 && at[0] === 'requestId' && t.id == null) t.id = value;
        if (at.length === 2 && at[0] === 'message' && at[1] === 'id' && t.id == null) t.id = value;
      }
      if (!top) {
        if (t.hasRoot) throw new Error('multiple roots');
        t.root = value; t.hasRoot = true;
        return;
      }
      if (top.array) { if (t.keep) top.value.push(value); return; }
      if (top.key == null) throw new Error('missing key');
      if (t.keep) Object.defineProperty(top.value, top.key, { value, enumerable: true, writable: true, configurable: true });
      if (!container) top.key = null;
    };
    for (const token of tokens) {
      switch (token.type) {
        case 'array-start': { const v = t.keep ? [] : null; save(v, true); t.stack.push({ array: true, value: v, key: null }); break; }
        case 'object-start': { const v = t.keep ? {} : null; save(v, true); t.stack.push({ array: false, value: v, key: null }); break; }
        case 'container-end': {
          if (!t.stack.pop()) throw new Error('unmatched end');
          const parent = t.stack[t.stack.length - 1];
          if (parent && !parent.array) parent.key = null;
          break;
        }
        case 'key': t.stack[t.stack.length - 1].key = token.value; break;
        case 'value': save(token.value, false); break;
        case 'string-start': t.str = []; t.strTarget = token.target; break;
        case 'string-chunk': t.str.push(token.value); break;
        case 'string-end': {
          const s = t.str.join(''); const target = t.strTarget; t.str = null; t.strTarget = null;
          if (target === 'key') t.stack[t.stack.length - 1].key = s; else save(s, false);
          break;
        }
        default: throw new Error('unknown token');
      }
    }
  }

  function onIncoming(event) {
    if (disposed || event.__codexGuardSynthetic) return;
    const d = event.data;
    if (!d || typeof d !== 'object') return;
    if (d.marker === CHUNK_MARKER && typeof d.transferId === 'string') { onChunk(d); return; }
    if (d.type === 'mcp-response' && d.message && typeof d.message.id === 'string') settle('mcp', d.message.id, d, event);
    else if (d.type === 'fetch-response' && typeof d.requestId === 'string') settle('fetch', d.requestId, d, event);
    else if (d.type === 'mcp-request-delivery' && d.update && d.update.type === 'failed') {
      const id = d.update.delivery && d.update.delivery.requestId;
      if (typeof id === 'string') pending.mcp.delete(id);
    }
  }

  function replay(bus, id, entry, reason) {
    entry.id = id;
    const newId = OWN_PREFIX + (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2));
    let message;
    if (bus === 'mcp') {
      // The original deadline fields describe the lost attempt, not this one.
      const { trace, dispatchedAtMs, expiresAtMs, timeoutMs, ...rest } = entry.detail;
      const request = { ...entry.detail.request, id: newId };
      delete request.trace;
      message = { ...rest, type: 'mcp-request', request };
    } else {
      message = { ...entry.detail, type: 'fetch', requestId: newId };
    }
    replays.set(newId, { bus, entry, createdAt: cfg.now() });
    entry.replayCount++;
    entry.lastReplayAt = cfg.now();
    counters.replayed++;
    report({ kind: 'replay', bus, [bus === 'mcp' ? 'method' : 'path']: entry.name, ageMs: cfg.now() - entry.startedAt, attempt: entry.replayCount, reason });
    try { bridgeSend(message); } catch { replays.delete(newId); report({ kind: 'replay-failed', bus, name: entry.name }); }
  }

  function tick() {
    if (disposed) return;
    const now = cfg.now();
    for (const [id, until] of recovered) if (until < now) recovered.delete(id);
    for (const [id, r] of replays) if (now - r.createdAt > cfg.replayTtlMs) replays.delete(id);
    for (const [id, t] of transfers) if (now - t.startedAt > cfg.transferTtlMs) transfers.delete(id);
    for (const bus of ['mcp', 'fetch']) {
      for (const [id, entry] of pending[bus]) {
        const age = now - entry.startedAt;
        if (bus === 'mcp' && !entry.candidateReported && age >= cfg.mcpCandidateReportAfterMs) {
          entry.candidateReported = true;
          report({ kind: 'candidate', bus, id, method: entry.name, ageMs: age, startedAt: entry.startedAt });
        }
        if (entry.replayCount >= cfg.maxReplays) {
          if (now - entry.lastReplayAt > cfg.replayIntervalMs) {
            pending[bus].delete(id);
            report({ kind: 'gave-up', bus, [bus === 'mcp' ? 'method' : 'path']: entry.name, ageMs: age });
          }
          continue;
        }
        const firstAfter = bus === 'mcp' ? (entry.confirmedLost ? cfg.mcpConfirmedReplayAfterMs : cfg.mcpReplayAfterMs) : cfg.fetchReplayAfterMs;
        const due = entry.replayCount === 0 ? age >= firstAfter : now - entry.lastReplayAt >= cfg.replayIntervalMs;
        if (due) replay(bus, id, entry, entry.confirmedLost ? 'confirmed' : 'deadline');
      }
    }
  }

  // --- App-version-specific corrections ------------------------------------

  let registry = null;
  let lastRegistryScan = 0;
  let versionSkipReported = false;
  const resumePatches = [];  // { queue, original, wrapper }

  function findRegistry() {
    const host = document.getElementById('root') || document.body;
    const rootEl = host && [host, ...host.querySelectorAll('*')].find((el) => Object.keys(el).some((k) => k.startsWith('__reactContainer$')));
    if (!rootEl) return null;
    const key = Object.keys(rootEl).find((k) => k.startsWith('__reactContainer$'));
    const stack = [rootEl[key]];
    let fibers = 0;
    while (stack.length && fibers < 100000) {
      const fiber = stack.pop();
      if (!fiber) continue;
      fibers++;
      let hook = fiber.memoizedState;
      for (let i = 0; hook && i < 60; i++, hook = hook.next) {
        const value = hook.memoizedState;
        if (value && typeof value === 'object' && typeof value.getImplForHostId === 'function' && typeof value.getAll === 'function') return value;
      }
      if (fiber.sibling) stack.push(fiber.sibling);
      if (fiber.child) stack.push(fiber.child);
    }
    return null;
  }

  function managers() {
    if (!registry && cfg.now() - lastRegistryScan > 5000) {
      lastRegistryScan = cfg.now();
      try { registry = findRegistry(); } catch { registry = null; }
    }
    if (!registry) return [];
    try { return registry.getAll() || []; } catch { return []; }
  }

  let initRequests = 0;
  let lastInitRequest = 0;
  const documentStartedAt = typeof performance !== 'undefined' ? performance.timeOrigin : cfg.now();

  function initSnapshotFix(list) {
    if (cfg.now() - documentStartedAt < cfg.initSnapshotAfterMs) return;
    const missing = list.filter((m) => m && m.requestClient && m.requestClient.appServerVersion == null && (!m.getHostId || m.getHostId() === 'local'));
    if (!missing.length || initRequests >= 6 || cfg.now() - lastInitRequest < 10000) return;
    initRequests++;
    lastInitRequest = cfg.now();
    report({ kind: 'init-snapshot-requested', attempt: initRequests });
    try { bridgeSend({ type: 'ready', initializationOnly: true }); } catch {}
  }

  function overrideStreaming(manager, threadId) {
    const key = 'isConversationStreaming';
    const ownDescriptor = Object.getOwnPropertyDescriptor(manager, key);
    if (ownDescriptor && !ownDescriptor.configurable) return null;
    const inherited = manager[key];
    Object.defineProperty(manager, key, {
      configurable: true, writable: true, enumerable: false,
      value: function (id) { return id === threadId ? false : inherited.call(this, id); },
    });
    return () => {
      if (ownDescriptor) Object.defineProperty(manager, key, ownDescriptor);
      else delete manager[key];
    };
  }

  function resumeFix(list) {
    for (const manager of list) {
      const coordinator = manager && manager.turnCoordinator;
      const queue = coordinator && coordinator.serverQueue;
      const host = coordinator && coordinator.options && coordinator.options.submissionHost;
      if (!queue || typeof queue.resume !== 'function' || queue.resume.__codexGuardResumeFix || !host) continue;
      if (typeof manager.isConversationStreaming !== 'function' || typeof host.getActiveTurnId !== 'function' || typeof host.hasPendingTurnStart !== 'function') continue;
      const original = queue.resume;
      const inflight = new Map();
      const wrapper = function (threadId, ...rest) {
        if (disposed || !cfg.resumeFix) return original.call(this, threadId, ...rest);
        if (inflight.has(threadId)) return inflight.get(threadId);
        let busy = true;
        try { busy = host.getActiveTurnId(threadId) != null || host.hasPendingTurnStart(threadId); } catch {}
        if (busy || !manager.isConversationStreaming(threadId)) return original.call(this, threadId, ...rest);
        const restore = overrideStreaming(manager, threadId);
        if (!restore) return original.call(this, threadId, ...rest);
        let result;
        try {
          // The streaming check is the first synchronous statement of resume().
          result = original.call(this, threadId, ...rest);
        } finally {
          restore();
        }
        report({ kind: 'resume-fix', host: manager.getHostId ? manager.getHostId() : undefined });
        const promise = Promise.resolve(result);
        inflight.set(threadId, promise);
        promise.finally(() => inflight.delete(threadId)).catch(() => {});
        return result;
      };
      Object.defineProperty(wrapper, '__codexGuardResumeFix', { value: true });
      queue.resume = wrapper;
      resumePatches.push({ queue, original, wrapper });
      report({ kind: 'resume-fix-installed', host: manager.getHostId ? manager.getHostId() : undefined });
    }
  }

  function corrections() {
    if (disposed || (!cfg.resumeFix && !cfg.initSnapshotFix)) return;
    if (!verifiedApp) {
      if (!versionSkipReported) { versionSkipReported = true; report({ kind: 'corrections-skipped', appVersion: appVersion() }); }
      return;
    }
    const list = managers();
    if (cfg.initSnapshotFix) initSnapshotFix(list);
    if (cfg.resumeFix) resumeFix(list);
  }

  window.addEventListener('codex-message-from-view', onOutgoing);
  window.addEventListener('message', onIncoming, { capture: true });
  const timer = setInterval(() => {
    try { tick(); } catch (error) { report({ kind: 'tick-error', message: String(error && error.message).slice(0, 200) }); }
    try { corrections(); } catch (error) { report({ kind: 'corrections-error', message: String(error && error.message).slice(0, 200) }); }
  }, cfg.tickMs);

  const api = {
    version: VERSION,
    // Set by the companion when it injects the guard before the app's scripts.
    installedAtDocumentStart: window.__codexGuardInjectedAtStart === true,
    get verifiedApp() { return verifiedApp; },
    cfg,
    tick,
    corrections,
    setRegistryForTest(value) { registry = value; },
    setVerifiedForTest(value) { verifiedApp = !!value; },
    // Called by the companion after the host log shows it already routed
    // this reply while the request is still waiting here.
    confirmLost(id) {
      const entry = pending.mcp.get(id);
      if (!entry) return false;
      entry.confirmedLost = true;
      counters.confirmedLost++;
      tick();
      return true;
    },
    // The companion process polls this; returns and clears pending reports.
    drain() {
      return { status: api.status(), events: outbox.splice(0, outbox.length) };
    },
    status() {
      const now = cfg.now();
      const oldest = (map) => [...map.values()].reduce((m, e) => Math.max(m, now - e.startedAt), 0);
      return {
        version: VERSION,
        verifiedApp,
        pendingMcp: pending.mcp.size,
        pendingFetch: pending.fetch.size,
        outstandingReplays: replays.size,
        oldestMcp: oldest(pending.mcp),
        oldestFetch: oldest(pending.fetch),
        counters: { ...counters },
        recent: ring.slice(-20),
      };
    },
    dispose() {
      disposed = true;
      clearInterval(timer);
      window.removeEventListener('codex-message-from-view', onOutgoing);
      window.removeEventListener('message', onIncoming, { capture: true });
      for (const patch of resumePatches) if (patch.queue.resume === patch.wrapper) patch.queue.resume = patch.original;
      resumePatches.length = 0;
      if (window.__codexSelfHealGuard === api) delete window.__codexSelfHealGuard;
    },
  };
  Object.defineProperty(window, '__codexSelfHealGuard', { value: api, configurable: true, writable: false, enumerable: false });
  report({ kind: 'installed', version: VERSION, verifiedApp, atStart: api.installedAtDocumentStart, href: location.pathname + location.search.slice(0, 60) });
  return api.status();
})();
