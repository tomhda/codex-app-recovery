// Unit tests for guard.js against a fake renderer bus. Run: node tests/test_guard.mjs
import fs from 'node:fs';
import assert from 'node:assert/strict';

const source = fs.readFileSync(new URL('../guard.js', import.meta.url), 'utf8');
const body = 'return ' + source.slice(source.indexOf('(() =>')).trim().replace(/;$/, '');
let failures = 0;

function setup({ loopback = false } = {}) {
  const win = new EventTarget();
  const sent = [];
  const appSeen = [];
  const acks = [];
  win.electronBridge = {
    acknowledgeChunkedMessage: (transferId, sequence) => { acks.push([transferId, sequence]); },
    sendMessageFromView: async (m) => {
      sent.push(m);
      // Some bridges re-announce what they send; the guard must not chase its own ids.
      if (loopback) win.dispatchEvent(new CustomEvent('codex-message-from-view', { detail: m }));
    },
  };
  new Function('window', 'location', body)(win, { pathname: '/index.html', search: '' });
  const guard = win.__codexSelfHealGuard;
  let now = 1_000_000;
  guard.cfg.now = () => now;
  win.addEventListener('message', (e) => { if (e.data && e.data.type) appSeen.push(e.data); });
  const app = {
    request(id, method, params = {}, hostId = 'local') {
      const detail = { type: 'mcp-request', hostId, request: { id, method, params }, priority: 'interactive', expiresAtMs: now + 1000, timeoutMs: 1000 };
      win.dispatchEvent(new CustomEvent('codex-message-from-view', { detail }));
      return detail;
    },
    abandon(id) { win.dispatchEvent(new CustomEvent('codex-message-from-view', { detail: { type: 'mcp-request-abandon', requestId: id } })); },
    fetch(requestId, path, body = {}) {
      win.dispatchEvent(new CustomEvent('codex-message-from-view', { detail: { type: 'fetch', requestId, method: 'POST', url: 'vscode://codex/' + path, body: JSON.stringify(body) } }));
    },
  };
  const host = {
    mcpResponse(id, result, hostId = 'local') { win.dispatchEvent(new MessageEvent('message', { data: { type: 'mcp-response', hostId, message: { id, result } } })); },
    fetchResponse(requestId, body) { win.dispatchEvent(new MessageEvent('message', { data: { type: 'fetch-response', responseType: 'success', requestId, status: 200, bodyJsonString: JSON.stringify(body) } })); },
    raw(data) { win.dispatchEvent(new MessageEvent('message', { data })); },
  };
  return { win, guard, sent, appSeen, acks, app, host, advance(ms) { now += ms; guard.tick(); } };
}

function test(name, fn, options) {
  const env = setup(options);
  try { fn(env); console.log('ok   ', name); }
  catch (error) { failures++; console.log('FAIL ', name, '\n     ', error.message); }
  finally { env.guard.dispose(); }
}

const M = 'codex-host-chunked-message-v1';
function chunkedReply(host, transferId, id, extraTokens = []) {
  host.raw({ marker: M, kind: 'start', transferId, sequence: 0 });
  host.raw({ marker: M, kind: 'chunk', transferId, sequence: 1, tokens: [
    { type: 'object-start' }, { type: 'key', value: 'type' }, { type: 'value', value: 'mcp-response' },
    { type: 'key', value: 'hostId' }, { type: 'value', value: 'local' },
    { type: 'key', value: 'message' }, { type: 'object-start' }, { type: 'key', value: 'id' }, { type: 'value', value: id },
    { type: 'key', value: 'result' }, { type: 'object-start' }, ...extraTokens,
    { type: 'key', value: 'text' }, { type: 'string-start', target: 'value' }, { type: 'string-chunk', value: 'ab' }, { type: 'string-chunk', value: 'cd' }, { type: 'string-end' },
    { type: 'container-end' }, { type: 'container-end' }, { type: 'container-end' },
  ] });
}

test('lost read reply is replayed and delivered to the original id', ({ sent, appSeen, app, host, advance }) => {
  app.request('orig-1', 'thread/queue/list', { threadId: 'T', cursor: null });
  advance(30_000);
  assert.equal(sent.length, 0, 'no replay before deadline');
  advance(16_000);
  assert.equal(sent.length, 1);
  const replay = sent[0];
  assert.equal(replay.request.method, 'thread/queue/list');
  assert.deepEqual(replay.request.params, { threadId: 'T', cursor: null });
  assert.ok(replay.request.id.startsWith('guard-'));
  assert.equal(replay.expiresAtMs, undefined);
  host.mcpResponse(replay.request.id, { data: [], nextCursor: null });
  assert.equal(appSeen.length, 1, 'app sees exactly one reply');
  assert.equal(appSeen[0].message.id, 'orig-1');
});

