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
      <div v-else class="spread-view">
        <div class="spread-summary">
          <div class="spread-kpis">
            <span><strong>{{ graphModel.nodes.length }}</strong> 个节点</span>
            <span><strong>{{ graphModel.edges.length }}</strong> 条主路径</span>
            <span><strong>{{ verifiedEdgeCount }}</strong> 条已验证</span>
          </div>
          <div class="spread-legend">
            <span><i class="legend-line verified"></i>已验证关系</span>
            <span><i class="legend-line inferred"></i>推测关系</span>
          </div>
        </div>

        <div v-if="!graphModel.nodes.length" class="empty-cell">传播关系已加载，暂未找到对应文章。</div>
        <div v-else class="spread-graph-scroll">
          <div
            class="spread-graph"
            role="img"
            :aria-label="`传播图包含 ${graphModel.nodes.length} 个节点和 ${graphModel.edges.length} 条主路径`"
            :style="{ width: `${graphModel.width}px`, height: `${graphModel.height}px` }"
          >
            <svg
              class="spread-lines"
              :viewBox="`0 0 ${graphModel.width} ${graphModel.height}`"
              aria-hidden="true"
            >
              <defs>
                <marker id="spread-arrow-verified" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                  <path d="M 0 0 L 10 5 L 0 10 z" class="arrow-verified" />
                </marker>
                <marker id="spread-arrow-inferred" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                  <path d="M 0 0 L 10 5 L 0 10 z" class="arrow-inferred" />
                </marker>
              </defs>
              <path
                v-for="edge in graphModel.edges"
                :key="edge.displayKey"
                :d="edge.path"
                :class="['graph-edge', edge.verified ? 'verified' : 'inferred']"
                :marker-end="edge.verified ? 'url(#spread-arrow-verified)' : 'url(#spread-arrow-inferred)'"
              />
            </svg>

            <article
              v-for="node in graphModel.nodes"
              :key="node.id"
              :class="['graph-node', node.kind]"
              :style="{
                width: `${graphModel.nodeWidth}px`,
                height: `${graphModel.nodeHeight}px`,
                transform: `translate(${node.x}px, ${node.y}px)`,
              }"
            >
              <div class="graph-node-top">
                <span class="graph-node-kind">{{ node.label }}</span>
                <strong>#{{ node.id }}</strong>
              </div>
              <h4 :title="node.title">{{ node.title }}</h4>
              <div class="graph-node-meta">
                <span :title="node.author || `来源 ${node.sourceId || '-'}`">{{ node.author || `来源 ${node.sourceId || '-'}` }}</span>
                <time>{{ formatTime(node.publishTime || node.collectedAt) }}</time>
              </div>
            </article>
          </div>
        </div>

        <div class="spread-evidence">
          <div class="spread-evidence-head">
            <strong>关系证据</strong>
            <span>{{ normalizedEdges.length }} 条</span>
          </div>
          <ul class="edge-list">
            <li v-for="edge in normalizedEdges" :key="edge.displayKey" class="edge-item">
              <div class="edge-route">
                <span class="edge-article">#{{ edge.fromArticleId }}</span>
                <span class="edge-route-line" :class="{ verified: edge.verified }"></span>
                <span class="edge-article">#{{ edge.toArticleId }}</span>
              </div>
              <span :class="['state-badge', edge.verified ? 'ok' : 'warn']">{{ edge.verified ? '已验证' : '推测' }}</span>
              <span class="edge-type">{{ edge.relationType }}</span>
              <small>{{ edge.evidence }}</small>
            </li>
          </ul>
        </div>
      </div>
    </section>
  </main>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import {
  analyzeOpinionSpread, feedbackOpinionSuggestion, fetchOpinionAlerts, fetchOpinionMonitors,
  fetchOpinionArticles, fetchOpinionNotifications, fetchOpinionSpread, fetchOpinionSuggestions,
  generateOpinionSuggestion, handleOpinionAlert,
} from '../api';

const monitors = ref([]);
const monitorId = ref(null);
const alerts = ref([]);
const edges = ref([]);
const spreadArticles = ref([]);
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

const articleTime = (article) => new Date(article?.publishTime || article?.collectedAt || 0).getTime() || 0;
const compareArticles = (left, right) =>
  articleTime(left) - articleTime(right) || Number(left?.id || 0) - Number(right?.id || 0);
