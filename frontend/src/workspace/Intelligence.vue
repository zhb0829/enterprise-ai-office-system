<template>
  <main class="intelligence-page" aria-labelledby="intelligence-title">
    <header class="intelligence-head">
      <div>
        <p class="eyebrow">行业动态与竞品信息</p>
        <h2 id="intelligence-title">行业情报</h2>
        <p class="intelligence-lead">从已接入的公开来源中查看最新动态、主题聚类与已生成简报，帮助快速形成研判素材。</p>
      </div>
      <div class="intelligence-status" role="status" aria-live="polite">
        <span aria-hidden="true"></span>
        {{ loadingInitial ? '正在同步情报视图' : '情报视图已就绪' }}
      </div>
    </header>

    <section class="intelligence-metrics" aria-label="情报概览">
      <div class="metric-card">
        <span>匹配条目</span>
        <strong>{{ itemResult.total || 0 }}</strong>
        <small>按当前筛选条件</small>
      </div>
      <div class="metric-card">
        <span>主题聚类</span>
        <strong>{{ clusters.length }}</strong>
        <small>已整理可研判主题</small>
      </div>
      <div class="metric-card">
        <span>情报简报</span>
        <strong>{{ reports.length }}</strong>
        <small>日报与周报留存</small>
      </div>
    </section>

    <form class="intelligence-filter" @submit.prevent="applyFilters">
      <label>
        <span>关键词</span>
        <input v-model.trim="filters.keyword" type="search" placeholder="搜索行业、竞品或事件" />
      </label>
      <label>
        <span>来源</span>
        <select v-model="filters.sourceId">
          <option value="">全部已加载来源</option>
          <option v-for="source in sourceOptions" :key="source.id" :value="String(source.id)">{{ source.name }}</option>
        </select>
      </label>
      <div class="filter-actions">
        <button class="filter-reset" type="button" :disabled="loadingItems" @click="resetFilters">重置</button>
        <button class="filter-submit" type="submit" :disabled="loadingItems">{{ loadingItems ? '筛选中...' : '应用筛选' }}</button>
      </div>
    </form>

    <p v-if="loadError" class="intelligence-error" role="alert">
      {{ loadError }}
      <button type="button" @click="loadDashboard">重新加载</button>
    </p>

    <section class="intelligence-grid" :aria-busy="loadingInitial">
      <section class="intelligence-panel article-panel" aria-labelledby="article-title">
        <div class="panel-title">
          <div>
            <p class="eyebrow">条目流</p>
            <h3 id="article-title">最新公开动态</h3>
          </div>
          <span>{{ itemResult.total || 0 }} 条</span>
        </div>

        <div v-if="loadingItems" class="loading-list" aria-live="polite">
          <span v-for="index in 4" :key="index" class="loading-line"></span>
        </div>
        <div v-else-if="!itemResult.items.length" class="empty-state">
          <strong>暂无匹配的情报条目</strong>
          <span>调整关键词或来源筛选，或等待管理员完成下一次采集。</span>
        </div>
        <div v-else class="article-list">
          <article v-for="article in visibleArticles" :key="article.id" class="article-item">
            <div class="article-meta">
              <span>{{ article.sourceName || '公开来源' }}</span>
              <time :datetime="article.publishTime || article.collectedAt">{{ formatDate(article.publishTime || article.collectedAt) }}</time>
            </div>
            <h4>{{ article.title || '未命名情报条目' }}</h4>
            <p>{{ excerpt(article.content) }}</p>
            <div class="article-actions">
              <button type="button" :disabled="summarizing" @click="summarizeArticle(article)">
                {{ summarizing && summaryTarget === `article-${article.id}` ? '生成中...' : '单篇摘要' }}
              </button>
              <a v-if="article.url" :href="article.url" target="_blank" rel="noreferrer">查看原文</a>
            </div>
          </article>
        </div>

        <div v-if="hasMoreArticles" class="pagination-row">
          <span>当前显示 {{ visibleArticles.length }} / {{ itemResult.total }} 条</span>
          <button type="button" :disabled="loadingMore" @click="loadMoreItems">
            {{ loadingMore ? '加载中...' : '加载更多' }}
          </button>
        </div>
      </section>

      <section class="intelligence-panel cluster-panel" aria-labelledby="cluster-title">
        <div class="panel-title">
          <div>
            <p class="eyebrow">主题聚类</p>
            <h3 id="cluster-title">近期关注主题</h3>
          </div>
          <span>{{ clusters.length }} 个</span>
        </div>
        <label class="topic-filter">
          <span class="visually-hidden">过滤主题</span>
          <input v-model.trim="topicQuery" type="search" placeholder="过滤主题" @input="filterClusters" />
        </label>
        <div v-if="loadingClusters" class="loading-list compact" aria-live="polite">
          <span v-for="index in 3" :key="index" class="loading-line"></span>
        </div>
        <div v-else-if="!clusters.length" class="empty-state compact-empty">
          <strong>暂无可用主题</strong>
          <span>采集到足够条目后会自动聚合主题。</span>
        </div>
        <div v-else class="cluster-list">
          <article v-for="cluster in visibleClusters" :key="cluster.id" :class="['cluster-item', { selected: selectedCluster?.id === cluster.id }]">
            <button type="button" class="cluster-select" :aria-pressed="selectedCluster?.id === cluster.id" @click="selectCluster(cluster)">
              <span class="cluster-count">{{ cluster.report_count || 0 }}</span>
              <span>
                <strong>{{ cluster.topic }}</strong>
                <small>{{ cluster.sources?.length || 0 }} 个来源 · {{ formatDate(cluster.time_end || cluster.updated_at) }}</small>
              </span>
            </button>
            <p>{{ excerpt(cluster.summary, 110) || '选择主题后生成摘要，查看关联公开来源。' }}</p>
          </article>
        </div>
        <div v-if="hasMoreClusters" class="pagination-row">
          <span>当前显示 {{ visibleClusters.length }} / {{ clusters.length }} 个</span>
          <button type="button" @click="loadMoreClusters">加载更多</button>
        </div>
      </section>

      <aside class="intelligence-side" aria-label="摘要与简报">
        <section class="intelligence-panel summary-panel" aria-labelledby="summary-title">
          <div class="panel-title">
            <div>
              <p class="eyebrow">智能摘要</p>
              <h3 id="summary-title">{{ summaryTitle }}</h3>
            </div>
            <span v-if="summaryResult">已生成</span>
          </div>
          <div v-if="summarizing" class="summary-loading" aria-live="polite">正在根据公开来源整理摘要...</div>
          <div v-else-if="summaryResult" class="summary-content">
            <p>{{ summaryResult.summary }}</p>
            <div v-if="summaryResult.riskFlags?.length" class="summary-note">{{ summaryResult.riskFlags[0] }}</div>
            <div v-if="summaryResult.sources?.length" class="summary-sources">
              <span>引用来源</span>
              <a v-for="source in summaryResult.sources" :key="source.articleId" :href="source.url" target="_blank" rel="noreferrer">{{ source.title || source.sourceName }}</a>
            </div>
          </div>
          <div v-else class="empty-state compact-empty">
            <strong>选择一篇条目或主题</strong>
            <span>系统将基于关联公开来源生成可核验摘要。</span>
          </div>
        </section>

        <section class="intelligence-panel report-panel" aria-labelledby="report-title">
          <div class="panel-title">
            <div>
              <p class="eyebrow">情报简报</p>
              <h3 id="report-title">日报与周报</h3>
            </div>
            <select v-model="reportPeriod" aria-label="简报周期" @change="loadReports">
              <option value="">全部</option>
              <option value="daily">日报</option>
              <option value="weekly">周报</option>
            </select>
          </div>
          <div v-if="loadingReports" class="loading-list compact" aria-live="polite">
            <span v-for="index in 2" :key="index" class="loading-line"></span>
          </div>
          <div v-else-if="!reports.length" class="empty-state compact-empty">
            <strong>暂无已生成简报</strong>
            <span>管理员生成日报或周报后会显示在这里。</span>
          </div>
          <div v-else class="report-list">
            <article v-for="report in reports" :key="report.id" class="report-item">
              <button type="button" :aria-expanded="activeReport?.id === report.id" @click="toggleReport(report)">
                <span>
                  <strong>{{ report.title }}</strong>
                  <small>{{ periodLabel(report.period) }} · {{ formatDate(report.generatedAt) }}</small>
                </span>
                <span>{{ activeReport?.id === report.id ? '收起' : '查看' }}</span>
              </button>
              <div v-if="activeReport?.id === report.id" class="report-detail">
                <p v-if="report.trend?.articleCount !== undefined">覆盖 {{ report.trend.articleCount }} 条情报、{{ report.trend.clusterCount || 0 }} 个主题。</p>
                <ul v-if="report.items?.length">
                  <li v-for="item in report.items.slice(0, 4)" :key="item.clusterId || item.topic">
                    <strong>{{ item.topic }}</strong>
                    <span>{{ item.summary }}</span>
                  </li>
                </ul>
                <p v-else>该简报暂无可展示的主题摘要。</p>
              </div>
            </article>
          </div>
        </section>
      </aside>
    </section>
  </main>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import {
  fetchIntelligenceClusters,
  fetchIntelligenceItems,
  fetchIntelligenceReports,
  summarizeIntelligence,
} from '../api';

