<template>
  <main class="opinion-page" aria-labelledby="reports-title">
    <header class="opinion-head">
      <div>
        <p class="eyebrow">舆情日报 / 周报</p>
        <h2 id="reports-title">舆情报告</h2>
        <p class="opinion-lead">按监控任务生成日报/周报，支持 HTML 在线查看、PDF 导出与人工确认发布；重新生成产生新版本。</p>
      </div>
      <div class="opinion-status" role="status" aria-live="polite">
        <span aria-hidden="true"></span>
        {{ loading ? '同步中' : '报告视图已就绪' }}
      </div>
    </header>

    <div class="monitor-bar">
      <select v-model="monitorId" aria-label="监控任务" @change="loadReports">
        <option :value="null" disabled>选择监控任务</option>
        <option v-for="monitor in monitors" :key="monitor.id" :value="monitor.id">{{ monitor.name }}</option>
      </select>
      <select v-model="period" aria-label="报告周期" @change="loadReports">
        <option value="daily">日报</option>
        <option value="weekly">周报</option>
      </select>
      <button type="button" class="primary-button" :disabled="generating" @click="generateReport">{{ generating ? '生成中...' : '生成报告' }}</button>
      <button type="button" class="ghost-button" @click="loadReports">刷新</button>
    </div>

    <p v-if="error" class="feedback danger" role="alert">{{ error }}</p>

    <section class="panel">
      <div class="panel-title"><h3>报告列表</h3><span class="count">{{ reports.length }} 份</span></div>
      <div v-if="!reports.length" class="empty-cell">暂无报告，点击「生成报告」创建。</div>
      <ul v-else class="report-list">
        <li v-for="report in reports" :key="report.id" class="report-item">
          <button type="button" class="report-select" :aria-expanded="activeReport?.id === report.id" @click="toggleReport(report)">
            <span>
              <strong>{{ report.title }}</strong>
              <small>v{{ report.version }} · {{ report.status }} · {{ report.model || 'rule-based' }} · {{ formatTime(report.createdAt) }}</small>
            </span>
            <span class="report-actions">
              <span :class="['state-badge', report.status === 'published' ? 'ok' : 'warn']">{{ report.status === 'published' ? '已发布' : '草稿' }}</span>
              {{ activeReport?.id === report.id ? '收起' : '查看' }}
            </span>
          </button>
          <div v-if="activeReport?.id === report.id" class="report-detail">
            <p class="report-summary">{{ report.summary }}</p>
            <div class="report-html" v-html="report.contentHtml || '<p>（正文为空）</p>'"></div>
            <div class="report-toolbar">
              <button type="button" v-if="report.status !== 'published'" class="primary-button" :disabled="publishing === report.id" @click="publishReport(report)">{{ publishing === report.id ? '发布中...' : '确认发布' }}</button>
              <button type="button" class="ghost-button" :disabled="exporting === report.id" @click="exportPdf(report)">{{ exporting === report.id ? '导出中...' : '导出 PDF' }}</button>
              <a v-if="pdfUrl" :href="pdfUrl" target="_blank" rel="noreferrer" class="pdf-link">打开导出文件</a>
            </div>
          </div>
        </li>
      </ul>
    </section>
  </main>
</template>

<script setup>
import { onMounted, ref } from 'vue';
import {
  exportOpinionReportPdf, fetchOpinionMonitors, fetchOpinionReports, generateOpinionReport, openFileBlobUrl, publishOpinionReport,
} from '../api';

const monitors = ref([]);
const monitorId = ref(null);
const reports = ref([]);
const period = ref('daily');
const activeReport = ref(null);
const generating = ref(false);
const publishing = ref(null);
const exporting = ref(null);
const pdfUrl = ref('');
const loading = ref(false);
const error = ref('');

const formatTime = (value) => {
  if (!value) return '-';
  const raw = String(value).trim();
  const hasTz = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw);
  const date = new Date(hasTz ? raw : `${raw.replace(' ', 'T')}Z`);
  return Number.isNaN(date.getTime()) ? raw : date.toLocaleString();
};
async function loadAll() {
  error.value = ''; loading.value = true;
  try {
    monitors.value = await fetchOpinionMonitors();
    if (!monitorId.value && monitors.value.length) monitorId.value = monitors.value[0].id;
    await loadReports();
  } catch (e) { error.value = `加载失败：${e.message}`; } finally { loading.value = false; }
}
async function loadReports() {
  if (!monitorId.value) { reports.value = []; return; }
  try {
    reports.value = await fetchOpinionReports({ monitorId: monitorId.value, period: period.value });
  } catch (e) { error.value = `加载报告失败：${e.message}`; }
}
async function generateReport() {
  generating.value = true; error.value = ''; pdfUrl.value = '';
  try {
    const report = await generateOpinionReport(monitorId.value, period.value);
    await loadReports();
    activeReport.value = reports.value.find((item) => item.id === report?.id) || null;
  } catch (e) { error.value = `生成失败：${e.message}`; } finally { generating.value = false; }
}
async function publishReport(report) {
  publishing.value = report.id;
  try { await publishOpinionReport(report.id); await loadReports(); } catch (e) { error.value = `发布失败：${e.message}`; } finally { publishing.value = null; }
}
async function exportPdf(report) {
  exporting.value = report.id; pdfUrl.value = '';
  try {
    const result = await exportOpinionReportPdf(report.id);
    if (!result?.downloadUrl) {
      error.value = result?.error || '导出未返回文件地址';
      return;
    }
    if (pdfUrl.value && pdfUrl.value.startsWith('blob:')) {
      URL.revokeObjectURL(pdfUrl.value);
    }
    pdfUrl.value = await openFileBlobUrl(result.downloadUrl);
  } catch (e) { error.value = `导出失败：${e.message}`; } finally { exporting.value = null; }
}
function toggleReport(report) { activeReport.value = activeReport.value?.id === report.id ? null : report; }
onMounted(loadAll);
</script>

