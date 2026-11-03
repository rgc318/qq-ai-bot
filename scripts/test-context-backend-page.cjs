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
async function harness({envelope = false, initialFailure = false, pending = false} = {}) {
  const elements = new Map();
  for (const key of ['#notice','#active','#samples','#latency','#refresh','#card-builtin','#card-contextaware','#state-builtin','#state-contextaware']) elements.set(key, element());
  const buttons = ['builtin','contextaware'].map(mode => element(mode));
  for (const e of [...elements.values(), ...buttons]) e.classList.owner = e;
  const timers = new Map(), events = {};
  let timerId = 0;
  const control = {mode: 'builtin', reject: false, calls: 0, getCalls: 0, failGet: initialFailure, pending, hangPost: false, malformed: false};
  const state = () => ({backend: control.mode, active_requests: 0, failed: false,
    startup_pending: control.pending, requested_backend: control.pending ? 'contextaware' : control.mode,
    startup_issue: control.pending ? '等待原生模块加载' : '',
    choices: ['builtin','contextaware'].map(value => ({value, available: true, reason: ''})),
    metrics: {window_samples: 0, p95_ms: null}});
  const wrap = value => envelope ? {status:'ok', data:value} : value;
  const bridge = {ready: async () => {}, apiGet: async name => {
    assert.equal(name, 'context_backend/status'); control.getCalls++;
    if (control.failGet) throw new Error('网络暂不可用');
    return control.malformed ? {unexpected:true} : wrap(state());
  }, apiPost: async (name, body) => {
    control.calls++; assert.equal(name,'context_backend/switch');
    if(control.reject) throw new Error('仍有排队消息');
    control.mode=body.mode; control.pending=false;
    if (control.hangPost) return new Promise(() => {});
    return wrap(state());
  }};
  const document = {querySelector(selector) {if(selector.startsWith('[data-mode=')) return buttons.find(b => selector.includes(b.dataset.mode)); return elements.get(selector);}, querySelectorAll: () => buttons};
  await vm.runInNewContext('(async()=>{'+source+'})()', {
    window:{AstrBotPluginView:bridge,addEventListener:(key,fn)=>events[key]=fn}, document,
    setTimeout:(fn,ms)=>{const id=++timerId;timers.set(id,{fn,ms});return id;}, clearTimeout:id=>timers.delete(id)
  });
  return {elements,buttons,control,timers,events,bridge,
    fire:async ms=>{const entry=[...timers.entries()].find(([,v])=>v.ms===ms);assert(entry,'Expected scheduled timer '+ms);timers.delete(entry[0]);return entry[1].fn();}};
}
(async () => {
  for (const envelope of [false,true]) {
    const h=await harness({envelope});
    assert(h.buttons[0].disabled && !h.buttons[1].disabled);
    assert.equal(h.elements.get('#latency').textContent, '样本不足');
    await h.buttons[1].handlers.click();
    assert.equal(h.control.mode, 'contextaware'); assert.equal(h.control.calls,1);
    assert(h.buttons[1].disabled && !h.buttons[0].disabled);
    h.control.reject=true; await h.buttons[0].handlers.click();
    assert.equal(h.control.mode,'contextaware');
    assert(h.elements.get('#notice').textContent.includes('排队消息')); assert(!h.buttons[0].disabled);
    assert.equal(h.timers.size,0,'No polling or retries after a successful status read');
  }
  const retry=await harness({initialFailure:true});
  assert(retry.buttons.every(b=>b.disabled));assert(retry.elements.get('#notice').textContent.includes('2 秒'));
  await retry.fire(2000);
  assert(retry.elements.get('#notice').textContent.includes('4 秒'));
  retry.control.failGet=false;await retry.fire(4000);
  assert(!retry.buttons[1].disabled);assert.equal(retry.timers.size,0);assert.equal(retry.control.calls,0);
  const recovering=await harness({pending:true});
  assert(!recovering.buttons[0].disabled,'Explicit local choice remains available during deferred startup');
  assert(recovering.elements.get('#notice').textContent.includes('等待原生模块'));
  await recovering.buttons[0].handlers.click();
  assert(!recovering.control.pending);assert.equal(recovering.control.calls,1);assert.equal(recovering.timers.size,0);
  const timeout=await harness();timeout.control.hangPost=true;
  const clicked=timeout.buttons[1].handlers.click();
  await timeout.fire(10000);await clicked;
  assert.equal(timeout.control.mode,'contextaware');assert.equal(timeout.control.calls,1,'Never retry an ambiguous mutation');
  assert(timeout.elements.get('#notice').textContent.includes('未自动重复提交'));assert(timeout.buttons[1].disabled);
  const bad=await harness();bad.control.malformed=true;await bad.elements.get('#refresh').handlers.click();
  assert(bad.elements.get('#notice').textContent.includes('格式不兼容'));assert(bad.buttons.every(b=>b.disabled));
  bad.events.pagehide();assert.equal(bad.timers.size,0,'Leaving the page cancels retry timers');
  const stale=await harness();let failOld,markStarted;
  const started=new Promise(resolve=>markStarted=resolve);
  stale.bridge.apiGet=()=>new Promise((_,reject)=>{failOld=reject;markStarted();});
  const previous=stale.elements.get('#refresh').handlers.click();
  await started;
  stale.bridge.apiGet=async()=>({backend:'contextaware',active_requests:0,failed:false,choices:[{value:'builtin',available:true},{value:'contextaware',available:true}],metrics:{window_samples:0,p95_ms:null}});
  await stale.elements.get('#refresh').handlers.click();failOld(new Error('old request failed'));await previous;
  assert(stale.buttons[1].disabled && !stale.buttons[0].disabled,'Stale failures cannot overwrite a newer successful read');
  assert.equal(stale.timers.size,0);
  console.log('Page regressions passed: raw/enveloped bridge, switch, busy rejection, bounded reconnect, deferred startup, mutation timeout, invalid response, teardown and stale failure.');
})().catch(error => {console.error(error); process.exitCode=1;});