const PAGE_SIZE = 20;
const ARTICLE_BATCH_SIZE = 6;
const CLUSTER_BATCH_SIZE = 5;
const INITIAL_ARTICLE_COUNT = 6;
const INITIAL_CLUSTER_COUNT = 5;
const filters = ref({ keyword: '', sourceId: '' });
const topicQuery = ref('');
const reportPeriod = ref('');
const itemResult = ref({ items: [], total: 0, page: 1, pageSize: PAGE_SIZE });
const clusters = ref([]);
const visibleArticleCount = ref(INITIAL_ARTICLE_COUNT);
const visibleClusterCount = ref(INITIAL_CLUSTER_COUNT);
const reports = ref([]);
const selectedCluster = ref(null);
const summaryResult = ref(null);
const summaryTarget = ref('');
const activeReport = ref(null);
const loadingInitial = ref(true);
const loadingItems = ref(false);
const loadingMore = ref(false);
const loadingClusters = ref(false);
const loadingReports = ref(false);
const summarizing = ref(false);
const loadError = ref('');
let clusterFilterTimer;

const sourceOptions = computed(() => {
  const known = new Map();
  itemResult.value.items.forEach((item) => {
    if (item.sourceId && item.sourceName) known.set(item.sourceId, { id: item.sourceId, name: item.sourceName });
  });
  return [...known.values()];
});