const articleById = computed(() => new Map(
  spreadArticles.value.map((article) => [Number(article.id), article]),
));
const normalizedEdges = computed(() => {
  const byKey = new Map();
  for (const raw of edges.value) {
    let fromArticleId = Number(raw.fromArticleId);
    let toArticleId = Number(raw.toArticleId);
    const from = articleById.value.get(fromArticleId);
    const to = articleById.value.get(toArticleId);
    if (from && to && compareArticles(from, to) > 0) {
      [fromArticleId, toArticleId] = [toArticleId, fromArticleId];
    }
    if (fromArticleId === toArticleId) continue;
    const displayKey = `${fromArticleId}-${toArticleId}-${raw.relationType}`;
    const existing = byKey.get(displayKey);
    if (!existing || Number(raw.confidence || 0) > Number(existing.confidence || 0)) {
      byKey.set(displayKey, { ...raw, fromArticleId, toArticleId, displayKey });
    }
  }
  return [...byKey.values()].sort((a, b) => Number(b.verified) - Number(a.verified)
    || Number(b.confidence || 0) - Number(a.confidence || 0));
});
const primaryEdges = computed(() => {
  const verified = normalizedEdges.value.filter((edge) => edge.verified);
  const selected = [...verified];
  const verifiedTargets = new Set(verified.map((edge) => edge.toArticleId));
  const inferredByTarget = new Map();

  for (const edge of normalizedEdges.value) {
    if (edge.verified || verifiedTargets.has(edge.toArticleId)) continue;
    const group = inferredByTarget.get(edge.toArticleId) || [];
    group.push(edge);
    inferredByTarget.set(edge.toArticleId, group);
  }

  for (const candidates of inferredByTarget.values()) {
    const bestConfidence = Math.max(...candidates.map((edge) => Number(edge.confidence || 0)));
    const plausible = candidates.filter((edge) =>
      Number(edge.confidence || 0) >= bestConfidence - 0.05);
    plausible.sort((left, right) => {
      const leftFrom = articleById.value.get(left.fromArticleId);
      const rightFrom = articleById.value.get(right.fromArticleId);
      return articleTime(rightFrom) - articleTime(leftFrom)
        || Number(right.confidence || 0) - Number(left.confidence || 0);
    });
    if (plausible[0]) selected.push(plausible[0]);
  }

  return selected.sort((left, right) => {
    const leftFrom = articleById.value.get(left.fromArticleId);
    const rightFrom = articleById.value.get(right.fromArticleId);
    return compareArticles(leftFrom, rightFrom)
      || Number(right.verified) - Number(left.verified)
      || Number(right.confidence || 0) - Number(left.confidence || 0);
  });
});
const graphModel = computed(() => {
  const nodeWidth = 220;
  const nodeHeight = 124;
  const minimumColumnGap = 112;
  const rowGap = 28;
  const padding = 28;
  const graphEdges = primaryEdges.value.filter((edge) =>
    articleById.value.has(edge.fromArticleId) && articleById.value.has(edge.toArticleId));
  const nodeIds = new Set(graphEdges.flatMap((edge) => [edge.fromArticleId, edge.toArticleId]));
  const articles = spreadArticles.value
    .filter((article) => nodeIds.has(Number(article.id)))
    .sort(compareArticles);
  const incoming = new Map(articles.map((article) => [Number(article.id), []]));

  for (const edge of graphEdges) {
    incoming.get(edge.toArticleId)?.push(edge);
  }

  const depthById = new Map();
  for (const article of articles) {
    const parents = incoming.get(Number(article.id)) || [];
    const depth = parents.length
      ? Math.max(...parents.map((edge) => depthById.get(edge.fromArticleId) ?? 0)) + 1
      : 0;
    depthById.set(Number(article.id), depth);
  }

  const layers = new Map();
  for (const article of articles) {
    const depth = depthById.get(Number(article.id)) || 0;
    const layer = layers.get(depth) || [];
    layer.push(article);
    layers.set(depth, layer);
  }
  for (const layer of layers.values()) layer.sort(compareArticles);

  const maxDepth = Math.max(0, ...layers.keys());
  const maxRows = Math.max(1, ...[...layers.values()].map((layer) => layer.length));
  const contentHeight = maxRows * nodeHeight + Math.max(0, maxRows - 1) * rowGap;
  const minimumWidth = 1040;
  const naturalWidth = padding * 2 + (maxDepth + 1) * nodeWidth + maxDepth * minimumColumnGap;
  const width = Math.max(minimumWidth, naturalWidth);
  const columnGap = maxDepth > 0
    ? Math.max(minimumColumnGap, (width - padding * 2 - (maxDepth + 1) * nodeWidth) / maxDepth)
    : minimumColumnGap;
  const height = Math.max(220, padding * 2 + contentHeight);
  const positions = new Map();

  for (const [depth, layer] of layers.entries()) {
    const layerHeight = layer.length * nodeHeight + Math.max(0, layer.length - 1) * rowGap;
    const startY = padding + (contentHeight - layerHeight) / 2;
    layer.forEach((article, index) => {
      positions.set(Number(article.id), {
        x: padding + depth * (nodeWidth + columnGap),
        y: startY + index * (nodeHeight + rowGap),
      });
    });
  }

  const nodes = articles.map((article) => {
    const articleId = Number(article.id);
    const incomingEdges = incoming.get(articleId) || [];
    const verifiedParent = incomingEdges.find((edge) => edge.verified);
    const position = positions.get(articleId) || { x: padding, y: padding };
    return {
      ...article,
      ...position,
      id: articleId,
      kind: incomingEdges.length === 0 ? 'origin' : verifiedParent ? 'verified' : 'inferred',
      label: incomingEdges.length === 0
        ? '首发'
        : verifiedParent?.relationType || '推测扩散',
    };
  });
  const laidOutEdges = graphEdges.map((edge) => {
    const from = positions.get(edge.fromArticleId);
    const to = positions.get(edge.toArticleId);
    const startX = from.x + nodeWidth;
    const startY = from.y + nodeHeight / 2;
    const endX = to.x;
    const endY = to.y + nodeHeight / 2;
    const bendX = startX + (endX - startX) / 2;
    return {
      ...edge,
      path: `M ${startX} ${startY} C ${bendX} ${startY}, ${bendX} ${endY}, ${endX - 8} ${endY}`,
    };
  });

  return { width, height, nodeWidth, nodeHeight, nodes, edges: laidOutEdges };
});
const verifiedEdgeCount = computed(() =>
  graphModel.value.edges.filter((edge) => edge.verified).length);
