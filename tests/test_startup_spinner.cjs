const assert = require('node:assert/strict');
const fs = require('node:fs');
const { JSDOM } = require('jsdom');
const { QueryClient } = require('@tanstack/query-core');
const source = fs.readFileSync(__dirname + '/../engine.js', 'utf8');

async function snapshot(html) {
  const dom = new JSDOM(`<div id="root">${html}</div>`, {runScripts: 'outside-only'});
  const w = dom.window;
  Object.defineProperty(w.HTMLElement.prototype, 'innerText', {get() {return this.textContent;}});
  w.HTMLElement.prototype.getClientRects = function() {return this.hidden ? [] : [{}];};
  const client = new QueryClient();
  client.setQueryData(['experimental-features', 'list', 'local'], []);
  client.setQueryData(['config', 'user', 'local'], {readSucceeded: true});
  w.document.getElementById('root').__reactContainer$test = {stateNode: {current: {memoizedProps: {client}}}};
  try {
    const engine = w.eval(`(${source})`);
    const first = await engine({action: 'snapshot'}), second = await engine({action: 'snapshot'});
    assert.equal(first.ui.documentId, second.ui.documentId);
    return first;
  } finally {client.clear();w.close();}
}
(async () => {
  const spinner = '<div class="motion-safe:animate-spin"><svg></svg></div>';
  assert.equal((await snapshot(spinner)).ui.startupSpinner, true);
  assert.equal((await snapshot('')).ui.startupSpinner, false);
  assert.equal((await snapshot('<div hidden class="animate-spin"></div>')).ui.startupSpinner, false);
  for (const content of ['<textarea hidden>draft</textarea>', '<input hidden>', '<div contenteditable="true" hidden></div>', '<button>Menu</button>', 'Loading']) {
    assert.equal((await snapshot(spinner + content)).ui.startupSpinner, false);
  }
  assert.notEqual((await snapshot(spinner)).ui.documentId, (await snapshot(spinner)).ui.documentId);
  console.log('PASS: startup spinner detection, hidden drafts, healthy controls, and document identity');
})().catch(error => {console.error(error);process.exitCode=1;});