const visibleArticles = computed(() => itemResult.value.items.slice(0, visibleArticleCount.value));
const visibleClusters = computed(() => clusters.value.slice(0, visibleClusterCount.value));
const hasMoreArticles = computed(() => visibleArticleCount.value < (itemResult.value.total || itemResult.value.items.length));
const hasMoreClusters = computed(() => visibleClusterCount.value < clusters.value.length);

const summaryTitle = computed(() => {
  if (selectedCluster.value) return selectedCluster.value.topic;
  if (summaryTarget.value.startsWith('article-')) return '单篇动态摘要';
  return '等待选择情报';
});

function excerpt(value, length = 170) {
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  return text.length > length ? `${text.slice(0, length)}...` : text;
}

function formatDate(value) {
  if (!value) return '时间未知';
  const raw = String(value).trim();
  const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw);
  const date = new Date(hasTimezone ? raw : `${raw.replace(' ', 'T')}Z`);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

function periodLabel(period) {
  return period === 'weekly' ? '周报' : period === 'daily' ? '日报' : period || '简报';
}

async function loadItems({ append = false } = {}) {
  const page = append ? itemResult.value.page + 1 : 1;
  if (append) loadingMore.value = true;
  else loadingItems.value = true;
  try {
    const result = await fetchIntelligenceItems({
      keyword: filters.value.keyword,
      sourceId: filters.value.sourceId,
      page,
      pageSize: PAGE_SIZE,
    });
    itemResult.value = {
      ...result,
      items: append ? [...itemResult.value.items, ...(result.items || [])] : (result.items || []),
    };
    if (!append) visibleArticleCount.value = INITIAL_ARTICLE_COUNT;
  } catch (error) {
    loadError.value = `加载条目流失败：${error.message}`;
  } finally {
    loadingItems.value = false;
    loadingMore.value = false;
  }
}

async function loadClusters() {
  loadingClusters.value = true;
  try {
    clusters.value = await fetchIntelligenceClusters(topicQuery.value);
    visibleClusterCount.value = INITIAL_CLUSTER_COUNT;
  } catch (error) {
    loadError.value = `加载主题聚类失败：${error.message}`;
  } finally {
    loadingClusters.value = false;
  }
}

async function loadReports() {
  loadingReports.value = true;
  try {
    reports.value = await fetchIntelligenceReports(reportPeriod.value);
    activeReport.value = reports.value[0] || null;
  } catch (error) {
    loadError.value = `加载情报简报失败：${error.message}`;
  } finally {
    loadingReports.value = false;
  }
}

