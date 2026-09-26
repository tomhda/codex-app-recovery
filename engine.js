(async function recoveryEngine(request) {
  const rootElement = document.getElementById('root');
  if (!rootElement) { const error = new Error('Codex の画面を確認できません。'); error.code = 'engine_not_ready'; throw error; }
  const containerKey = Object.keys(rootElement).find(k => k.startsWith('__reactContainer$'));
  const fiberRoot = window.__codexRoot?._internalRoot?.current ||
    rootElement[containerKey]?.stateNode?.current || rootElement[containerKey]?.current || rootElement[containerKey];
  if (!fiberRoot) { const error = new Error('このバージョンの画面構造には対応していません。'); error.code = 'engine_not_ready'; throw error; }
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
  function visible(element) { return !!element && !!element.getClientRects().length && getComputedStyle(element).visibility !== 'hidden'; }
  function elementsInScope(scope, selector) { return [...scope.querySelectorAll(selector)].filter(visible); }
  function composerScopes() {
    const inputs = [...rootElement.querySelectorAll('textarea,[contenteditable="true"]')].filter(visible), scopes = [];
    for (const input of inputs) {
      let node = input.parentElement, found = null;
      for (let depth = 0; node && depth < 10; depth++, node = node.parentElement) {
        if (node.matches?.('[data-composer], [data-composer-layout], [data-testid*="composer" i], [data-composer-navigation-target]') || node.querySelector?.('[data-composer], [data-composer-layout], [data-testid*="composer" i]')) { found = node; break; }
      }
      if (found && !scopes.includes(found)) scopes.push(found);
    }
    return {inputs, scopes};
  }
  function composerFiber(scope) { const key = Object.keys(scope).find(k => k.startsWith('__reactFiber$')); return key ? scope[key] : null; }
  function fiberProps(scope) {
    const startFiber = composerFiber(scope), result = [], seen = new Set(), stack = startFiber ? [startFiber] : [];
    while (stack.length && seen.size < 1000) {
      const fiber = stack.pop(); if (!fiber || seen.has(fiber)) continue; seen.add(fiber);
      if (fiber.memoizedProps) result.push(fiber.memoizedProps);
      if (fiber.child) {
        stack.push(fiber.child);
        let sibling = fiber.child.sibling;
        while (sibling) { stack.push(sibling); sibling = sibling.sibling; }
      }
    }
    return result;
  }
  function ancestorProps(scope) {
    let fiber = composerFiber(scope)?.return, result = [];
    for (let i = 0; fiber && i < 30; i++, fiber = fiber.return) if (fiber.memoizedProps) result.push(fiber.memoizedProps);
    return result;
  }
  function validContext(value) {
    return value && typeof value === 'object' && Number.isFinite(value.percent) && Number.isFinite(value.usedTokens) && Number.isFinite(value.contextWindow) && value.percent >= 0 && value.percent <= 100 && value.usedTokens >= 0 && value.contextWindow > 0;
  }
  function scopeInfo(scope) {
    const props = fiberProps(scope), ancestors = ancestorProps(scope), allProps = props.concat(ancestors), local = allProps.filter(p => p.composerMode === 'local' && p.permissionsHostId === 'local' && p.executionTargetHostId === 'local' && typeof p.permissionsCwdOverride === 'string' && p.permissionsCwdOverride.length > 0);
    const remote = allProps.some(p => p.composerMode && p.composerMode !== 'local' || p.permissionsHostId && p.permissionsHostId !== 'local' || p.executionTargetHostId && p.executionTargetHostId !== 'local');
    const cwds = [...new Set(local.map(p => p.permissionsCwdOverride))];
    const conversationId = allProps.find(p => Object.prototype.hasOwnProperty.call(p, 'conversationId'))?.conversationId;
    return {known: !remote && cwds.length === 1, cwd: cwds.length === 1 ? cwds[0] : null, conversationId,
      contextValues: allProps.map(p => p.contextUsage).filter(validContext)};
  }
  function uiHealth() {
    const {inputs, scopes} = composerScopes();
    if (scopes.length !== 1) return {chat: false, modelPicker: null, effortPicker: null, contextUsage: null, contextState: 'unknown', degraded: false, scopeKnown: false, cwd: null};
    const scoped = scopes.map(scope => ({scope, info: scopeInfo(scope)})).filter(x => x.info.known);
    if (scoped.length !== 1) return {chat: false, modelPicker: null, effortPicker: null, contextUsage: null, contextState: 'unknown', degraded: false, scopeKnown: false, cwd: null};
    if (!inputs.length || !scoped.length) return {chat: false, modelPicker: null, effortPicker: null, contextUsage: null, contextState: 'unknown', degraded: false, scopeKnown: false, cwd: null};
    const modelPicker = scoped.some(({scope}) => elementsInScope(scope, '[data-codex-intelligence-trigger]').length > 0);
    const effortPicker = scoped.some(({scope}) => elementsInScope(scope, '[data-composer-navigation-target="reasoning"][data-selected-reasoning-effort]').length > 0);
    let contextState = 'unknown', contextUsage = false;
    for (const {scope, info} of scoped) {
      if (info.conversationId === null) { contextState = 'no_data'; continue; }
      const contextNodes = [...scope.querySelectorAll('[aria-label]')];
      let observed = false;
      for (const element of contextNodes) {
        const key = Object.keys(element).find(k => k.startsWith('__reactFiber$')); let fiber = key ? element[key] : null;
        for (let i = 0; fiber && i < 30; i++, fiber = fiber.return) {
          if (validContext(fiber.memoizedProps?.contextUsage)) { observed = true; if (!visible(element)) contextState = 'hidden'; else { contextState = 'visible'; contextUsage = true; } break; }
        }
      }
      if (!observed && info.contextValues.length) contextState = 'hidden';
    }
    const contextDegraded = contextState === 'hidden';
    return {chat: true, modelPicker, effortPicker, contextUsage, contextState,
      degraded: !modelPicker || !effortPicker || contextDegraded, scopeKnown: true, cwd: scoped[0].info.cwd};
  }
  const candidates = [...clients].filter(c => c.getQueryCache().find({queryKey: featureKey, exact: true}));
  if (candidates.length === 0) { const error = new Error('対象の機能一覧を準備中です。'); error.code = 'engine_not_ready'; throw error; }
  if (candidates.length !== 1) { const error = new Error('対象の機能一覧を一意に特定できません。変更せず停止しました。'); error.code = 'ambiguous_client'; throw error; }
  const client = candidates[0], cache = client.getQueryCache();
  const tracking = window.__codexRecoveryTracking ||= {ids: new WeakMap(), next: 1};
  function identity(value) { if (!value || !['object', 'function'].includes(typeof value)) return null; if (!tracking.ids.has(value)) tracking.ids.set(value, tracking.next++); return tracking.ids.get(value); }
  function localConfig(key) {
    if (!Array.isArray(key) || key[0] !== 'config' || key[2] !== 'local') return null;
    if (key[1] === 'user' && key.length === 3) return {role: 'config-parent', cwd: null};
    if (['effective', 'layered-response'].includes(key[1]) && key.length === 4) return {role: 'config-parent', cwd: key[3]};
    if (key[1] === 'read-response' && key.length === 5 && typeof key[4] === 'boolean') return {role: 'config-read', cwd: key[3]};
    return null;
  }
  function kind(key) {
    if (JSON.stringify(key) === JSON.stringify(featureKey)) return 'features';
    const config = localConfig(key); if (config) return config.role;
    if (key[0] === 'models' && key[1] === 'list' && key[2] === 'local' && key.length >= 5) return 'models';
    if (key[0] === 'config' && key[1] === 'requirements' && key[2] === 'local' && key[3] === 'auth') return 'prepare';
    if (JSON.stringify(key) === JSON.stringify(['collaboration-modes', 'list', 'local'])) return 'prepare';
    if (JSON.stringify(key) === JSON.stringify(['windows-sandbox', 'readiness', 'local'])) return 'prepare';
    if (key.length === 2 && key[0] === 'vscode' && ['codex-command-keymap-state', 'chronicle-permissions'].includes(key[1])) return 'prepare';
    return null;
  }
  function isStalled(query) { return query.state.status === 'pending' && query.state.fetchStatus === 'fetching' && query.state.dataUpdatedAt === 0; }
  function queryEligible(query, ui) {
    const k = kind(query.queryKey); if (k === 'features') return true;
    if (!isStalled(query)) return false;
    if (ui.blank && ['config-read', 'prepare'].includes(k)) return true;
    if (k === 'prepare' || !ui.scopeKnown || !ui.degraded) return false;
    if (k === 'models') return query.getObserversCount() > 0;
    const info = localConfig(query.queryKey); if (!info || (ui.cwd && info.cwd !== ui.cwd)) return false;
    if (info.role === 'config-parent') return query.getObserversCount() > 0;
    return cache.getAll().some(parent => { const pi = localConfig(parent.queryKey); return pi?.role === 'config-parent' && pi.cwd === info.cwd && parent.getObserversCount() > 0; });
  }
  function queryState(query, ui = uiHealth()) { return {key: query.queryKey, kind: kind(query.queryKey), status: query.state.status, fetch: query.state.fetchStatus, updated: query.state.dataUpdatedAt, queryId: identity(query), promiseId: identity(query.promise), observers: query.getObserversCount(), eligible: queryEligible(query, ui)}; }
  function snapshot() {
    const featureQuery = cache.find({queryKey: featureKey, exact: true}), userConfig = cache.find({queryKey: ['config', 'user', 'local'], exact: true}), ui = uiHealth();
    const visibleControls = [...rootElement.querySelectorAll('button,a,textarea,[contenteditable="true"]')].filter(visible).length;
    const blank = document.body.innerText.trim().length < 20 && visibleControls === 0;
    // A visible spinner without any editor is distinct from a blank renderer.
    // Never reload a hidden editor/draft, or a spinner inside an existing chat.
    ui.startupSpinner = blank && document.body.innerText.trim().length === 0 &&
      rootElement.querySelectorAll('textarea,input,[contenteditable="true"],[role="textbox"]').length === 0 &&
      [...rootElement.querySelectorAll('[class*="animate-spin"],[role="progressbar"]')].some(visible);
    tracking.documentToken ||= `${Date.now()}-${Math.random()}`;
    ui.documentId = `${tracking.documentToken}:${identity(rootElement)}`;
    const eligibilityUi = {...ui, blank};
    return {textLength: document.body.innerText.trim().length, visibleControls, ui, blank, settingsRead: userConfig?.state.data?.readSucceeded ?? null, settingsFetching: userConfig?.state.fetchStatus === 'fetching', features: featureQuery ? {status: featureQuery.state.status, fetch: featureQuery.state.fetchStatus, browser: featureQuery.state.data?.find?.(f => f.name === 'in_app_browser')?.enabled ?? null, automation: featureQuery.state.data?.find?.(f => f.name === 'in_app_local_automation')?.enabled ?? null} : {status: 'missing', fetch: 'idle', browser: null, automation: null}, queries: cache.getAll().filter(q => kind(q.queryKey)).map(q => queryState(q, eligibilityUi))};
  }
  if (request.action === 'snapshot') return snapshot();
  if (request.action !== 'repair') throw new Error('未対応の操作です。');
  const query = cache.find({queryKey: request.key, exact: true});
  if (!query || !kind(query.queryKey)) throw new Error('復旧対象外のクエリです。');
  const initial = snapshot();
  const before = queryState(query, {...initial.ui, blank: initial.blank});
  if (before.queryId !== request.queryId || before.promiseId !== request.promiseId || before.status !== 'pending' || before.fetch !== 'fetching' || before.updated !== 0 || !before.eligible) return {action: 'skipped', reason: before.eligible ? 'state_changed' : 'ineligible', before};
  const current = initial;
  if (before.kind !== 'features' && !current.blank && !current.ui.degraded) return {action: 'skipped', reason: 'screen_visible', before};
  function deadline(promise) { let timer; return Promise.race([promise, new Promise((_, reject) => {timer = setTimeout(() => reject(new Error('timeout')), 12000);})]).finally(() => clearTimeout(timer)); }
  const filter = {queryKey: query.queryKey, exact: true}; await deadline(client.cancelQueries(filter));
  if (before.kind === 'config-read') {
    const info = localConfig(query.queryKey);
    const layered = cache.getAll().find(candidate => { const pi = localConfig(candidate.queryKey); return pi?.role === 'config-parent' && candidate.queryKey[1] === 'layered-response' && pi.cwd === info.cwd; });
    const parent = cache.getAll().find(candidate => { const pi = localConfig(candidate.queryKey); return pi?.role === 'config-parent' && candidate.queryKey[1] === 'effective' && pi.cwd === info.cwd && candidate.getObserversCount() > 0; });
    if (layered && client.invalidateQueries) {
      try { await deadline(client.invalidateQueries({queryKey: layered.queryKey, exact: true, refetchType: 'none'})); }
      catch (error) { return {action: 'refetch_incomplete', reason: 'dependency_invalidate_failed', before, after: queryState(query, current.ui)}; }
    }
    if (parent && cache.getAll().includes(parent)) {
      try { await deadline(client.refetchQueries({queryKey: parent.queryKey, exact: true, type: 'all'})); }
      catch (error) { return {action: 'refetch_incomplete', reason: 'parent_refetch_failed', before, after: queryState(query, current.ui)}; }
    }
    const leafAfter = queryState(query, current.ui);
    if (parent && cache.getAll().includes(parent)) {
      const parentAfter = queryState(parent, current.ui);
      if (leafAfter.status !== 'success' || leafAfter.fetch !== 'idle' || leafAfter.updated === 0 || parentAfter.status !== 'success' || parentAfter.fetch !== 'idle' || parentAfter.updated === 0)
        return {action: 'refetch_incomplete', reason: 'dependency_not_successful', before, after: leafAfter};
      return {action: 'cancelled_refetched', before, after: leafAfter};
    }
    return {action: 'cancelled', before, after: leafAfter};
  }
  try { await deadline(client.refetchQueries({...filter, type: 'all'})); } catch (error) { return {action: 'refetch_incomplete', reason: 'refetch_failed', before, after: queryState(query, current.ui)}; }
  const after = queryState(query, current.ui); if (after.status !== 'success' || after.fetch !== 'idle' || after.updated === 0) return {action: 'refetch_incomplete', reason: 'query_not_successful', before, after};
  return {action: 'cancelled_refetched', before, after};

})