<style scoped>
.opinion-page { max-width: 1100px; margin: 0 auto; padding: clamp(24px, 4vw, 48px) clamp(16px, 4vw, 40px) 72px; color: #17233a; }
.opinion-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 12px; padding: 10px 0 24px; border-bottom: 1px solid #d7e4df; }
.opinion-head h2 { margin: 0; color: #112927; font-size: clamp(2rem, 4vw, 3rem); line-height: 1.08; }
.opinion-lead { max-width: 720px; margin: 14px 0 0; color: #52615f; line-height: 1.75; }
.opinion-status { display: inline-flex; align-items: center; gap: 8px; border: 1px solid #b9ddd3; border-radius: 999px; padding: 8px 11px; color: #0f5f59; background: #f0fbf7; font-size: 13px; font-weight: 700; }
.opinion-status span { width: 8px; height: 8px; border-radius: 50%; background: #0f9f6e; }
.monitor-bar { display: flex; gap: 10px; margin: 18px 0; flex-wrap: wrap; }
.monitor-bar select { min-height: 38px; border: 1px solid #cbd5e1; border-radius: 6px; padding: 7px 9px; font-size: 13px; min-width: 220px; }
.panel { border: 1px solid rgba(37, 67, 63, 0.15); border-radius: 8px; background: rgba(255, 255, 255, 0.9); overflow: hidden; }
.panel-title { display: flex; align-items: center; justify-content: space-between; padding: 14px 16px; border-bottom: 1px solid #e1ebe7; background: #fbfdfc; }
.panel-title h3 { margin: 0; font-size: 16px; }
.count, .report-select small { color: #64748b; font-size: 12px; }
.empty-cell { padding: 20px 16px; color: #64748b; font-size: 13px; text-align: center; }
.report-list { display: grid; }
.report-item { border-bottom: 1px solid #e7efeb; }
.report-select { width: 100%; display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 16px; border: 0; background: transparent; text-align: left; }
.report-select > span:first-child { display: grid; gap: 4px; min-width: 0; }
.report-select strong { font-size: 14px; }
.report-actions { display: inline-flex; align-items: center; gap: 10px; color: #0f5f59; font-size: 13px; font-weight: 800; flex: 0 0 auto; }
.state-badge { border-radius: 999px; padding: 3px 9px; font-size: 12px; font-weight: 800; }
.state-badge.ok { color: #0f5f59; background: #f0fbf7; border: 1px solid #9bd0c1; }
.state-badge.warn { color: #92400e; background: #fff7ed; border: 1px solid #f0c98a; }
.report-detail { display: grid; gap: 12px; margin: 0 12px 12px; padding: 12px; border: 1px solid #dce9e4; border-radius: 7px; background: #f7fbf9; }
.report-summary { margin: 0; color: #334155; font-size: 14px; line-height: 1.7; }
.report-html { color: #1e293b; font-size: 13px; line-height: 1.75; }
.report-html :deep(h3), .report-html :deep(h4) { color: #112927; margin: 12px 0 6px; }
.report-html :deep(ul) { margin: 4px 0; padding-left: 20px; }
.report-html :deep(a) { color: #0f5f59; }
.report-toolbar { display: flex; align-items: center; gap: 8px; padding-top: 10px; border-top: 1px solid #e1ebe7; flex-wrap: wrap; }
.report-toolbar button, .primary-button, .ghost-button { min-height: 32px; border-radius: 6px; padding: 5px 10px; font-size: 12px; font-weight: 700; }
.primary-button { border: 1px solid #112927; color: #fff; background: #112927; }
.ghost-button { border: 1px solid #b8d3cb; color: #0f5f59; background: #fff; }
.pdf-link { color: #0f5f59; font-size: 13px; font-weight: 700; text-decoration: none; }
.feedback { padding: 9px 13px; border-radius: 7px; font-size: 12px; margin: 10px 0; color: #9f1c16; background: #fff5f4; border: 1px solid #f0b7b2; }
@media (max-width: 620px) { .opinion-head { flex-direction: column; align-items: flex-start; } .report-select { flex-direction: column; align-items: flex-start; } }
</style>