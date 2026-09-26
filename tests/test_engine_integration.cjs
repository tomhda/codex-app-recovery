const fs = require('node:fs');
const assert = require('node:assert/strict');
const { JSDOM } = require('jsdom');
const { QueryClient, QueryObserver } = require('@tanstack/query-core');
const engineSource = fs.readFileSync(__dirname + '/../engine.js', 'utf8');
const pause = () => new Promise(resolve => setTimeout(resolve, 15));

async function scenario({ modelVisible = false, unrelated = true, descendantScope = false, context = null, outsideSibling = false, unknownComposer = false } = {}) {
  const dom = new JSDOM('<div id="root"><div id="history">model effort reasoning context コンテキスト モデル</div><section id="composer" data-composer-layout="multiline"><div contenteditable="true" role="textbox"></div></section></div>', { url: 'app://-/index.html', runScripts: 'outside-only' });
  const { window } = dom;
  Object.defineProperty(window.HTMLElement.prototype, 'innerText', { get() { return this.textContent; } });
  window.HTMLElement.prototype.getClientRects = function () { return this.hidden ? [] : [{ width: 800, height: 40 }]; };
  const root = window.document.getElementById('root');
  const composer = window.document.getElementById('composer');
  function showPicker() {
    if (!composer.querySelector('[data-codex-intelligence-trigger]')) {
      composer.insertAdjacentHTML('beforeend', '<button data-codex-intelligence-trigger="true" data-composer-navigation-target="reasoning" data-selected-reasoning-effort="medium">Fixture model Medium</button>');
    }
  }
  if (modelVisible) showPicker();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  const cwd = 'C:\\fixture\\current';
  const props = { composerMode: 'local', permissionsCwdOverride: cwd, permissionsHostId: 'local', executionTargetHostId: 'local', conversationId: context ? 'fixture-thread' : null, isHomeLayout: !context, defaultCwd: cwd, selectedProject: 'fixture-project' };
  const composerFiber = { memoizedProps: props, memoizedState: null, child: { memoizedProps: { 'data-composer-layout': 'multiline' }, stateNode: composer } };
  const providerFiber = { memoizedProps: { queryClient: client }, child: composerFiber };
  composerFiber.return = providerFiber;
  composerFiber.child.return = composerFiber;
  root.__reactContainer$fixture = { stateNode: { current: providerFiber } };
  composer.__reactFiber$fixture = composerFiber.child;
  const input = composer.querySelector('[contenteditable]');
  input.__reactFiber$fixture = { stateNode: input, memoizedProps: { contentEditable: true }, return: composerFiber.child };
  if (descendantScope) {
    const wrapper = composerFiber.child;
    composerFiber.memoizedProps = { conversationId: context ? 'fixture-thread' : null };
    const footerProps = { ...props };
    delete footerProps.conversationId;
    wrapper.child = { memoizedProps: footerProps, return: wrapper };
  }
  if (outsideSibling || unknownComposer) {
    const sibling = window.document.createElement('section'); sibling.setAttribute('data-composer-layout', 'multiline');
    sibling.innerHTML = '<div contenteditable="true" role="textbox"></div>'; root.append(sibling);
    const siblingFiber = { memoizedProps: outsideSibling ? { composerMode: 'local', permissionsCwdOverride: 'C:\\fixture\\other', permissionsHostId: 'local', executionTargetHostId: 'local', conversationId: 'other' } : {}, child: null, sibling: null };
    const siblingNodeFiber = { memoizedProps: { 'data-composer-layout': 'multiline' }, stateNode: sibling, return: siblingFiber };
    siblingFiber.child = siblingNodeFiber; composerFiber.sibling = siblingFiber;
    sibling.__reactFiber$fixture = siblingNodeFiber;
  }
  if (context) {
    const element = window.document.createElement('span');
    element.setAttribute('aria-label', 'コンテキスト使用量: 30%');
    element.hidden = context === 'hidden';
    composer.append(element);
    const usageParent = composerFiber.child.child || composerFiber.child;
    const usageFiber = { memoizedProps: { contextUsage: { percent: 30, usedTokens: 300, contextWindow: 1000, remainingTokens: 700 } }, return: usageParent };
    element.__reactFiber$fixture = { memoizedProps: { 'aria-label': 'コンテキスト使用量: 30%' }, stateNode: element, return: usageFiber };
    usageParent.child = usageFiber;
  }
  client.setQueryData(['experimental-features', 'list', 'local'], [{ name: 'in_app_browser', enabled: true }, { name: 'in_app_local_automation', enabled: true }]);
  client.setQueryData(['config', 'user', 'local'], { readSucceeded: true, response: { config: { model: 'fixture' } } });
  client.setQueryData(['models', 'list', 'local', 'chatgpt', 100], { data: [{ model: 'fixture' }] });
  let transportReady = false;
  let requests = 0;
  const keys = {
    leaf: ['config', 'read-response', 'local', cwd, true],
    layer: ['config', 'layered-response', 'local', cwd],
    parent: ['config', 'effective', 'local', cwd]
  };
  const loadLeaf = () => client.fetchQuery({ queryKey: keys.leaf, staleTime: 0, queryFn: () => {
    requests++;
    return transportReady ? Promise.resolve({ config: { model: 'fixture' }, readSucceeded: true }) : new Promise(() => {});
  } });
  const loadLayer = () => client.fetchQuery({ queryKey: keys.layer, staleTime: 300000, queryFn: async () => {
    try { return await loadLeaf(); } catch { return { config: { model: null }, readSucceeded: false }; }
  } });
  const observer = new QueryObserver(client, { queryKey: keys.parent, queryFn: loadLayer, staleTime: 300000 });
  const unsubs = [observer.subscribe(result => { if (result.data?.readSucceeded) showPicker(); })];
  const extraKeys = [];
  if (unrelated) {
    for (const key of [
      ['config', 'read-response', 'local', 'C:\\fixture\\other', true],
      ['config', 'effective', 'local', 'C:\\fixture\\other'],
      ['models', 'list', 'remote-host', 'chatgpt', 100],
      ['windows-sandbox', 'readiness', 'local']
    ]) {
      const extra = new QueryObserver(client, { queryKey: key, queryFn: () => new Promise(() => {}) });
      unsubs.push(extra.subscribe(() => {}));
      extraKeys.push(key);
    }
  }
  await pause();
  const engine = window.eval(`(${engineSource})`);
  const call = (action = 'snapshot', params = {}) => engine({ action, ...params });
  const cleanup = () => { unsubs.forEach(fn => fn()); client.clear(); window.close(); };
  return { call, client, keys, extraKeys, ready: () => { transportReady = true; }, requests: () => requests, cleanup };
}

