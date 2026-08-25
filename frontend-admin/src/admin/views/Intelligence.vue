<template>
  <div class="page-shell intelligence-page">
    <div class="page-head">
      <div>
        <h2>行业与竞品情报</h2>
        <p class="page-sub">配置公开来源，查看采集健康状态、任务执行和已生成简报。</p>
      </div>
      <div class="head-actions">
        <button class="apply-button" type="button" :disabled="generating" @click="generateReport">{{ generating ? '生成中...' : '生成日报' }}</button>
        <button class="primary-button head-button" type="button" @click="loadAll">刷新数据</button>
      </div>
    </div>

    <section class="panel">
      <div class="panel-head"><h3>新增采集来源</h3><p class="page-sub">支持网页、RSS/Atom 和公开 API，关键词为空表示不过滤。</p></div>
      <form class="source-form" @submit.prevent="createSource">
        <input v-model="form.name" required placeholder="来源名称" aria-label="来源名称" />
        <select v-model="form.type" aria-label="来源类型"><option value="web">网页</option><option value="rss">RSS</option><option value="api">公开 API</option></select>
        <input v-model="form.url" required type="url" placeholder="https://..." aria-label="来源 URL" />
        <input v-model="form.keywords" placeholder="关键词，逗号分隔" aria-label="关键词" />
        <input v-model="form.competitors" placeholder="竞品，逗号分隔" aria-label="竞品" />
        <select v-model="form.frequency" aria-label="采集频率"><option value="hourly">每小时</option><option value="daily">每日</option><option value="weekly">每周</option><option value="manual">手动</option></select>
        <button class="apply-button primary-outline" type="submit" :disabled="saving">{{ saving ? '保存中...' : '添加来源' }}</button>
      </form>
      <p v-if="message" class="page-sub feedback">{{ message }}</p>
    </section>

    <section class="panel">
      <div class="panel-head"><h3>来源配置</h3><span class="count">{{ sources.length }} 个来源</span></div>
      <div class="table-wrap"><table>
        <thead><tr><th>来源</th><th>类型</th><th>频率</th><th>健康</th><th>最近采集</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="source in sources" :key="source.id">
            <td class="strong">{{ source.name }}<small class="table-note">{{ source.url }}</small></td>
            <td>{{ typeLabel(source.type) }}</td><td>{{ frequencyLabel(source.frequency) }}</td>
            <td><span :class="['check-badge', source.healthStatus === 'healthy' ? 'ok' : source.healthStatus === 'paused' ? 'danger' : 'warn']">{{ source.healthStatus || 'unknown' }}</span></td>
            <td>{{ formatTime(source.lastRunAt) }}</td>
            <td class="row-actions"><button class="apply-button" type="button" @click="runSource(source)">立即采集</button><button class="apply-button" type="button" @click="toggleSource(source)">{{ source.status === 'enabled' ? '暂停' : '启用' }}</button></td>
          </tr>
          <tr v-if="!sources.length"><td colspan="6" class="empty-cell">暂无采集来源</td></tr>
        </tbody>
      </table></div>
    </section>

    <section class="panel">
      <div class="panel-head"><h3>采集任务</h3><button class="apply-button" type="button" @click="refreshTasksAndSources">刷新任务</button></div>
      <div class="table-wrap"><table>
        <thead><tr><th>任务</th><th>来源 ID</th><th>状态</th><th>新增条目</th><th>重试次数</th><th>创建时间</th><th>操作</th></tr></thead>
        <tbody><tr v-for="task in tasks" :key="task.id"><td>#{{ task.id }}</td><td>{{ task.sourceId }}</td><td><span :class="['check-badge', task.status === 'success' ? 'ok' : task.status === 'failed' ? 'danger' : 'warn']">{{ task.status }}</span></td><td>{{ task.itemsCount }}</td><td>{{ task.retryCount }}</td><td>{{ formatTime(task.createdAt) }}</td><td><button v-if="task.status === 'failed'" class="apply-button" type="button" @click="retryTask(task)">重试</button><span v-else class="table-note">-</span></td></tr><tr v-if="!tasks.length"><td colspan="7" class="empty-cell">暂无采集任务</td></tr></tbody>
      </table></div>
    </section>

    <section class="panel">
      <div class="panel-head"><h3>情报简报</h3><span class="count">{{ reports.length }} 份</span></div>
      <div class="report-list">
        <article v-for="report in reports" :key="report.id" class="report-item">
          <button type="button" class="report-toggle" :aria-expanded="activeReport?.id === report.id" @click="toggleReport(report)">
            <span>
              <strong>{{ report.title }}</strong>
              <small>{{ report.trend?.articleCount || 0 }} 条情报 · {{ report.trend?.clusterCount || 0 }} 个主题 · {{ formatTime(report.generatedAt) }}</small>
            </span>
            <span class="report-toggle-actions"><span class="check-badge ok">{{ report.period }}</span>{{ activeReport?.id === report.id ? '收起' : '查看' }}</span>
          </button>
          <div v-if="activeReport?.id === report.id" class="report-detail">
            <p>生成时间：{{ formatTime(report.generatedAt) }}。覆盖 {{ report.trend?.articleCount || 0 }} 条情报、{{ report.trend?.clusterCount || 0 }} 个主题。</p>
            <ul v-if="report.items?.length">
              <li v-for="item in report.items" :key="item.clusterId || item.topic">
                <strong>{{ item.topic }}</strong>
                <span>{{ item.summary || '暂无主题摘要。' }}</span>
              </li>
            </ul>
            <p v-else>该简报暂无可展示的主题摘要。</p>
            <div v-if="reportSources(report).length" class="report-sources">
              <span>引用来源</span>
              <a v-for="source in reportSources(report)" :key="source.articleId || source.url" :href="source.url" target="_blank" rel="noreferrer">{{ source.title || source.sourceName || source.url }}</a>
            </div>
          </div>
        </article>
        <p v-if="!reports.length" class="empty-cell">暂无简报，请先完成采集。</p>
      </div>
    </section>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue';
