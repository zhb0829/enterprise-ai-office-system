<template>
  <main class="opinion-page" aria-labelledby="opinion-title">
    <header class="opinion-head">
      <div>
        <p class="eyebrow">企业实时舆情监控</p>
        <h2 id="opinion-title">舆情分析</h2>
        <p class="opinion-lead">配置监控词，采集公开来源内容，完成情感、事件与风险分析，并支持人工复核修正。</p>
      </div>
      <div class="opinion-status" role="status" aria-live="polite">
        <span aria-hidden="true"></span>
        {{ loading ? '正在同步舆情视图' : '舆情视图已就绪' }}
      </div>
    </header>

    <section class="opinion-layout">
      <aside class="opinion-side">
        <div class="panel">
          <div class="panel-title"><h3>新建监控任务</h3></div>
          <form class="monitor-form" @submit.prevent="createMonitor">
            <label><span>任务名称</span><input v-model.trim="form.name" required maxlength="128" placeholder="如：核心品牌监测" /></label>
            <label><span>企业名称</span><input v-model.trim="form.enterpriseName" maxlength="128" placeholder="如：某科技有限公司" /></label>
            <label><span>品牌词</span><input v-model="form.brandWords" placeholder="逗号分隔" /></label>
            <label><span>竞品词</span><input v-model="form.competitorWords" placeholder="逗号分隔" /></label>
            <label><span>高管姓名</span><input v-model="form.executiveNames" placeholder="逗号分隔" /></label>
            <label><span>排除词</span><input v-model="form.excludeWords" placeholder="命中即不关联" /></label>
            <label><span>匹配模式</span>
              <select v-model="form.matchMode">
                <option value="any">任一命中</option>
                <option value="all">全部命中</option>
              </select>
            </label>
            <label><span>监控周期(天)</span><input type="number" min="1" max="90" v-model.number="form.timeWindowDays" /></label>
            <button class="primary-button" type="submit" :disabled="saving">{{ saving ? '创建中...' : '创建监控任务' }}</button>
          </form>
          <p v-if="message" class="feedback" role="status">{{ message }}</p>
        </div>

        <div class="panel">
          <div class="panel-title"><h3>监控任务</h3><span class="count">{{ monitors.length }} 个</span></div>
          <div v-if="!monitors.length" class="empty-cell">暂无监控任务</div>
          <ul v-else class="monitor-list">
            <li v-for="monitor in monitors" :key="monitor.id"
                :class="['monitor-item', { active: selectedMonitorId === monitor.id }]">
              <button type="button" class="monitor-select" @click="selectMonitor(monitor.id)">
                <strong>{{ monitor.name }}</strong>
                <small>{{ (monitor.brandWords || []).join('、') || '未配置品牌词' }}</small>
              </button>
              <div class="monitor-actions">
                <button type="button" :disabled="collecting" @click="triggerCollect(monitor.id)">采集</button>
                <button type="button" @click="toggleMonitor(monitor)">{{ monitor.status === 'enabled' ? '停用' : '启用' }}</button>
                <button type="button" @click="removeMonitor(monitor)">删除</button>
              </div>
            </li>
          </ul>
        </div>
      </aside>

      <section class="opinion-main">
        <div class="metrics">
          <div class="metric-card"><span>采集文章</span><strong>{{ articles.total || 0 }}</strong><small>已匹配入库</small></div>
          <div class="metric-card"><span>热点事件</span><strong>{{ events.length }}</strong><small>已聚合事件</small></div>
          <div class="metric-card"><span>负面文章</span><strong>{{ negativeCount }}</strong><small>情感为负面</small></div>
        </div>

        <p v-if="error" class="feedback danger" role="alert">{{ error }}<button type="button" @click="loadAll">重试</button></p>

        <div class="panel">
          <div class="panel-title">
            <h3>热点事件</h3>
            <div class="panel-actions"><select v-model="riskFilter" aria-label="风险等级" @change="loadEvents">
              <option value="">全部等级</option><option value="危机">危机</option><option value="预警">预警</option><option value="关注">关注</option>
            </select><button class="ghost-button" type="button" @click="loadEvents">刷新</button></div>
          </div>
          <div v-if="!events.length" class="empty-cell">暂无事件，请先创建监控任务并触发采集。</div>
          <ul v-else class="event-list">
            <li v-for="event in events" :key="event.id" class="event-item">
              <div class="event-head">
                <strong>{{ event.title }}</strong>
                <span :class="['risk-badge', riskClass(event.riskLevel)]">{{ event.riskLevel }}</span>
              </div>
              <p>{{ event.summary }}</p>
              <div class="event-meta">
                <span>{{ (event.sentimentDist || {}).negative || 0 }} 条负面</span>
                <span>{{ event.reportCount }} 篇文章</span>
                <span>{{ event.sourceWeight || 0 }} 个来源</span>
                <button type="button" @click="expandEvent(event)">{{ eventExpanded === event.id ? '收起' : '查看文章' }}</button>
              </div>
              <div v-if="eventExpanded === event.id" class="event-articles">
                <article v-for="article in eventArticles[event.id] || []" :key="article.id">
                  <span :class="['sentiment-badge', sentimentClass(article.analysis?.sentiment)]">{{ sentimentLabel(article.analysis?.sentiment) }}</span>
                  <div>
                    <strong>{{ article.title }}</strong>
                    <small>{{ article.url }}</small>
                  </div>
                  <a v-if="article.url" :href="article.url" target="_blank" rel="noreferrer">原文</a>
                </article>
              </div>
            </li>
          </ul>
        </div>

        <div class="panel">
          <div class="panel-title">
            <h3>文章与情感分析</h3>
            <div class="panel-actions">
              <select v-model="sentimentFilter" aria-label="情感筛选" @change="loadArticles">
                <option value="">全部情感</option><option value="positive">正面</option><option value="neutral">中性</option><option value="negative">负面</option>
              </select>
              <input v-model.trim="articleKeyword" type="search" placeholder="搜索标题/内容" @keyup.enter="loadArticles" />
              <button class="ghost-button" type="button" @click="loadArticles">查询</button>
            </div>
          </div>
          <div v-if="!articles.items?.length" class="empty-cell">暂无文章，触发采集后再来查看。</div>
          <ul v-else class="article-list">
            <li v-for="article in articles.items" :key="article.id" class="article-list-item">
              <div class="article-row">
                <span :class="['sentiment-badge', sentimentClass(article.analysis?.sentiment || (article.articleAnalysis?.at(-1)?.sentiment))]">{{ sentimentLabel(article.analysis?.sentiment || (article.articleAnalysis?.at(-1)?.sentiment)) }}</span>
                <div class="article-row-main">
                  <strong>{{ article.title }}</strong>
                  <small>{{ article.url }}</small>
                </div>
                <button class="ghost-button" type="button" @click="toggleArticle(article)">{{ detailArticleId === article.id ? '收起' : '详情/复核' }}</button>
              </div>
              <div v-if="detailArticleId === article.id" class="article-detail">
                <p>{{ excerpt(article.content, 300) }}</p>
                <div class="analysis-meta" v-if="article.analysis">
                  <span>置信度 {{ (article.analysis.confidence * 100).toFixed(1) }}%</span>
                  <span>风险分 {{ article.analysis.riskScore }}</span>
                  <span>模型 {{ article.analysis.model || 'rule-based' }}</span>
                  <span v-if="article.analysis.reason" class="reason">理由：{{ article.analysis.reason }}</span>
                </div>
                <div v-if="currentDetailArticleId === article.id" class="review-form">
                  <label><span>人工修正情感</span>
                    <select v-model="reviewForm.sentiment">
                      <option value="positive">正面</option><option value="neutral">中性</option><option value="negative">负面</option>
                    </select>
                  </label>
                  <label><span>风险分</span><input type="number" min="0" max="100" v-model.number="reviewForm.riskScore" /></label>
                  <label><span>修正原因</span><input v-model.trim="reviewForm.reason" placeholder="必填，便于审计追溯" /></label>
                  <button class="primary-button" type="button" :disabled="reviewing" @click="submitReview(article)">{{ reviewing ? '提交中...' : '提交修正' }}</button>
                </div>
              </div>
            </li>
          </ul>
        </div>
      </section>
    </section>
  </main>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import {
  createOpinionMonitor, deleteOpinionMonitor, fetchOpinionArticles, fetchOpinionEvents,
  fetchOpinionMonitors, reviewOpinionAnalysis, toggleOpinionMonitor, triggerOpinionMonitor,
} from '../api';

