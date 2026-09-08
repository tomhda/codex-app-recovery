(async function recoveryEngine(request) {
  const rootElement = document.getElementById('root');
  if (!rootElement) throw new Error('Codex の画面を確認できません。');
  const containerKey = Object.keys(rootElement).find(k => k.startsWith('__reactContainer$'));
  const fiberRoot = window.__codexRoot?._internalRoot?.current ||
    rootElement[containerKey]?.stateNode?.current || rootElement[containerKey]?.current || rootElement[containerKey];
  if (!fiberRoot) throw new Error('このバージョンの画面構造には対応していません。');
  const clients = new Set(), objects = new Set(), fibers = new Set();
  function inspect(object, depth = 0) {
    if (!object || typeof object !== 'object' || objects.has(object) || depth > 4) return;
    objects.add(object);
    if (typeof object.getQueryCache === 'function' && typeof object.cancelQueries === 'function') clients.add(object);
    if (object instanceof Map) for (const value of object.values()) inspect(value, depth + 1);
    for (const key of ['client', 'queryClient', 'value', 'memoizedValue', 'memoizedState', 'scope']) {
      const descriptor = Object.getOwnPropertyDescriptor(object, key);
      if (descriptor && 'value' in descriptor) inspect(descriptor.value, depth + 1);
    }
  }
  const stack = [fiberRoot];
  while (stack.length && fibers.size < 30000) {
    const fiber = stack.pop();
    if (!fiber || fibers.has(fiber)) continue;
    fibers.add(fiber);
    inspect(fiber.memoizedProps);
    let hook = fiber.memoizedState;
    for (let i = 0; hook && i < 100; i++, hook = hook.next) inspect(hook);
    let context = fiber.dependencies?.firstContext;
    for (let i = 0; context && i < 100; i++, context = context.next) inspect(context.memoizedValue);
    if (fiber.child) stack.push(fiber.child);
    if (fiber.sibling) stack.push(fiber.sibling);
  }
  const featureKey = ['experimental-features', 'list', 'local'];
  const candidates = [...clients].filter(c => c.getQueryCache().find({queryKey: featureKey, exact: true}));
  if (candidates.length !== 1) throw new Error('対象の機能一覧を一意に特定できません。変更せず停止しました。');
  const client = candidates[0];
  const cache = client.getQueryCache();
  // Promise identity prevents cancelling a new request that started between observations.
  const tracking = window.__codexRecoveryTracking ||= {ids: new WeakMap(), next: 1};
  function identity(value) {
    if (!value || !['object', 'function'].includes(typeof value)) return null;
    if (!tracking.ids.has(value)) tracking.ids.set(value, tracking.next++);
    return tracking.ids.get(value);
  }
  function kind(key) {
    if (JSON.stringify(key) === JSON.stringify(featureKey)) return 'features';
    if (key[0] === 'config' && key[1] === 'read-response' && key[2] === 'local' && key.length === 5) return 'config-read';
    if (key[0] === 'config' && key[1] === 'requirements' && key[2] === 'local' && key[3] === 'auth') return 'prepare';
    if (JSON.stringify(key) === JSON.stringify(['collaboration-modes', 'list', 'local'])) return 'prepare';
    if (JSON.stringify(key) === JSON.stringify(['windows-sandbox', 'readiness', 'local'])) return 'prepare';
    if (key.length === 2 && key[0] === 'vscode' && ['codex-command-keymap-state', 'chronicle-permissions'].includes(key[1])) return 'prepare';
    return null;
  }
  function queryState(query) {
    return {key: query.queryKey, kind: kind(query.queryKey), status: query.state.status,
      fetch: query.state.fetchStatus, updated: query.state.dataUpdatedAt,
      queryId: identity(query), promiseId: identity(query.promise), observers: query.getObserversCount()};
  }
  function snapshot() {
    const featureQuery = cache.find({queryKey: featureKey, exact: true});
    const userConfig = cache.find({queryKey: ['config', 'user', 'local'], exact: true});
    const visibleControls = [...rootElement.querySelectorAll('button,a,textarea,[contenteditable="true"]')]
      .filter(el => el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden').length;
    return {textLength: document.body.innerText.trim().length, visibleControls,
      blank: document.body.innerText.trim().length < 20 && visibleControls === 0,
      settingsRead: userConfig?.state.data?.readSucceeded ?? null,
      settingsFetching: userConfig?.state.fetchStatus === 'fetching',
      features: {status: featureQuery.state.status, fetch: featureQuery.state.fetchStatus,
        browser: featureQuery.state.data?.find?.(f => f.name === 'in_app_browser')?.enabled ?? null,
        automation: featureQuery.state.data?.find?.(f => f.name === 'in_app_local_automation')?.enabled ?? null},
      queries: cache.getAll().filter(q => kind(q.queryKey)).map(queryState)};
  }
  if (request.action === 'snapshot') return snapshot();
  if (request.action !== 'repair') throw new Error('未対応の操作です。');
  const query = cache.find({queryKey: request.key, exact: true});
  if (!query || !kind(query.queryKey)) throw new Error('復旧対象外のクエリです。');
  const before = queryState(query);
  if (before.queryId !== request.queryId || before.promiseId !== request.promiseId ||
      before.status !== 'pending' || before.fetch !== 'fetching' || before.updated !== 0) {
    return {action: 'skipped', reason: 'state_changed', before};
  }
  if (before.kind !== 'features' && !snapshot().blank) return {action: 'skipped', reason: 'screen_visible', before};
  const filter = {queryKey: query.queryKey, exact: true};
  function deadline(promise) {
    let timer;
    return Promise.race([promise, new Promise((_, reject) => {timer = setTimeout(() => reject(new Error('timeout')), 12000);})])
      .finally(() => clearTimeout(timer));
  }
  await deadline(client.cancelQueries(filter));
  // In the successful black-screen recovery, cancelling the internal config reads
  // released the parent wait. Refetch with no observers did not restart those reads.
  if (before.kind !== 'config-read') {
    try { await deadline(client.refetchQueries({...filter, type: 'all'})); }
    catch (error) { return {action: 'refetch_incomplete', reason: String(error), before, after: queryState(query)}; }
  }
  return {action: before.kind === 'config-read' ? 'cancelled' : 'cancelled_refetched', before, after: queryState(query)};
})
