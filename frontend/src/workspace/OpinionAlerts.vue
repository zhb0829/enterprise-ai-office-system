<template>
  <main class="opinion-page" aria-labelledby="alerts-title">
    <header class="opinion-head">
      <div>
        <p class="eyebrow">风险预警闭环</p>
        <h2 id="alerts-title">舆情告警</h2>
        <p class="opinion-lead">查看告警事件、处置流转、AI 应对建议，以及文章传播路径（已验证/推测分开展示）。</p>
      </div>
      <div class="opinion-status" role="status" aria-live="polite">
        <span aria-hidden="true"></span>
        {{ loading ? '同步中' : '告警视图已就绪' }}
      </div>
    </header>

    <div class="monitor-bar">
      <select v-model="monitorId" aria-label="监控任务" @change="loadAll">
        <option :value="null" disabled>选择监控任务</option>
        <option v-for="monitor in monitors" :key="monitor.id" :value="monitor.id">{{ monitor.name }}</option>
      </select>
      <button type="button" class="primary-button" @click="loadAll">刷新</button>
    </div>

    <p v-if="error" class="feedback danger" role="alert">{{ error }}</p>

    <section class="panel">
      <div class="panel-title"><h3>告警事件</h3><span class="count">{{ alerts.length }} 条</span></div>
      <div v-if="!alerts.length" class="empty-cell">暂无告警，规则命中后自动生成。</div>
      <ul v-else class="alert-list">
        <li v-for="alert in alerts" :key="alert.id" class="alert-item">
          <div class="alert-head">
            <span :class="['risk-badge', riskClass(alert.riskLevel)]">{{ alert.riskLevel }}</span>
            <strong>告警 #{{ alert.id }}</strong>
            <span :class="['state-badge', stateClass(alert.state)]">{{ stateLabel(alert.state) }}</span>
            <small>触发 {{ alert.triggerCount }} 次 · {{ formatTime(alert.lastTriggeredAt) }}</small>
          </div>
          <p class="stats-line">{{ statsLabel(alert.triggerStats) }}</p>
          <div class="alert-actions">
            <button type="button" :disabled="handling === alert.id" @click="openHandle(alert)">处置</button>
            <button type="button" :disabled="suggesting === alert.id" @click="generateSuggestion(alert)">{{ suggesting === alert.id ? '生成中...' : '生成应对建议' }}</button>
            <button type="button" @click="toggleNotifications(alert)">通知记录</button>
          </div>
          <div v-if="handleAlertId === alert.id" class="handle-form">
            <select v-model="handleState">
              <option value="acknowledged">确认（acknowledged）</option>
              <option value="processing">处理中（processing）</option>
              <option value="resolved">已解决（resolved）</option>
              <option value="closed">已关闭（closed）</option>
            </select>
            <input v-model="handleNote" placeholder="处置说明（审计追溯）" />
            <button type="button" class="primary-button" :disabled="submitting" @click="submitHandle(alert)">提交</button>
          </div>
          <ul v-if="activeNotifications === alert.id" class="notification-list">
            <li v-for="notification in notifications[alert.id] || []" :key="notification.id">
              <span :class="['state-badge', notification.status === 'success' ? 'ok' : 'warn']">{{ notification.status }}</span>
              <span>{{ notification.channel }}</span>
              <small>{{ notification.content || notification.error }}</small>
            </li>
          </ul>
          <div v-if="visibleSuggestions(alert.id).length" class="suggestion-box">
            <div v-for="suggestion in visibleSuggestions(alert.id)" :key="suggestion.id" class="suggestion-item">
              <p>{{ suggestion.content }}</p>
              <small>模型 {{ suggestion.model || 'rule-based' }} · 状态 {{ suggestion.status }}</small>
              <div v-if="suggestion.status === 'pending'" class="feedback-actions">
                <button type="button" @click="feedbackSuggestion(suggestion, 'accepted')">采纳</button>
                <button type="button" @click="feedbackSuggestion(suggestion, 'rejected')">拒绝</button>
              </div>
            </div>
          </div>
        </li>
      </ul>
    </section>

    <section class="panel">
      <div class="panel-title">
        <h3>传播路径</h3>
        <div class="panel-actions">
          <select v-model="verifiedFilter" aria-label="传播关系类型" @change="loadSpread">
            <option value="">全部</option>
            <option value="true">已验证</option>
            <option value="false">推测</option>
          </select>
          <button type="button" class="ghost-button" :disabled="analyzing" @click="analyzeSpread">{{ analyzing ? '分析中...' : '分析传播路径' }}</button>
        </div>
      </div>
      <div v-if="!edges.length" class="empty-cell">暂无传播关系，点击「分析传播路径」基于相似度与时间推断。</div>
      <ul v-else class="edge-list">
        <li v-for="edge in edges" :key="edge.id" class="edge-item">
          <span :class="['state-badge', edge.verified ? 'ok' : 'warn']">{{ edge.verified ? '已验证' : '推测' }}</span>
          <span class="edge-type">{{ edge.relationType }}</span>
          <strong>#{{ edge.fromArticleId }} → #{{ edge.toArticleId }}</strong>
          <small>{{ edge.evidence }}</small>
        </li>
      </ul>
    </section>
  </main>