const riskClass = (value) => ({ 危机: 'danger', 预警: 'warn', 关注: 'ok' }[value] || 'warn');
const stateClass = (value) => ({ resolved: 'ok', closed: 'ok', acknowledged: 'warn', processing: 'warn', triggered: 'danger' }[value] || 'warn');
const stateLabel = (value) => ({ triggered: '已触发', acknowledged: '已确认', processing: '处理中', resolved: '已解决', closed: '已关闭' }[value] || value);
const formatTime = (value) => {
  if (!value) return '-';
  const raw = String(value).trim();
  const hasTz = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw);
  const date = new Date(hasTz ? raw : raw.replace(' ', 'T'));
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
    spreadArticles.value = monitorId.value
      ? (await fetchOpinionArticles({ monitorId: monitorId.value, pageSize: 50 })).items || []
      : [];
    if (!monitorId.value && m.length) { monitorId.value = m[0].id; await loadAll(); }
  } catch (e) {
    error.value = `加载失败：${e.message}`;
  } finally { loading.value = false; }
}
async function loadSpread() {
  if (!monitorId.value) { edges.value = []; spreadArticles.value = []; return; }
  const [nextEdges, result] = await Promise.all([
    fetchOpinionSpread(monitorId.value, verifiedFilter.value === '' ? undefined : verifiedFilter.value === 'true'),
    fetchOpinionArticles({ monitorId: monitorId.value, pageSize: 50 }),
  ]);
  edges.value = nextEdges;
  spreadArticles.value = result.items || [];
}
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
.spread-view { padding: 16px; }
.spread-summary { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding-bottom: 14px; border-bottom: 1px solid #e7efeb; }
.spread-kpis { display: flex; flex-wrap: wrap; gap: 8px 18px; }
.spread-kpis span { color: #64748b; font-size: 12px; }
.spread-kpis strong { margin-right: 3px; color: #112927; font-size: 16px; font-variant-numeric: tabular-nums; }
.spread-evidence-head strong { color: #112927; font-size: 14px; }
.spread-evidence-head span { color: #64748b; font-size: 12px; }
.spread-legend { display: flex; flex-wrap: wrap; gap: 10px 14px; }
.spread-legend span { display: inline-flex; align-items: center; gap: 6px; color: #52615f; font-size: 12px; }
.legend-line { display: inline-block; width: 24px; height: 3px; border-radius: 2px; background: #0f766e; }
.legend-line.inferred { height: 0; border-top: 2px dashed #d97706; background: transparent; }
.spread-graph-scroll { overflow-x: auto; margin: 0 -4px; padding: 20px 4px 24px; }
.spread-graph { position: relative; min-width: 760px; border: 1px solid #dce9e4; border-radius: 8px; background-color: #fbfdfc; background-image: linear-gradient(#edf4f1 1px, transparent 1px), linear-gradient(90deg, #edf4f1 1px, transparent 1px); background-size: 32px 32px; }
.spread-lines { position: absolute; inset: 0; width: 100%; height: 100%; overflow: visible; pointer-events: none; }
.graph-edge { fill: none; stroke-linecap: round; }
.graph-edge.verified { stroke: #0f766e; stroke-width: 3; }
.graph-edge.inferred { stroke: #d97706; stroke-width: 2.5; stroke-dasharray: 8 7; }
.arrow-verified { fill: #0f766e; }
.arrow-inferred { fill: #d97706; }
.graph-node { position: absolute; top: 0; left: 0; display: grid; grid-template-rows: auto minmax(0, 1fr) auto; gap: 8px; padding: 13px 14px; overflow: hidden; border: 1px solid #cbded8; border-radius: 8px; background: #fff; box-shadow: 0 5px 14px rgba(17, 41, 39, 0.08); }
.graph-node.origin { border-color: #0f766e; box-shadow: 0 0 0 3px #e2f3ed, 0 5px 14px rgba(17, 41, 39, 0.08); }
.graph-node.verified { border-color: #73b7a4; }
.graph-node.inferred { border-color: #dfb66e; }
.graph-node-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.graph-node-top strong { color: #0f5f59; font-size: 15px; font-variant-numeric: tabular-nums; }
.graph-node-kind { max-width: 130px; overflow: hidden; color: #0f5f59; font-size: 11px; font-weight: 800; text-overflow: ellipsis; white-space: nowrap; }
.graph-node.inferred .graph-node-kind { color: #9a5708; }
.graph-node h4 { display: -webkit-box; margin: 0; overflow: hidden; color: #17233a; font-size: 13px; line-height: 1.5; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.graph-node-meta { display: grid; gap: 3px; min-width: 0; }
.graph-node-meta span, .graph-node-meta time { display: block; overflow: hidden; color: #52615f; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.graph-node-meta time { color: #64748b; font-variant-numeric: tabular-nums; }
.spread-evidence { padding-top: 14px; border-top: 1px solid #e7efeb; }
.spread-evidence-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px; }
.spread-evidence .edge-list { display: grid; }
.spread-evidence .edge-item { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding: 12px 0; border-top: 1px solid #eef3f1; }
.spread-evidence .edge-item small { min-width: 0; flex: 1 1 260px; white-space: normal; overflow-wrap: anywhere; }
.edge-route { display: inline-flex; align-items: center; gap: 7px; min-width: 112px; }
.edge-article { color: #17233a; font-size: 14px; font-weight: 800; }
.edge-route-line { position: relative; width: 28px; height: 0; border-top: 2px dashed #d97706; }
.edge-route-line::after { content: ''; position: absolute; right: -1px; top: -4px; border-top: 5px solid transparent; border-bottom: 5px solid transparent; border-left: 7px solid #d97706; }
.edge-route-line.verified { height: 2px; border-top: 0; background: #0f766e; }
.edge-route-line.verified::after { border-left-color: #0f766e; }
.edge-type { font-weight: 800; color: #1d4ed8; }
.feedback { padding: 9px 13px; border-radius: 7px; font-size: 12px; margin: 10px 0; color: #9f1c16; background: #fff5f4; border: 1px solid #f0b7b2; }
@media (max-width: 620px) { .opinion-head { flex-direction: column; align-items: flex-start; } .monitor-bar { display: grid; grid-template-columns: minmax(0, 1fr) 88px; } .monitor-bar select { min-width: 0; width: 100%; } .monitor-bar .primary-button { width: 88px; min-width: 0; } .panel-title { align-items: flex-start; flex-wrap: wrap; } .panel-title .panel-actions { display: grid; grid-template-columns: minmax(0, 1fr) auto; width: 100%; } .panel-actions select { min-width: 0; width: 100%; } .handle-form { grid-template-columns: 1fr; } .spread-summary { align-items: flex-start; flex-direction: column; } .spread-view { padding: 12px; } .spread-evidence .edge-item small { flex-basis: 100%; } }
</style>