import { createIntelligenceSource, fetchIntelligenceReports, fetchIntelligenceSources, fetchIntelligenceTasks, generateIntelligenceReport, retryIntelligenceTask, runIntelligenceSource, toggleIntelligenceSource } from '../../api';

const sources = ref([]); const tasks = ref([]); const reports = ref([]); const saving = ref(false); const generating = ref(false); const message = ref(''); const activeReport = ref(null);
const form = reactive({ name: '', type: 'rss', url: '', keywords: '', competitors: '', frequency: 'daily' });
const split = (value) => value.split(',').map((item) => item.trim()).filter(Boolean);
function formatTime(value) {
  if (!value) return '-';
  const raw = String(value).trim();
  const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw);
  const date = new Date(hasTimezone ? raw : `${raw.replace(' ', 'T')}Z`);
  return Number.isNaN(date.getTime()) ? raw : date.toLocaleString();
}
const typeLabel = (value) => ({ web: '网页', rss: 'RSS', api: 'API' }[value] || value);
const frequencyLabel = (value) => ({ hourly: '每小时', daily: '每日', weekly: '每周', manual: '手动' }[value] || value);
async function loadSources() { sources.value = await fetchIntelligenceSources(); }
async function loadTasks() { tasks.value = await fetchIntelligenceTasks(); }
async function loadReports() {
  const activeId = activeReport.value?.id;
  reports.value = await fetchIntelligenceReports();
  activeReport.value = reports.value.find((report) => report.id === activeId) || null;
}
async function loadAll() { try { await Promise.all([loadSources(), loadTasks(), loadReports()]); } catch (error) { message.value = `加载失败：${error.message}`; } }
async function refreshTasksAndSources() { await Promise.all([loadSources(), loadTasks()]); }
async function createSource() { saving.value = true; message.value = ''; try { await createIntelligenceSource({ ...form, keywords: split(form.keywords), competitors: split(form.competitors) }); Object.assign(form, { name: '', url: '', keywords: '', competitors: '' }); message.value = '采集来源已保存。'; await loadSources(); } catch (error) { message.value = `保存失败：${error.message}`; } finally { saving.value = false; } }
async function generateReport() {
  generating.value = true;
  message.value = '';
  try {
    const generatedReport = await generateIntelligenceReport();
    message.value = '日报已生成。';
    await loadReports();
    activeReport.value = reports.value.find((report) => report.id === generatedReport?.id) || null;
  } catch (error) {
    message.value = `生成失败：${error.message}`;
  } finally {
    generating.value = false;
  }
}
async function runSource(source) { try { await runIntelligenceSource(source.id); message.value = `已触发「${source.name}」采集。`; await refreshTasksAndSources(); } catch (error) { message.value = `触发失败：${error.message}`; } }
async function toggleSource(source) { try { await toggleIntelligenceSource(source.id); await loadSources(); } catch (error) { message.value = `状态更新失败：${error.message}`; } }
async function retryTask(task) { try { await retryIntelligenceTask(task.id); message.value = `任务 #${task.id} 已重新排队。`; await refreshTasksAndSources(); } catch (error) { message.value = `重试失败：${error.message}`; } }
function reportSources(report) {
  const unique = new Map();
  (report.sources || []).forEach((source) => {
    if (source?.url && !unique.has(source.url)) unique.set(source.url, source);
  });
  return [...unique.values()];
}
function toggleReport(report) { activeReport.value = activeReport.value?.id === report.id ? null : report; }
onMounted(loadAll);
</script>