</template>

<script setup>
import { onMounted, ref } from 'vue';
import {
  analyzeOpinionSpread, feedbackOpinionSuggestion, fetchOpinionAlerts, fetchOpinionMonitors,
  fetchOpinionNotifications, fetchOpinionSpread, fetchOpinionSuggestions, generateOpinionSuggestion,
  handleOpinionAlert,
} from '../api';

const monitors = ref([]);
const monitorId = ref(null);
const alerts = ref([]);
const edges = ref([]);
const notifications = ref({});
const suggestions = ref({});
const verifiedFilter = ref('');
const handleAlertId = ref(null);
const activeNotifications = ref(null);
const handleState = ref('acknowledged');
const handleNote = ref('');
const loading = ref(false);
const handling = ref(null);
const submitting = ref(false);
const suggesting = ref(null);
const analyzing = ref(false);
const error = ref('');

const riskClass = (value) => ({ 危机: 'danger', 预警: 'warn', 关注: 'ok' }[value] || 'warn');
const stateClass = (value) => ({ resolved: 'ok', closed: 'ok', acknowledged: 'warn', processing: 'warn', triggered: 'danger' }[value] || 'warn');
const stateLabel = (value) => ({ triggered: '已触发', acknowledged: '已确认', processing: '处理中', resolved: '已解决', closed: '已关闭' }[value] || value);
const formatTime = (value) => {
  if (!value) return '-';
  const raw = String(value).trim();
  const hasTz = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw);
  const date = new Date(hasTz ? raw : `${raw.replace(' ', 'T')}Z`);
  return Number.isNaN(date.getTime()) ? raw : date.toLocaleString();
};
function statsLabel(stats) {
  if (!stats) return '';
  return `负面 ${stats.negativeCount ?? 0} / ${stats.totalCount ?? 0}，比例 ${stats.negativeRatio ?? 0}，来源 ${stats.sourceCount ?? 0}，增速 ${stats.growthRate ?? 0}`;
}
async function loadAll() {
  error.value = ''; loading.value = true;
  try {
    const [m, a, e] = await Promise.all([
      fetchOpinionMonitors(),
      monitorId.value ? fetchOpinionAlerts({ monitorId: monitorId.value }) : Promise.resolve([]),
      monitorId.value ? fetchOpinionSpread(monitorId.value, verifiedFilter.value === '' ? undefined : verifiedFilter.value === 'true') : Promise.resolve([]),
    ]);
    monitors.value = m; alerts.value = a; edges.value = e;
    if (!monitorId.value && m.length) { monitorId.value = m[0].id; await loadAll(); }
  } catch (e) {
    error.value = `加载失败：${e.message}`;
  } finally { loading.value = false; }
}
async function loadSpread() { edges.value = await fetchOpinionSpread(monitorId.value, verifiedFilter.value === '' ? undefined : verifiedFilter.value === 'true'); }
function openHandle(alert) { handleAlertId.value = handleAlertId.value === alert.id ? null : alert.id; handleState.value = alert.state === 'triggered' ? 'acknowledged' : alert.state; handleNote.value = alert.handleNote || ''; }
async function submitHandle(alert) {
  submitting.value = true;
  try {
    await handleOpinionAlert(alert.id, { state: handleState.value, note: handleNote.value });
    handleAlertId.value = null;
    await loadAll();
  } catch (e) { error.value = `处置失败：${e.message}`; } finally { submitting.value = false; }
}
async function toggleNotifications(alert) {
  activeNotifications.value = activeNotifications.value === alert.id ? null : alert.id;
  if (activeNotifications.value === alert.id) notifications.value = { ...notifications.value, [alert.id]: await fetchOpinionNotifications(alert.id) };
}
async function generateSuggestion(alert) {
  suggesting.value = alert.id;
  try {
    await generateOpinionSuggestion('alert', alert.id);
    suggestions.value = { ...suggestions.value, [alert.id]: await fetchOpinionSuggestions('alert', alert.id) };
  } catch (e) { error.value = `建议生成失败：${e.message}`; } finally { suggesting.value = null; }
}
function visibleSuggestions(alertId) {
  const items = suggestions.value[alertId] || [];
  const hasCaseBackedSuggestion = items.some((item) => item.citations?.length);
  if (!hasCaseBackedSuggestion) return items;
  return items.filter((item) => item.citations?.length || !item.content?.includes('暂未检索到足够相似'));
}
async function feedbackSuggestion(suggestion, status) {
  try {
    await feedbackOpinionSuggestion(suggestion.id, { status, feedback: status === 'rejected' ? '内容不适用' : '已采纳' });
    suggestions.value = { ...suggestions.value, [suggestion.targetId]: await fetchOpinionSuggestions('alert', suggestion.targetId) };
  } catch (e) { error.value = `反馈失败：${e.message}`; }
}
async function analyzeSpread() {
  analyzing.value = true;
  try {
    await analyzeOpinionSpread(monitorId.value);
    await loadSpread();
  } catch (e) { error.value = `传播分析失败：${e.message}`; } finally { analyzing.value = false; }
}
onMounted(loadAll);
</script>

