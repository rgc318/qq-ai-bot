// Logic-only test of the official plugin page bridge. No browser or network.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../extensions/astrbot_plugin_qq_persona_models/pages/上下文后端/app.js'), 'utf8');
function element(mode) {
  return {dataset: {mode}, textContent: '', disabled: false, classes: new Set(), handlers: {},
    classList: {toggle(name, value) { value ? this.owner.classes.add(name) : this.owner.classes.delete(name); }},
    addEventListener(name, callback) { this.handlers[name] = callback; }};
}
(async () => {
  const elements = new Map();
  for (const key of ['#notice','#active','#samples','#latency','#refresh','#card-builtin','#card-contextaware','#state-builtin','#state-contextaware']) elements.set(key, element());
  const buttons = ['builtin','contextaware'].map(mode => element(mode));
  for (const e of [...elements.values(), ...buttons]) e.classList.owner = e;
  let mode = 'builtin', reject = false, calls = 0;
  const state = () => ({backend: mode, active_requests: 0, failed: false,
    choices: ['builtin','contextaware'].map(value => ({value, available: true, reason: ''})),
    metrics: {window_samples: 0, p95_ms: null}});
  const bridge = {ready: async () => {}, apiGet: async name => {assert.equal(name, 'context_backend/status'); return {status:'ok', data:state()};},
    apiPost: async (name, body) => {calls++; assert.equal(name,'context_backend/switch'); if(reject) throw new Error('仍有排队消息'); mode=body.mode; return {status:'ok',data:state()};}};
  const document = {querySelector(selector) {if(selector.startsWith('[data-mode=')) return buttons.find(b => selector.includes(b.dataset.mode)); return elements.get(selector);}, querySelectorAll: () => buttons};
  await vm.runInNewContext('(async()=>{'+source+'})()', {window:{AstrBotPluginView:bridge},document});
  assert(buttons[0].disabled && !buttons[1].disabled);
  assert.equal(elements.get('#latency').textContent, '样本不足');
  await buttons[1].handlers.click();
  assert.equal(mode, 'contextaware'); assert.equal(calls,1); assert(buttons[1].disabled && !buttons[0].disabled);
  reject=true; await buttons[0].handlers.click();
  assert.equal(mode,'contextaware'); assert(elements.get('#notice').textContent.includes('排队消息')); assert(!buttons[0].disabled);
  console.log('Plugin page bridge: initial status, switch, busy rejection and controls restored passed');
})().catch(error => {console.error(error); process.exitCode=1;});