const monitors = ref([]);
const articles = ref({ items: [], total: 0 });
const events = ref([]);
const selectedMonitorId = ref(null);
const riskFilter = ref('');
const sentimentFilter = ref('');
const articleKeyword = ref('');
const eventExpanded = ref(null);
const eventArticles = ref({});
const detailArticleId = ref(null);
const currentDetailArticleId = ref(null);
const loading = ref(false);
const saving = ref(false);
const collecting = ref(false);
const reviewing = ref(false);
const message = ref('');
const error = ref('');
const form = reactive({
  name: '', enterpriseName: '', brandWords: '', competitorWords: '', executiveNames: '',
  excludeWords: '', matchMode: 'any', timeWindowDays: 7,
});
const reviewForm = reactive({ sentiment: 'negative', riskScore: 0, reason: '' });

const split = (value) => String(value || '').split(/[,，]/).map((item) => item.trim()).filter(Boolean);
const negativeCount = computed(() => (articles.value.items || []).filter((article) =>
  (article.analysis?.sentiment || article.articleAnalysis?.at(-1)?.sentiment) === 'negative').length);
const sentimentLabel = (value) => ({ positive: '正面', neutral: '中性', negative: '负面' }[value] || '未分析');
const sentimentClass = (value) => ({ positive: 'ok', neutral: 'warn', negative: 'danger' }[value] || 'warn');
const riskClass = (value) => ({ 危机: 'danger', 预警: 'warn', 关注: 'ok' }[value] || 'warn');
const excerpt = (value, length = 120) => {
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  return text.length > length ? `${text.slice(0, length)}...` : text;
};
const formatTime = (value) => {
  if (!value) return '-';
  const raw = String(value).trim();
  const hasTz = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw);
  const date = new Date(hasTz ? raw : `${raw.replace(' ', 'T')}Z`);
  return Number.isNaN(date.getTime()) ? raw : date.toLocaleString();
};