async function loadDashboard() {
  loadError.value = '';
  loadingInitial.value = true;
  await Promise.all([loadItems(), loadClusters(), loadReports()]);
  loadingInitial.value = false;
}

async function applyFilters() {
  loadError.value = '';
  await loadItems();
}

async function resetFilters() {
  filters.value = { keyword: '', sourceId: '' };
  await loadItems();
}

function filterClusters() {
  window.clearTimeout(clusterFilterTimer);
  clusterFilterTimer = window.setTimeout(() => {
    loadClusters();
  }, 250);
}

async function loadMoreItems() {
  const nextCount = visibleArticleCount.value + ARTICLE_BATCH_SIZE;
  if (nextCount > itemResult.value.items.length && itemResult.value.items.length < itemResult.value.total) {
    await loadItems({ append: true });
  }
  visibleArticleCount.value = Math.min(nextCount, itemResult.value.total || itemResult.value.items.length);
}

function loadMoreClusters() {
  visibleClusterCount.value = Math.min(visibleClusterCount.value + CLUSTER_BATCH_SIZE, clusters.value.length);
}

async function summarizeArticle(article) {
  selectedCluster.value = null;
  summaryTarget.value = `article-${article.id}`;
  summarizing.value = true;
  try {
    summaryResult.value = await summarizeIntelligence({ articleIds: [article.id] });
  } catch (error) {
    loadError.value = `生成单篇摘要失败：${error.message}`;
  } finally {
    summarizing.value = false;
  }
}

async function selectCluster(cluster) {
  selectedCluster.value = cluster;
  summaryTarget.value = `cluster-${cluster.id}`;
  summarizing.value = true;
  try {
    summaryResult.value = await summarizeIntelligence({ clusterId: cluster.id });
  } catch (error) {
    loadError.value = `生成主题摘要失败：${error.message}`;
  } finally {
    summarizing.value = false;
  }
}

function toggleReport(report) {
  activeReport.value = activeReport.value?.id === report.id ? null : report;
}

onMounted(loadDashboard);
</script>

<style scoped>
.intelligence-page {
  max-width: 1480px;
  margin: 0 auto;
  padding: clamp(24px, 4vw, 52px) clamp(16px, 4vw, 48px) 72px;
  color: #17233a;
}

.intelligence-head,
.panel-title,
.article-meta,
.article-actions,
.pagination-row,
.cluster-select,
.report-item > button,
.report-detail li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.intelligence-head {
  align-items: flex-end;
  padding: 10px 0 28px;
  border-bottom: 1px solid #d7e4df;
}

.intelligence-head h2 {
  margin: 0;
  color: #112927;
  font-size: clamp(2rem, 4vw, 3.6rem);
  line-height: 1.08;
}

.intelligence-lead {
  max-width: 760px;
  margin: 14px 0 0;
  color: #52615f;
  line-height: 1.75;
}

.intelligence-status {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex: 0 0 auto;
  border: 1px solid #b9ddd3;
  border-radius: 999px;
  padding: 8px 11px;
  color: #0f5f59;
  background: #f0fbf7;
  font-size: 13px;
  font-weight: 700;
}

.intelligence-status span {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #0f9f6e;
}

.intelligence-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin: 20px 0;
}

.metric-card,
.intelligence-panel {
  border: 1px solid rgba(37, 67, 63, 0.15);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.9);
  box-shadow: 0 10px 28px rgba(18, 43, 40, 0.05);
}

.metric-card {
  display: grid;
  gap: 3px;
  padding: 14px 16px;
}

.metric-card span,
.metric-card small,
.panel-title > span,
.article-meta,
.cluster-select small,
.report-item small {
  color: #64748b;
  font-size: 12px;
}

.metric-card strong {
  color: #112927;
  font-size: 25px;
  font-variant-numeric: tabular-nums;
}

.intelligence-filter {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) minmax(180px, 260px) auto;
  gap: 12px;
  align-items: end;
  margin-bottom: 18px;
  padding: 14px;
  border: 1px solid #d7e4df;
  border-radius: 8px;
  background: #f7fbf9;
}

.intelligence-filter label,
.topic-filter {
  display: grid;
  gap: 6px;
  color: #334155;
  font-size: 13px;
  font-weight: 700;
}

.filter-actions {
  display: flex;
  gap: 8px;
}

