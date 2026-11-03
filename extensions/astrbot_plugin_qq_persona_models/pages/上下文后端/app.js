const notice = document.querySelector('#notice');
const buttons = [...document.querySelectorAll('[data-mode]')];
let switching = false, connected = false, retryTimer = null, retryDelay = 2000;
let disposed = false, revision = 0;
function message(text, error = false) { notice.textContent = text; notice.classList.toggle('error', error); }
function bridge() {
  const api = window.AstrBotPluginView || window.AstrBotPluginPage;
  if (!api || typeof api.apiGet !== 'function') throw new Error('页面桥接未就绪，请从 AstrBot 插件菜单重新打开本页。');
  return api;
}
function timed(request) {
  let timer;
  return Promise.race([request, new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error('后台响应超时')), 10000);
  })]).finally(() => clearTimeout(timer));
}
function unwrap(response) {
  // Current AstrBot views already unwrap `data`; older hosts return an envelope.
  if (response?.status === 'error') throw new Error(response.message || '后台请求失败');
  return response?.status === 'ok' && response.data != null ? response.data : response;
}
function validate(state) {
  if (!state || !['builtin', 'contextaware'].includes(state.backend) || !Array.isArray(state.choices) || !state.metrics) {
    throw new Error('后台状态格式不兼容，请刷新 AstrBot 页面。');
  }
  return state;
}
function render(state) {
  for (const choice of state.choices) {
    if (!['builtin', 'contextaware'].includes(choice.value)) continue;
    const active = choice.value === state.backend;
    document.querySelector(`#card-${choice.value}`).classList.toggle('active', active && !state.startup_pending);
    document.querySelector(`#state-${choice.value}`).textContent = state.startup_pending && choice.value === state.requested_backend
      ? state.startup_issue || '正在恢复已保存的选择'
      : active ? state.startup_pending ? '可明确选择本地后端' : '当前正在使用' : choice.reason || '已就绪';
    document.querySelector(`[data-mode="${choice.value}"]`).disabled = !connected || switching || state.switching || (active && !state.startup_pending) || !choice.available || state.failed;
  }
  document.querySelector('#active').textContent = state.active_requests;
  document.querySelector('#samples').textContent = state.metrics.window_samples;
  document.querySelector('#latency').textContent = Number.isFinite(state.metrics.p95_ms) ? `${state.metrics.p95_ms.toFixed(2)} ms` : '样本不足';
}
function clearRetry() { if (retryTimer !== null) clearTimeout(retryTimer); retryTimer = null; }
function failed(error) {
  if (disposed) return;
  connected = false;
  buttons.forEach(button => button.disabled = true);
  message(`${error.message || String(error)}。将在 ${retryDelay / 1000} 秒后重试读取状态。`, true);
  clearRetry();
  retryTimer = setTimeout(() => { retryTimer = null; return connect(); }, retryDelay);
  retryDelay = Math.min(retryDelay * 2, 30000);
}
async function refresh(successMessage = '状态已更新。') {
  const requestRevision = ++revision;
  let state;
  try { state = validate(unwrap(await timed(bridge().apiGet('context_backend/status')))); }
  catch (error) { if (disposed || requestRevision !== revision) return; throw error; }
  if (disposed || requestRevision !== revision) return;
  connected = true; retryDelay = 2000; clearRetry(); render(state);
  if (state.startup_pending) {
    message(state.startup_issue || '正在等待依赖模块，准备恢复已保存的后端。', true);
    retryTimer = setTimeout(() => { retryTimer = null; return connect(); }, 2000);
  }
  else if (state.failed) message('后端切换回滚失败，请查看插件日志并重载插件。', true);
  else message(successMessage);
  return state;
}
async function connect() {
  try {
    await timed(bridge().ready());
    if (switching || disposed) return;
    await refresh('已连接，切换操作不会调用 AI 模型。');
  } catch (error) { failed(error); }
}
for (const button of buttons) {
  button.addEventListener('click', async () => {
    if (switching || !connected) return;
    switching = true; ++revision; clearRetry();
    buttons.forEach(item => item.disabled = true);
    message('正在检查空闲状态并切换…');
    let switchError = null;
    try { unwrap(await timed(bridge().apiPost('context_backend/switch', {mode: button.dataset.mode}))); }
    catch (error) { switchError = error; }
    finally {
      switching = false;
      try {
        await refresh('已切换，下一条消息使用新后端。');
        if (switchError) message(`${switchError.message || String(switchError)}。已重新读取当前状态；未自动重复提交切换。`, true);
      } catch (error) { failed(error); }
    }
  });
}
document.querySelector('#refresh').addEventListener('click', async () => {
  if (switching) return;
  clearRetry();
  await connect();
});
window.addEventListener('pagehide', () => { disposed = true; ++revision; clearRetry(); });
await connect();