(async () => {
  const fixture = await scenario();
  try {
    const before = await fixture.call();

    assert.equal(before.ui.modelPicker, false, 'history text must not count as a model picker');
    assert.equal(before.ui.degraded, true);
    assert.equal(before.ui.scopeKnown, true);
    for (const key of fixture.extraKeys) {
      const query = before.queries.find(q => JSON.stringify(q.key) === JSON.stringify(key));
      assert.ok(!query?.eligible, 'unrelated read must not be eligible');
    }
    const leaf = before.queries.find(q => JSON.stringify(q.key) === JSON.stringify(fixture.keys.leaf));
    assert.equal(leaf.eligible, true, 'observed parent should make its leaf eligible');
    fixture.ready();
    const result = await fixture.call('repair', { key: leaf.key, queryId: leaf.queryId, promiseId: leaf.promiseId });
    await pause();

    assert.equal(fixture.client.getQueryData(fixture.keys.parent)?.readSucceeded, true, 'repair must replace the fallback with a real response');
    assert.equal(fixture.requests(), 2, 'one blocked read and one successful retry');
    const after = await fixture.call();
    assert.equal(after.ui.modelPicker, true);
    assert.equal(after.ui.effortPicker, true);
    assert.equal(after.ui.degraded, false);
    for (const key of fixture.extraKeys) {
      const q = fixture.client.getQueryCache().find({ queryKey: key, exact: true });
      assert.equal(q.state.fetchStatus, 'fetching', 'unrelated read must remain untouched');
    }
  } finally { fixture.cleanup(); }
  const healthy = await scenario({ modelVisible: true });
  try {
    const snap = await healthy.call();
    assert.equal(snap.ui.degraded, false);
    assert.ok(snap.queries.filter(q => q.kind !== 'features').every(q => !q.eligible), 'healthy composer must not trigger repair');
  } finally { healthy.cleanup(); }
  const sibling = await scenario({ outsideSibling: true });
  try { const snapshot = await sibling.call(); assert.equal(snapshot.ui.scopeKnown, false, 'outer sibling composer must not widen the scope'); assert.equal(snapshot.ui.degraded, false); } finally { sibling.cleanup(); }
  const mixed = await scenario({ unknownComposer: true });
  try { const snapshot = await mixed.call(); assert.equal(snapshot.ui.scopeKnown, false, 'known plus unknown composer must not mutate'); assert.ok(snapshot.queries.every(q => !q.eligible || q.kind === 'features')); } finally { mixed.cleanup(); }
  const descendant = await scenario({ descendantScope: true });
  try {
    const snapshot = await descendant.call();
    assert.equal(snapshot.ui.scopeKnown, true, 'footer descendant properties must resolve the current scope');
    assert.equal(snapshot.ui.degraded, true);
  } finally { descendant.cleanup(); }
  for (const context of ['visible', 'hidden']) {
    const localized = await scenario({ modelVisible: true, context });
    try {
      const snapshot = await localized.call();
      assert.equal(snapshot.ui.contextState, context, 'real object shape and Japanese label must be recognized');
      assert.equal(snapshot.ui.contextUsage, context === 'visible');
      assert.equal(snapshot.ui.degraded, context === 'hidden');
    } finally { localized.cleanup(); }
  }
  console.log('real_query_client_engine_validation PASS');
})().catch(error => { console.error(error.stack); process.exitCode = 1; });