.filter-actions button,
.article-actions button,
.pagination-row button {
  min-height: 42px;
  border-radius: 7px;
  padding: 8px 12px;
  font-size: 13px;
  font-weight: 700;
}

.filter-reset,
.article-actions button,
.pagination-row button {
  border: 1px solid #b8d3cb;
  color: #0f5f59;
  background: #ffffff;
}

.filter-submit {
  border: 1px solid #112927;
  color: #ffffff;
  background: #112927;
}

.filter-actions button:hover:not(:disabled),
.article-actions button:hover:not(:disabled),
.pagination-row button:hover:not(:disabled) {
  transform: translateY(-1px);
}

.filter-submit:hover:not(:disabled) {
  background: #0b4f4a;
}

.intelligence-error {
  margin: 0 0 18px;
  padding: 11px 13px;
  border: 1px solid #f0b7b2;
  border-radius: 7px;
  color: #9f1c16;
  background: #fff5f4;
  font-size: 13px;
}

.intelligence-error button {
  margin-left: 8px;
  border: 0;
  padding: 0;
  color: inherit;
  background: transparent;
  font-weight: 800;
  text-decoration: underline;
}

.intelligence-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) minmax(300px, 0.82fr) minmax(310px, 0.93fr);
  gap: 14px;
  align-items: start;
}

.intelligence-panel {
  overflow: hidden;
}

.article-panel,
.cluster-panel,
.report-panel {
  height: clamp(520px, 70vh, 680px);
  min-height: 520px;
}

.article-panel {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
}

.cluster-panel {
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr) auto;
}

.report-panel {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
}

.panel-title {
  align-items: flex-start;
  padding: 16px;
  border-bottom: 1px solid #e1ebe7;
  background: #fbfdfc;
}

.panel-title h3 {
  margin: 0;
  color: #17233a;
  font-size: 17px;
}

.panel-title .eyebrow {
  margin-bottom: 4px;
  font-size: 12px;
}

.article-list,
.cluster-list,
.report-list {
  display: grid;
}

.article-list,
.cluster-list,
.report-list {
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
}

.article-item,
.cluster-item,
.report-item {
  padding: 16px;
  border-bottom: 1px solid #e7efeb;
}

.article-item:last-child,
.cluster-item:last-child,
.report-item:last-child {
  border-bottom: 0;
}

.article-meta span {
  border: 1px solid #c9e1da;
  border-radius: 999px;
  padding: 3px 7px;
  color: #0f5f59;
  background: #f0fbf7;
  font-weight: 700;
}