async function loadMonitors() {
  monitors.value = await fetchOpinionMonitors();
  if (!selectedMonitorId.value && monitors.value.length) selectedMonitorId.value = monitors.value[0].id;
}
async function loadArticles() {
  if (!selectedMonitorId.value) { articles.value = { items: [], total: 0 }; return; }
  const result = await fetchOpinionArticles({ monitorId: selectedMonitorId.value, keyword: articleKeyword.value, pageSize: 50 });
  const withAnalysis = await Promise.all((result.items || []).map(async (article) => {
    const analysis = article.articleAnalysis?.at(-1);
    if (analysis) return { ...article, analysis };
    try {
      const analyses = await fetchAnalysisFor(article.id);
      return { ...article, articleAnalysis: analyses, analysis: analyses?.at(-1) };
    } catch {
      return { ...article };
    }
  }));
  articles.value = { items: withAnalysis, total: result.total || withAnalysis.length };
}
async function loadEvents() {
  if (!selectedMonitorId.value) { events.value = []; return; }
  events.value = await fetchOpinionEvents({ monitorId: selectedMonitorId.value, riskLevel: riskFilter.value });
}
async function loadAll() {
  error.value = '';
  loading.value = true;
  try {
    await loadMonitors();
    await Promise.all([loadArticles(), loadEvents()]);
  } catch (e) {
    error.value = `加载失败：${e.message}`;
  } finally {
    loading.value = false;
  }
}
async function createMonitor() {
  saving.value = true; message.value = '';
  try {
    await createOpinionMonitor({
      ...form,
      brandWords: split(form.brandWords), competitorWords: split(form.competitorWords),
      executiveNames: split(form.executiveNames), excludeWords: split(form.excludeWords),
    });
    Object.assign(form, { name: '', enterpriseName: '', brandWords: '', competitorWords: '', executiveNames: '', excludeWords: '' });
    message.value = '监控任务已创建。';
    await loadMonitors();
  } catch (e) {
    message.value = `创建失败：${e.message}`;
  } finally {
    saving.value = false;
  }
}
async function selectMonitor(id) {
  selectedMonitorId.value = id;
  await Promise.all([loadArticles(), loadEvents()]);
}
async function triggerCollect(id) {
  collecting.value = true; message.value = '';
  try {
    await triggerOpinionMonitor(id);
    message.value = '已触发公开来源采集，分析任务将异步处理。';
  } catch (e) {
    message.value = `触发失败：${e.message}`;
  } finally {
    collecting.value = false;
  }
}
async function toggleMonitor(monitor) {
  try {
    await toggleOpinionMonitor(monitor.id);
    await loadMonitors();
  } catch (e) {
    message.value = `状态更新失败：${e.message}`;
  }
}
async function removeMonitor(monitor) {
  if (!window.confirm(`确定删除监控任务「${monitor.name}」？`)) return;
  try {
    await deleteOpinionMonitor(monitor.id);
    if (selectedMonitorId.value === monitor.id) selectedMonitorId.value = null;
    await loadAll();
  } catch (e) {
    message.value = `删除失败：${e.message}`;
  }
}
async function expandEvent(event) {
  if (eventExpanded.value === event.id) { eventExpanded.value = null; return; }
  eventExpanded.value = event.id;
  try {
    const ids = event.articleIds || [];
    const items = articles.value.items || [];
    eventArticles.value = { ...eventArticles.value, [event.id]: ids.map((id) => items.find((a) => a.id === id)).filter(Boolean) };
  } catch {
    eventArticles.value = { ...eventArticles.value, [event.id]: [] };
  }
}
async function toggleArticle(article) {
  if (detailArticleId.value === article.id) { detailArticleId.value = null; return; }
  detailArticleId.value = article.id;
  currentDetailArticleId.value = article.id;
  Object.assign(reviewForm, { sentiment: article.analysis?.sentiment || 'neutral', riskScore: article.analysis?.riskScore || 0, reason: '' });
}
async function fetchAnalysisFor(articleId) {
  const { fetchOpinionAnalysis } = await import('../api');
  return fetchOpinionAnalysis(articleId);
}
async function submitReview(article) {
  const analysisId = article.analysis?.id;
  if (!analysisId) { message.value = '该文章暂无分析结果可修正。'; return; }
  if (!reviewForm.reason.trim()) { message.value = '请填写修正原因（审计追溯）。'; return; }
  reviewing.value = true;
  try {
    await reviewOpinionAnalysis(analysisId, { targetType: 'opinion_analysis', targetId: analysisId, field: 'review', sentiment: reviewForm.sentiment, riskScore: reviewForm.riskScore, reason: reviewForm.reason });
    message.value = '修正已提交并记录审计。';
    await Promise.all([loadArticles(), loadEvents()]);
  } catch (e) {
    message.value = `修正失败：${e.message}`;
  } finally {
    reviewing.value = false;
  }
}
onMounted(loadAll);
</script>

