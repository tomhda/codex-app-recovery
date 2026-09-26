const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(__dirname + '/../engine.js', 'utf8');

function fixture(blank=true) {
  const calls = [];
  function query(key, state={}) {
    return {queryKey:key, promise:Promise.resolve(), getObserversCount:()=>1,
      state:{status:'pending',fetchStatus:'fetching',dataUpdatedAt:0,...state}};
  }
  const feature=query(['experimental-features','list','local']);
  const config=query(['config','read-response','local',null,true]);
  const prepare=query(['vscode','codex-command-keymap-state']);
  const unrelated=query(['business','budget','change']);
  const qs=[feature,config,prepare,unrelated];
  const cache={getAll:()=>qs,find:({queryKey})=>qs.find(q=>JSON.stringify(q.queryKey)===JSON.stringify(queryKey))};
  const client={getQueryCache:()=>cache,
    cancelQueries:async filter=>{assert.equal(filter.exact,true);calls.push(['cancel',filter.queryKey]);cache.find(filter).state.fetchStatus='idle';},
    refetchQueries:async filter=>{assert.equal(filter.exact,true);calls.push(['refetch',filter.queryKey]);Object.assign(cache.find(filter).state,{status:'success',fetchStatus:'idle',dataUpdatedAt:1});}};
  const body={innerText:blank?'':'Normal application screen with buttons'};
  const element={__reactContainer$test:{stateNode:{current:{memoizedProps:{client}}}},querySelectorAll:()=>[]};
  const window={};
  const run=vm.runInNewContext(source,{document:{getElementById:()=>element,body},window,Map,Set,WeakMap,Promise,setTimeout,clearTimeout,getComputedStyle:()=>({visibility:'visible'})});
  return {run,calls,feature,config,prepare,unrelated,body,qs};
}

async function repair(f,q) {
  const state=await f.run({action:'snapshot'});
  const current=state.queries.find(x=>JSON.stringify(x.key)===JSON.stringify(q.queryKey));
  return f.run({action:'repair',...current});
}

assert.match(source, /data-composer-layout/);
assert.match(source, /contextState/);
assert.match(source, /engine_not_ready/);
assert.match(source, /invalidateQueries/);

(async()=>{
  let f=fixture();
  await f.run({action:'snapshot'});
  assert.equal(f.calls.length,0,'snapshot must be read-only');
  await repair(f,f.feature);
  assert.deepEqual(f.calls.map(x=>x[0]),['cancel','refetch']);
  assert.equal(f.feature.state.status,'success');
  f=fixture();
  const configResult = await repair(f,f.config);
  assert.equal(configResult.action,'cancelled','black-screen config read remains in the recovery allowlist');
  assert.deepEqual(f.calls.map(x=>x[0]),['cancel']);
  f=fixture(false);
  assert.equal((await repair(f,f.config)).reason,'ineligible');
  assert.equal(f.calls.length,0);
  f=fixture();
  const before=(await f.run({action:'snapshot'})).queries[0];
  f.feature.promise=Promise.resolve('new-request');
  assert.equal((await f.run({action:'repair',...before})).reason,'state_changed');
  assert.equal(f.calls.length,0);
  f=fixture();
  f.feature.state.fetchStatus='idle';
  assert.equal((await repair(f,f.feature)).reason,'state_changed');
  assert.equal(f.calls.length,0,'pending/idle is not a hung request');
  f=fixture();
  await assert.rejects(f.run({action:'repair',key:f.unrelated.queryKey}),/復旧対象外/);
  assert.equal(f.calls.length,0);
  f=fixture();
  const prepareResult = await repair(f,f.prepare);
  assert.equal(prepareResult.action,'cancelled_refetched');
  assert.deepEqual(f.calls.map(x=>x[0]),['cancel','refetch']);
  assert.equal(f.unrelated.state.status,'pending');
  console.log('PASS: 8 recovery selection and mutation-boundary scenarios');
})().catch(e=>{console.error(e);process.exitCode=1;});