<style scoped>
.opinion-page { max-width: 1200px; margin: 0 auto; padding: clamp(24px, 4vw, 48px) clamp(16px, 4vw, 40px) 72px; color: #17233a; }
.opinion-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 12px; padding: 10px 0 24px; border-bottom: 1px solid #d7e4df; }
.opinion-head h2 { margin: 0; color: #112927; font-size: clamp(2rem, 4vw, 3rem); line-height: 1.08; }
.opinion-lead { max-width: 720px; margin: 14px 0 0; color: #52615f; line-height: 1.75; }
.opinion-status { display: inline-flex; align-items: center; gap: 8px; border: 1px solid #b9ddd3; border-radius: 999px; padding: 8px 11px; color: #0f5f59; background: #f0fbf7; font-size: 13px; font-weight: 700; }
.opinion-status span { width: 8px; height: 8px; border-radius: 50%; background: #0f9f6e; }
.monitor-bar { display: flex; gap: 10px; margin: 18px 0; }
.monitor-bar select { min-height: 38px; border: 1px solid #cbd5e1; border-radius: 6px; padding: 7px 9px; font-size: 13px; min-width: 240px; }
.panel { border: 1px solid rgba(37, 67, 63, 0.15); border-radius: 8px; background: rgba(255, 255, 255, 0.9); margin-bottom: 14px; overflow: hidden; }
.panel-title { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 14px 16px; border-bottom: 1px solid #e1ebe7; background: #fbfdfc; }
.panel-title h3 { margin: 0; font-size: 16px; }
.count, .panel-actions select, .alert-head small, .edge-item small, .suggestion-item small { color: #64748b; font-size: 12px; }
.panel-actions { display: flex; gap: 8px; align-items: center; }
.empty-cell { padding: 20px 16px; color: #64748b; font-size: 13px; text-align: center; }
.alert-list, .edge-list { display: grid; }
.alert-item, .edge-item { padding: 14px 16px; border-top: 1px solid #e7efeb; }
.alert-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.risk-badge, .state-badge { border-radius: 999px; padding: 3px 9px; font-size: 12px; font-weight: 800; }
.risk-badge.ok, .state-badge.ok { color: #0f5f59; background: #f0fbf7; border: 1px solid #9bd0c1; }
.risk-badge.warn, .state-badge.warn { color: #92400e; background: #fff7ed; border: 1px solid #f0c98a; }
.risk-badge.danger, .state-badge.danger { color: #9f1c16; background: #fdf0ef; border: 1px solid #efc0ba; }
.stats-line { margin: 9px 0 0; color: #52615f; font-size: 13px; }
.alert-actions { display: flex; gap: 6px; margin-top: 10px; }
.alert-actions button, .handle-form button, .feedback-actions button, .primary-button, .ghost-button { min-height: 32px; border-radius: 6px; padding: 5px 10px; font-size: 12px; font-weight: 700; }
.alert-actions button, .ghost-button, .feedback-actions button { border: 1px solid #b8d3cb; color: #0f5f59; background: #fff; }
.primary-button { border: 1px solid #112927; color: #fff; background: #112927; }
.handle-form { display: grid; grid-template-columns: 180px 1fr auto; gap: 8px; margin-top: 12px; padding: 12px; background: #f7fbf9; border: 1px solid #dce9e4; border-radius: 7px; }
.handle-form select, .handle-form input { min-height: 34px; border: 1px solid #cbd5e1; border-radius: 6px; padding: 6px 8px; font-size: 13px; }
.notification-list { display: grid; gap: 6px; margin-top: 10px; padding: 10px; background: #f8fafc; border-radius: 7px; }
.notification-list li { display: flex; gap: 8px; align-items: center; font-size: 12px; color: #52615f; }
.notification-list small { color: #94a3b8; }
.suggestion-box { display: grid; gap: 10px; margin-top: 12px; padding: 12px; background: #fff8f1; border: 1px solid #f0c98a; border-radius: 7px; }
.suggestion-item { display: grid; grid-template-columns: minmax(0, 1fr); min-width: 0; gap: 6px; }
.suggestion-item p { min-width: 0; margin: 0; color: #8a421a; font-size: 13px; line-height: 1.65; white-space: pre-wrap; overflow-wrap: anywhere; }
.feedback-actions { display: flex; gap: 6px; }
.edge-item { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.edge-type { font-weight: 800; color: #1d4ed8; }
.feedback { padding: 9px 13px; border-radius: 7px; font-size: 12px; margin: 10px 0; color: #9f1c16; background: #fff5f4; border: 1px solid #f0b7b2; }
@media (max-width: 620px) { .opinion-head { flex-direction: column; align-items: flex-start; } .handle-form { grid-template-columns: 1fr; } }
</style>