test('answered request is never replayed', ({ sent, app, host, advance }) => {
  app.request('orig-2', 'skills/list');
  host.mcpResponse('orig-2', { data: [] });
  advance(300_000);
  assert.equal(sent.length, 0);
});

test('only exact listed methods are tracked', ({ sent, guard, app, advance }) => {
  for (const method of ['turn/start', 'turn/steer', 'thread/resume', 'thread/queue/add', 'thread/queue/start', 'thread/queue/delete', 'thread/settings/update', 'future/read', 'thread/destroy/list2'])
    app.request('w-' + method, method, { threadId: 'T' });
  advance(600_000);
  assert.equal(sent.length, 0);
  assert.equal(guard.status().pendingMcp, 0);
  assert.equal(guard.confirmLost('w-thread/queue/delete'), false, 'writes cannot be failed');
});

test('writes and unknown endpoints on the fetch bus are ignored', ({ sent, guard, appSeen, app, advance }) => {
  app.fetch('f-w', 'set-global-state', { key: 'k', value: 1 });
  app.fetch('f-x', 'worktree-create', {});
  advance(600_000);
  assert.equal(sent.length, 0);
  assert.equal(appSeen.length, 0, 'no synthetic failure');
  assert.equal(guard.status().pendingFetch, 0);
});

test('confirmed lost read is replayed early', ({ sent, guard, app, advance }) => {
  app.request('r3', 'thread/queue/list', { threadId: 'T' });
  advance(4_000);
  guard.confirmLost('r3');
  assert.equal(sent.length, 0, 'not before the confirmed threshold');
  advance(1_500);
  assert.equal(sent.length, 1);
});

test('read gives up quietly after bounded replays', ({ sent, guard, appSeen, app, advance }) => {
  app.request('r4', 'app/read', {});
  for (let i = 0; i < 60; i++) advance(5_000);
  assert.equal(sent.length, 3, 'bounded replays');
  assert.equal(appSeen.length, 0, 'no synthetic error');
  assert.equal(guard.status().pendingMcp, 0);
});

test('own replay ids are not chased when the bridge re-announces them', ({ sent, guard, app, host, advance }) => {
  app.request('r5', 'thread/read', { threadId: 'T' });
  advance(46_000);
  assert.equal(sent.length, 1);
  host.mcpResponse(sent[0].request.id, { thread: {} });
  for (let i = 0; i < 40; i++) advance(10_000);
  assert.equal(sent.length, 1, 'no replay chain');
  assert.equal(guard.status().pendingMcp, 0);
}, { loopback: true });

test('a replay reply never reaches a newer request that reused the id', ({ sent, appSeen, app, host, advance }) => {
  app.request('same', 'thread/read', { threadId: 'A' });
  advance(46_000);
  const replayA = sent[0].request.id;
  app.abandon('same');
  app.request('same', 'thread/read', { threadId: 'B' });
  host.mcpResponse(replayA, { thread: { id: 'A' } });
  assert.equal(appSeen.length, 0, 'A reply must not be delivered as B');
});

test('reply from another host is not delivered', ({ sent, appSeen, app, host, advance }) => {
  app.request('h1', 'thread/read', { threadId: 'A' }, 'local');
  advance(46_000);
  host.mcpResponse(sent[0].request.id, { thread: {} }, 'durable');
  assert.equal(appSeen.length, 0);
});

test('late original reply after recovery is dropped', ({ sent, appSeen, app, host, advance }) => {
  app.request('late', 'thread/queue/list', { threadId: 'T' });
  advance(46_000);
  host.mcpResponse(sent[0].request.id, { data: [] });
  host.mcpResponse('late', { data: [] });
  assert.equal(appSeen.filter((d) => d.message.id === 'late').length, 1);
});

test('replay uses the request as sent, even if the caller mutates it later', ({ sent, app, advance }) => {
  const detail = app.request('mut', 'thread/read', { threadId: 'A' });
  detail.request.params.threadId = 'B';
  advance(46_000);
  assert.equal(sent[0].request.params.threadId, 'A');
});

test('lost fetch read is replayed and delivered', ({ sent, appSeen, app, host, advance }) => {
  app.fetch('f1', 'codex-home', { hostId: 'local' });
  advance(31_000);
  assert.equal(sent.length, 1);
  assert.equal(sent[0].url, 'vscode://codex/codex-home');
  assert.equal(sent[0].body, JSON.stringify({ hostId: 'local' }));
  host.fetchResponse(sent[0].requestId, { codexHome: 'C:\\x' });
  assert.equal(appSeen.length, 1);
  assert.equal(appSeen[0].requestId, 'f1');
});