<style scoped>
.opinion-page { max-width: 1480px; margin: 0 auto; padding: clamp(24px, 4vw, 52px) clamp(16px, 4vw, 48px) 72px; color: #17233a; }
.opinion-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 12px; padding: 10px 0 28px; border-bottom: 1px solid #d7e4df; }
.opinion-head h2 { margin: 0; color: #112927; font-size: clamp(2rem, 4vw, 3.2rem); line-height: 1.08; }
.opinion-lead { max-width: 720px; margin: 14px 0 0; color: #52615f; line-height: 1.75; }
.opinion-status { display: inline-flex; align-items: center; gap: 8px; border: 1px solid #b9ddd3; border-radius: 999px; padding: 8px 11px; color: #0f5f59; background: #f0fbf7; font-size: 13px; font-weight: 700; }
.opinion-status span { width: 8px; height: 8px; border-radius: 50%; background: #0f9f6e; }
.opinion-layout { display: grid; grid-template-columns: minmax(280px, 360px) minmax(0, 1fr); gap: 14px; margin-top: 20px; align-items: start; }
.panel { border: 1px solid rgba(37, 67, 63, 0.15); border-radius: 8px; background: rgba(255, 255, 255, 0.9); overflow: hidden; }
.panel-title { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 14px 16px; border-bottom: 1px solid #e1ebe7; background: #fbfdfc; }
.panel-title h3 { margin: 0; color: #17233a; font-size: 16px; }
.count, .panel-title small { color: #64748b; font-size: 12px; }
.monitor-form { display: grid; gap: 10px; padding: 16px; }
.monitor-form label { display: grid; gap: 5px; color: #334155; font-size: 13px; font-weight: 700; }
.monitor-form input, .monitor-form select, .panel-actions select, .panel-actions input { min-height: 38px; border: 1px solid #cbd5e1; border-radius: 6px; padding: 7px 9px; font-size: 13px; }
.monitor-list { display: grid; }
.monitor-item { padding: 12px 16px; border-top: 1px solid #e7efeb; }
.monitor-item.active { background: #f3faf7; border-left: 3px solid #0f766e; }
.monitor-select { width: 100%; display: grid; gap: 4px; border: 0; padding: 0; color: #17233a; background: transparent; text-align: left; }
.monitor-select strong { font-size: 14px; }
.monitor-select small { color: #64748b; font-size: 12px; }
.monitor-actions { display: flex; gap: 6px; margin-top: 9px; }
.monitor-actions button, .primary-button, .ghost-button, .event-meta button, .article-row button { min-height: 32px; border-radius: 6px; padding: 5px 9px; font-size: 12px; font-weight: 700; }
.monitor-actions button, .ghost-button { border: 1px solid #b8d3cb; color: #0f5f59; background: #fff; }
.primary-button { border: 1px solid #112927; color: #fff; background: #112927; }
.feedback { padding: 9px 13px; border-radius: 7px; font-size: 12px; margin: 10px 16px 16px; color: #1d4ed8; background: #eef3ff; }
.feedback.danger { color: #9f1c16; background: #fff5f4; border: 1px solid #f0b7b2; }
.feedback.danger button { background: transparent; border: 0; color: inherit; font-weight: 800; text-decoration: underline; margin-left: 6px; cursor: pointer; }
.opinion-main { display: grid; gap: 14px; }
.metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.metric-card { display: grid; gap: 3px; padding: 14px 16px; border: 1px solid rgba(37, 67, 63, 0.15); border-radius: 8px; background: rgba(255, 255, 255, 0.9); }
.metric-card span, .metric-card small { color: #64748b; font-size: 12px; }
.metric-card strong { color: #112927; font-size: 25px; font-variant-numeric: tabular-nums; }
.panel-actions { display: flex; gap: 8px; align-items: center; }
.empty-cell { padding: 20px 16px; color: #64748b; font-size: 13px; text-align: center; }
.event-list, .article-list { display: grid; }
.event-item, .article-list-item { padding: 14px 16px; border-top: 1px solid #e7efeb; }
.event-head, .article-row, .event-meta { display: flex; align-items: center; gap: 10px; }
.event-head { justify-content: space-between; }
.event-head strong { font-size: 14px; }
.risk-badge, .sentiment-badge { border-radius: 999px; padding: 3px 9px; font-size: 12px; font-weight: 800; }
.risk-badge.ok, .sentiment-badge.ok { color: #0f5f59; background: #f0fbf7; border: 1px solid #9bd0c1; }
.risk-badge.warn, .sentiment-badge.warn { color: #92400e; background: #fff7ed; border: 1px solid #f0c98a; }
.risk-badge.danger, .sentiment-badge.danger { color: #9f1c16; background: #fdf0ef; border: 1px solid #efc0ba; }
.event-item p { margin: 9px 0 0; color: #52615f; font-size: 13px; line-height: 1.65; }
.event-meta { margin-top: 9px; color: #64748b; font-size: 12px; }
.event-meta button { margin-left: auto; }
.event-articles { display: grid; gap: 8px; margin-top: 12px; padding: 12px; background: #f7fbf9; border: 1px solid #dce9e4; border-radius: 7px; }
.event-articles article { display: flex; align-items: center; gap: 9px; }
.event-articles article > div { display: grid; gap: 3px; min-width: 0; }
.event-articles strong { font-size: 13px; }
.event-articles small, .article-row-main small { color: #64748b; font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.event-articles a, .article-row a { color: #0f5f59; font-size: 12px; font-weight: 700; text-decoration: none; flex: 0 0 auto; }
.article-row { align-items: flex-start; }
.article-row-main { display: grid; gap: 4px; min-width: 0; flex: 1; }
.article-row-main strong { font-size: 14px; }
.article-row button { flex: 0 0 auto; }
.article-detail { margin-top: 10px; padding: 12px; background: #f7fbf9; border: 1px solid #dce9e4; border-radius: 7px; }
.article-detail > p { margin: 0; color: #52615f; font-size: 13px; line-height: 1.65; }
.analysis-meta { display: flex; flex-wrap: wrap; gap: 8px 14px; margin-top: 10px; color: #64748b; font-size: 12px; }
.analysis-meta .reason { width: 100%; color: #52615f; }
.review-form { display: grid; grid-template-columns: 140px 120px 1fr auto; gap: 8px; align-items: end; margin-top: 12px; padding-top: 12px; border-top: 1px solid #e1ebe7; }
.review-form label { display: grid; gap: 5px; color: #334155; font-size: 12px; font-weight: 700; }
.review-form input, .review-form select { min-height: 34px; border: 1px solid #cbd5e1; border-radius: 6px; padding: 6px 8px; font-size: 13px; }
button:disabled { opacity: 0.55; cursor: not-allowed; }
@media (max-width: 960px) { .opinion-layout { grid-template-columns: 1fr; } .metrics { grid-template-columns: repeat(3, 1fr); } }
@media (max-width: 620px) { .metrics { grid-template-columns: 1fr; } .review-form { grid-template-columns: 1fr; } .opinion-head { flex-direction: column; align-items: flex-start; } }
</style>