<style scoped>
.intelligence-page { max-width: 1280px; }
.panel-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
.panel-head h3 { margin: 0; }
.count { color: #64748b; font-size: 13px; }
.head-actions { display: flex; align-items: center; gap: 8px; }
.head-button { width: auto; padding: 9px 14px; }
.source-form { display: grid; grid-template-columns: 1fr 120px 2fr 1.2fr 1.2fr 120px auto; gap: 8px; align-items: center; }
.source-form input, .source-form select { min-height: 40px; }
.primary-outline { min-height: 40px; white-space: nowrap; }
.feedback { color: #1d4ed8; }
.report-list { display: grid; gap: 8px; }
.report-item { border: 1px solid #e1e7ef; border-radius: 8px; background: #fbfcfe; overflow: hidden; }
.report-toggle { width: 100%; display: flex; align-items: center; justify-content: space-between; gap: 16px; border: 0; padding: 12px; color: #17233a; background: transparent; text-align: left; }
.report-toggle:hover { background: #f5f8fc; }
.report-toggle:focus-visible { outline: 3px solid rgba(29, 78, 216, 0.32); outline-offset: -3px; }
.report-toggle > span:first-child { display: grid; gap: 5px; min-width: 0; }
.report-toggle small { color: #64748b; font-size: 12px; }
.report-toggle-actions { display: inline-flex; align-items: center; gap: 10px; flex: 0 0 auto; color: #1d4ed8; font-size: 13px; font-weight: 700; }
.report-detail { display: grid; gap: 10px; margin: 0 12px 12px; padding: 12px; border: 1px solid #dce9e4; border-radius: 7px; background: #f7fbf9; }
.report-detail p, .report-detail li span { margin: 0; color: #52615f; font-size: 13px; line-height: 1.65; overflow-wrap: anywhere; }
.report-detail ul { display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }
.report-detail li { display: grid; gap: 3px; }
.report-detail li strong { color: #0f5f59; font-size: 13px; }
.report-sources { display: grid; gap: 6px; padding-top: 10px; border-top: 1px solid #dce9e4; }
.report-sources > span { color: #64748b; font-size: 12px; font-weight: 700; }
.report-sources a { color: #0f5f59; font-size: 13px; font-weight: 700; overflow-wrap: anywhere; text-decoration: none; }
.report-sources a:hover { text-decoration: underline; }
@media (max-width: 700px) { .report-toggle { align-items: flex-start; flex-direction: column; } .report-toggle-actions { width: 100%; justify-content: space-between; } }
@media (max-width: 1100px) { .source-form { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 700px) { .page-head, .head-actions { align-items: flex-start; flex-direction: column; } .source-form { grid-template-columns: 1fr; } .head-button { width: auto; } }
</style>
