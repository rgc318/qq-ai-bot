const bridge = window.AstrBotPluginView || window.AstrBotPluginPage;
const notice = document.querySelector('#notice');
let switching = false;
function message(text, error = false) { notice.textContent = text; notice.classList.toggle('error', error); }
async function refresh() {
  const response = await bridge.apiGet('context_backend/status');
  if (response.status !== 'ok') throw new Error(response.message || '读取状态失败');
  const state = response.data;
  for (const choice of state.choices) {
    const active = choice.value === state.backend;
    document.querySelector(`#card-${choice.value}`).classList.toggle('active', active);
    document.querySelector(`#state-${choice.value}`).textContent = active ? '当前正在使用' : choice.reason || '已就绪';
    document.querySelector(`[data-mode="${choice.value}"]`).disabled = switching || active || !choice.available || state.failed;
  }
  document.querySelector('#active').textContent = state.active_requests;
  document.querySelector('#samples').textContent = state.metrics.window_samples;
  document.querySelector('#latency').textContent = state.metrics.p95_ms === null ? '样本不足' : `${state.metrics.p95_ms.toFixed(2)} ms`;
  return state;
}
for (const button of document.querySelectorAll('[data-mode]')) {
  button.addEventListener('click', async () => {
    if (switching) return;
    switching = true;
    document.querySelectorAll('[data-mode]').forEach(item => item.disabled = true);
    message('正在检查空闲状态并切换…');
    try {
      const response = await bridge.apiPost('context_backend/switch', {mode: button.dataset.mode});
      if (response.status !== 'ok') throw new Error(response.message || '切换未完成');
      message('已切换，下一条消息使用新后端。');
    } catch (error) { message(error.message || String(error), true); }
    finally { switching = false; await refresh().catch(error => message(error.message, true)); }
  });
}
document.querySelector('#refresh').addEventListener('click', () => refresh().then(() => message('状态已更新。')).catch(error => message(error.message, true)));
try { await bridge.ready(); await refresh(); message('已连接，切换操作不会调用 AI 模型。'); }
catch (error) { message(error.message || '无法连接 AstrBot 插件页面接口', true); }