.article-item h4 {
  margin: 10px 0 7px;
  color: #1e293b;
  font-size: 15px;
  line-height: 1.45;
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.article-item p,
.cluster-item p,
.summary-content > p,
.report-detail p,
.report-detail li span {
  margin: 0;
  color: #52615f;
  font-size: 13px;
  line-height: 1.7;
  overflow-wrap: anywhere;
}

.article-item > p,
.cluster-item > p {
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
}

.article-item > p {
  -webkit-line-clamp: 2;
}

.cluster-item > p {
  -webkit-line-clamp: 3;
}

.article-actions {
  justify-content: flex-start;
  margin-top: 12px;
}

.article-actions button {
  min-height: 34px;
  padding: 5px 9px;
}

.article-actions a,
.summary-sources a {
  color: #0f5f59;
  font-size: 13px;
  font-weight: 700;
  text-decoration: none;
}

.article-actions a:hover,
.summary-sources a:hover {
  text-decoration: underline;
}

.pagination-row {
  padding: 12px 16px;
  border-top: 1px solid #e7efeb;
  color: #64748b;
  font-size: 12px;
}

.pagination-row button {
  min-height: 34px;
  padding: 5px 9px;
}

.topic-filter {
  margin: 14px 16px 0;
}

.topic-filter input {
  min-height: 40px;
  font-size: 13px;
}

.cluster-select {
  width: 100%;
  align-items: flex-start;
  justify-content: flex-start;
  border: 0;
  padding: 0;
  color: #17233a;
  background: transparent;
  text-align: left;
}

.cluster-select > span:last-child {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.cluster-select strong {
  font-size: 14px;
  line-height: 1.4;
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.cluster-count {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  flex: 0 0 30px;
  border-radius: 50%;
  color: #1d4ed8;
  background: #e9f1ff;
  font-size: 12px;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
}

.cluster-item {
  transition: background 0.18s ease, border-color 0.18s ease;
}

.cluster-item:hover,
.cluster-item.selected {
  background: #f3faf7;
}

.cluster-item.selected {
  border-left: 3px solid #0f766e;
  padding-left: 13px;
}

.cluster-item p {
  margin-top: 10px;
}

.intelligence-side {
  display: grid;
  gap: 14px;
}

.summary-panel,
.report-panel {
  min-width: 0;
}

.summary-loading,
.summary-content,
.empty-state {
  padding: 18px 16px;
}

.summary-loading {
  color: #52615f;
  font-size: 13px;
  line-height: 1.6;
}

.summary-content {
  display: grid;
  gap: 14px;
}

.summary-note {
  padding: 10px 11px;
  border-left: 3px solid #c2410c;
  color: #8a421a;
  background: #fff8f1;
  font-size: 12px;
  line-height: 1.55;
}

.summary-sources {
  display: grid;
  gap: 7px;
  padding-top: 12px;
  border-top: 1px solid #e7efeb;
}

.summary-sources > span {
  color: #64748b;
  font-size: 12px;
  font-weight: 700;
}

.empty-state {
  display: grid;
  gap: 7px;
  min-height: 170px;
  place-content: center;
  color: #64748b;
  text-align: center;
}

.empty-state strong {
  color: #334155;
  font-size: 14px;
}

.empty-state span {
  max-width: 270px;
  font-size: 13px;
  line-height: 1.6;
}

.compact-empty {
  min-height: 130px;
}

.report-panel .panel-title select {
  width: auto;
  min-height: 34px;
  padding: 5px 8px;
  font-size: 12px;
}

.report-item > button {
  width: 100%;
  align-items: flex-start;
  border: 0;
  padding: 0;
  color: #0f5f59;
  background: transparent;
  text-align: left;
  font-size: 12px;
  font-weight: 800;
}

.report-item > button > span:first-child {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.report-item strong {
  color: #1e293b;
  font-size: 13px;
  line-height: 1.45;
}

.report-detail {
  display: grid;
  gap: 10px;
  margin-top: 12px;
  padding: 12px;
  border: 1px solid #dce9e4;
  border-radius: 7px;
  background: #f7fbf9;
}

.report-detail ul {
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.report-detail li {
  align-items: flex-start;
  gap: 8px;
}

.report-detail li strong {
  flex: 0 0 74px;
  color: #0f5f59;
}

.loading-list {
  display: grid;
  gap: 12px;
  padding: 18px 16px;
}

.loading-list.compact {
  gap: 9px;
}

.loading-line {
  display: block;
  height: 58px;
  border-radius: 6px;
  background: linear-gradient(90deg, #f0f5f3 25%, #f8fbfa 45%, #f0f5f3 65%);
  background-size: 240% 100%;
  animation: loading-shimmer 1.25s ease infinite;
}

.loading-list.compact .loading-line {
  height: 42px;
}

button:focus-visible,
a:focus-visible {
  outline: 3px solid rgba(15, 118, 110, 0.35);
  outline-offset: 2px;
}

button:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}

@keyframes loading-shimmer {
  to { background-position: -240% 0; }
}

@media (max-width: 1220px) {
  .intelligence-grid {
    grid-template-columns: minmax(0, 1.2fr) minmax(300px, 0.8fr);
  }

  .intelligence-side {
    grid-column: 1 / -1;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  }

}

@media (max-width: 780px) {
  .intelligence-head {
    align-items: flex-start;
    flex-direction: column;
  }

  .intelligence-metrics,
  .intelligence-filter,
  .intelligence-grid,
  .intelligence-side {
    grid-template-columns: 1fr;
  }

  .filter-actions button {
    flex: 1;
  }

  .intelligence-side {
    grid-column: auto;
  }

  .article-panel,
  .cluster-panel,
  .report-panel {
    display: block;
    height: auto;
    min-height: 0;
  }

  .article-list,
  .cluster-list,
  .report-list {
    overflow: visible;
  }
}

@media (max-width: 480px) {
  .intelligence-page {
    padding-inline: 14px;
  }

  .article-meta,
  .pagination-row,
  .report-detail li {
    align-items: flex-start;
    flex-direction: column;
  }

  .report-detail li strong {
    flex-basis: auto;
  }
}

@media (prefers-reduced-motion: reduce) {
  .loading-line {
    animation: none;
  }
}
</style>