test('cancelled fetch is forgotten', ({ sent, win, app, advance }) => {
  app.fetch('f2', 'get-global-state', { key: 'k' });
  win.dispatchEvent(new CustomEvent('codex-message-from-view', { detail: { type: 'cancel-fetch', requestId: 'f2' } }));
  advance(200_000);
  assert.equal(sent.length, 0);
});

test('chunked replay reply is reassembled and delivered', ({ sent, appSeen, app, host, advance }) => {
  app.request('r6', 'thread/read', { threadId: 'T', includeTurns: true });
  advance(46_000);
  chunkedReply(host, 'x', sent[0].request.id, [{ type: 'key', value: '__proto__' }, { type: 'value', value: 'kept' }]);
  host.raw({ marker: M, kind: 'end', transferId: 'x', sequence: 2 });
  const delivered = appSeen.filter((d) => d.type === 'mcp-response');
  assert.equal(delivered.length, 1);
  assert.equal(delivered[0].message.id, 'r6');
  assert.equal(delivered[0].message.result.text, 'abcd');
  assert.ok(Object.prototype.hasOwnProperty.call(delivered[0].message.result, '__proto__'), '__proto__ kept as a plain key');
  assert.equal(Object.getPrototypeOf(delivered[0].message.result), Object.prototype);
});

test('a transfer that does not end with "end" is never delivered', ({ sent, appSeen, app, host, advance }) => {
  app.request('r7', 'thread/read', { threadId: 'T' });
  advance(46_000);
  chunkedReply(host, 'y', sent[0].request.id);
  host.raw({ marker: M, kind: 'abort', transferId: 'y', sequence: 2 });
  assert.equal(appSeen.filter((d) => d.type === 'mcp-response').length, 0);
});

test('a normal chunked original reply settles the request', ({ sent, guard, app, host, advance }) => {
  app.request('r8', 'thread/read', { threadId: 'T' });
  chunkedReply(host, 'z', 'r8');
  host.raw({ marker: M, kind: 'end', transferId: 'z', sequence: 2 });
  assert.equal(guard.status().pendingMcp, 0);
  advance(100_000);
  assert.equal(sent.length, 0);
});

test('second install is a no-op', ({ win, guard }) => {
  const again = new Function('window', 'location', body)(win, { pathname: '/', search: '' });
  assert.equal(win.__codexSelfHealGuard, guard);
  assert.equal(again.version, guard.version);
});

function fakeManager({ activeTurn = null, pendingStart = false } = {}) {
  const seen = [];
  class Manager {
    isConversationStreaming(id) { return id === 'T' || id === 'U'; }
    getHostId() { return 'local'; }
  }
  const manager = new Manager();
  let release;
  const queue = {
    // Mirrors the app: returns early while the thread holds a stream role.
    resume(threadId) {
      if (manager.isConversationStreaming(threadId)) { seen.push(['skipped', threadId]); return Promise.resolve(); }
      seen.push(['started', threadId]);
      return new Promise((resolve) => { release = resolve; });
    },
  };
  manager.requestClient = { appServerVersion: '0.159.2' };
  manager.turnCoordinator = { serverQueue: queue, options: { submissionHost: {
    getActiveTurnId: () => activeTurn, hasPendingTurnStart: () => pendingStart,
  } } };
  return { manager, queue, seen, release: () => release && release() };
}

function withManager(guard, manager) {
  guard.setVerifiedForTest(true);
  guard.setRegistryForTest({ getAll: () => [manager], getImplForHostId: () => manager });
  guard.corrections();
}

test('resume fix starts the queue for an idle open thread', ({ guard }) => {
  const { manager, queue, seen } = fakeManager();
  withManager(guard, manager);
  queue.resume('T');
  assert.deepEqual(seen, [['started', 'T']]);
  assert.equal(Object.prototype.hasOwnProperty.call(manager, 'isConversationStreaming'), false, 'override removed');
  assert.equal(manager.isConversationStreaming('U'), true);
});

test('resume fix leaves a running turn alone', ({ guard }) => {
  const { manager, queue, seen } = fakeManager({ activeTurn: 'turn-1' });
  withManager(guard, manager);
  queue.resume('T');
  assert.deepEqual(seen, [['skipped', 'T']]);
});

test('repeated Resume while one is in flight starts only once', ({ guard }) => {
  const { manager, queue, seen } = fakeManager();
  withManager(guard, manager);
  queue.resume('T');
  queue.resume('T');
  assert.deepEqual(seen, [['started', 'T']]);
});

test('resume fix is undone by dispose and by turning it off', ({ guard }) => {
  const { manager, queue, seen } = fakeManager();
  const original = queue.resume;
  withManager(guard, manager);
  assert.notEqual(queue.resume, original);
  guard.cfg.resumeFix = false;
  queue.resume('T');
  assert.deepEqual(seen, [['skipped', 'T']], 'off means original behaviour');
  guard.dispose();
  assert.equal(queue.resume, original, 'restored on dispose');
});

test('own-property override restores an existing own property exactly', ({ guard }) => {
  const { manager, queue } = fakeManager();
  const ownFn = function (id) { return id === 'T'; };
  Object.defineProperty(manager, 'isConversationStreaming', { value: ownFn, writable: true, configurable: true, enumerable: true });
  withManager(guard, manager);
  queue.resume('T');
  assert.equal(manager.isConversationStreaming, ownFn);
  assert.equal(Object.getOwnPropertyDescriptor(manager, 'isConversationStreaming').enumerable, true);
});

test('corrections do nothing on an unverified app version', ({ guard, sent }) => {
  const { manager, queue } = fakeManager();
  const original = queue.resume;
  manager.requestClient.appServerVersion = null;
  guard.cfg.initSnapshotAfterMs = -Infinity;
  guard.setRegistryForTest({ getAll: () => [manager], getImplForHostId: () => manager });
  guard.corrections();
  assert.equal(queue.resume, original);
  assert.equal(sent.length, 0);
});

test('init snapshot request works with the resume fix turned off, throttled', ({ guard, sent, advance }) => {
  const manager = { getHostId: () => 'local', requestClient: { appServerVersion: null } };
  guard.cfg.resumeFix = false;
  guard.cfg.initSnapshotAfterMs = -Infinity;
  withManager(guard, manager);
  assert.deepEqual(sent, [{ type: 'ready', initializationOnly: true }]);
  advance(5_000); guard.corrections();
  assert.equal(sent.length, 1, 'throttled');
  advance(11_000); guard.corrections();
  assert.equal(sent.length, 2);
  manager.requestClient.appServerVersion = '0.159.2';
  advance(11_000); guard.corrections();
  assert.equal(sent.length, 2, 'stops once initialized');
});

test('a chunk part followed by silence is acknowledged again, once', ({ acks, host, advance }) => {
  host.raw({ marker: M, kind: 'start', transferId: 'X', sequence: 0 });
  advance(3_000);
  assert.equal(acks.length, 0, 'not before the stall threshold');
  advance(2_000);
  assert.deepEqual(acks, [['X', 0]]);
  advance(10_000);
  assert.equal(acks.length, 1, 'only once per part');
});

test('a flowing or finished transfer is never acknowledged by the guard', ({ acks, host, advance }) => {
  host.raw({ marker: M, kind: 'start', transferId: 'Y', sequence: 0 });
  advance(3_000);
  host.raw({ marker: M, kind: 'chunk', transferId: 'Y', sequence: 1, tokens: [] });
  advance(3_000);
  host.raw({ marker: M, kind: 'end', transferId: 'Y', sequence: 2 });
  advance(20_000);
  assert.equal(acks.length, 0);
});

test('a later message after the part means the channel moved on', ({ acks, host, advance }) => {
  host.raw({ marker: M, kind: 'start', transferId: 'Z', sequence: 0 });
  advance(1_000);
  host.mcpResponse('unrelated', {});
  advance(10_000);
  assert.equal(acks.length, 0);
});

test('stalled needs a confirmed lost reply and silence', ({ guard, app, host, advance }) => {
  app.request('q-1', 'thread/queue/list', { threadId: 'T' });
  host.mcpResponse('other', {});
  advance(16_000);
  assert.equal(guard.status().stalled, false, 'silence alone is idle, not stalled');
  guard.confirmLost('q-1');
  assert.equal(guard.status().stalled, true);
  host.mcpResponse('other-2', {});
  assert.equal(guard.status().stalled, false, 'anything arriving clears it');
});

test('typing time is reported for the companion', ({ win, guard }) => {
  assert.equal(guard.status().sinceInputMs, null);
  win.dispatchEvent(new Event('keydown'));
  assert.equal(guard.status().sinceInputMs, 0);
});

console.log(failures ? `${failures} failed` : 'all passed');
process.exit(failures ? 1 : 0);
