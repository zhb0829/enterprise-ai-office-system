<template>
  <div class="page-shell opinion-sources-page">
    <div class="page-head">
      <div>
        <h2>舆情采集源治理</h2>
        <p class="page-sub">登记公开采集源、录入授权信息、审核启停并监控采集健康状态。只允许公开合规来源。</p>
      </div>
      <div class="head-actions">
        <button class="apply-button head-button" type="button" @click="loadAll">刷新数据</button>
      </div>
    </div>

    <section class="panel">
      <div class="panel-head"><h3>登记采集来源</h3><p class="page-sub">支持网页、RSS/Atom 与公开 API；来源需通过管理员授权审核后才能用于监控。</p></div>
      <form class="source-form" @submit.prevent="createSource">
        <input v-model="form.name" required placeholder="来源名称" aria-label="来源名称" />
        <select v-model="form.sourceType" aria-label="来源类型"><option value="web">网页</option><option value="rss">RSS</option><option value="api">公开 API</option></select>
        <input v-model="form.platform" placeholder="平台(如 新闻/论坛/公众号)" aria-label="平台" />
        <input v-model="form.homepage" required type="url" placeholder="https://..." aria-label="来源主页" />
        <input v-model="form.authSubject" placeholder="授权主体" aria-label="授权主体" />
        <input v-model="form.authScope" placeholder="授权范围" aria-label="授权范围" />
        <input v-model="form.authExpireDate" type="date" aria-label="授权到期日" />
        <select v-model="form.collectMethod" aria-label="采集方式"><option value="http">HTTP GET</option><option value="post">HTTP POST</option></select>
        <input v-model="form.frequency" placeholder="频率(如 daily)" aria-label="采集频率" />
        <input v-model="form.rateLimit" placeholder="限流规则" aria-label="限流规则" />
        <input v-model="form.priority" type="number" placeholder="优先级" aria-label="优先级" />
        <button class="apply-button primary-outline" type="submit" :disabled="saving">{{ saving ? '保存中...' : '登记来源' }}</button>
      </form>
      <p v-if="message" class="page-sub feedback">{{ message }}</p>
    </section>

    <section class="panel">
      <div class="panel-head"><h3>来源配置与授权</h3><span class="count">{{ sources.length }} 个来源</span></div>
      <div class="table-wrap"><table>
        <thead><tr><th>来源</th><th>类型</th><th>授权</th><th>健康</th><th>状态</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="source in sources" :key="source.id">
            <td class="strong">{{ source.name }}<small class="table-note">{{ source.homepage }}</small></td>
            <td>{{ source.sourceType }} · {{ source.frequency || '-' }}</td>
            <td>
              <span :class="['check-badge', auditBadgeClass(source.auditStatus)]">{{ auditLabel(source.auditStatus) }}</span>
              <small class="table-note" v-if="source.authExpire">到期 {{ formatTime(source.authExpire) }}</small>
            </td>
            <td><span :class="['check-badge', healthBadgeClass(source.healthStatus)]">{{ source.healthStatus || 'unknown' }}</span></td>
            <td><span :class="['check-badge', source.status === 'enabled' ? 'ok' : 'warn']">{{ source.status }}</span></td>
            <td class="row-actions">
              <button class="apply-button" type="button" :disabled="source.auditStatus !== 'approved'" @click="runSource(source)">立即采集</button>
              <button class="apply-button" type="button" @click="toggleSource(source)">{{ source.status === 'enabled' ? '停用' : '启用' }}</button>
              <button class="apply-button" type="button" @click="openAudit(source)" :disabled="source.auditStatus === 'rejected'">审核</button>
            </td>
          </tr>
          <tr v-if="!sources.length"><td colspan="6" class="empty-cell">暂无采集来源</td></tr>
        </tbody>
      </table></div>
    </section>

    <div v-if="auditTarget" class="modal-backdrop" @click.self="closeAudit">
      <div class="modal" role="dialog" aria-modal="true" aria-label="来源审核">
        <h3>审核采集来源</h3>
        <p class="page-sub">{{ auditTarget.name }} · {{ auditTarget.homepage }}</p>
        <textarea v-model="auditNote" rows="3" placeholder="审核意见（可通过时可选填）"></textarea>
        <div class="modal-actions">
          <button class="apply-button danger-outline" type="button" @click="submitAudit('rejected')">拒绝</button>
          <button class="apply-button primary-outline" type="button" @click="submitAudit('approved')">通过</button>
          <button class="apply-button" type="button" @click="closeAudit">取消</button>
        </div>
      </div>
    </div>

    <section class="panel">
      <div class="panel-head"><h3>采集任务</h3><button class="apply-button" type="button" @click="loadTasks">刷新任务</button></div>
      <div class="table-wrap"><table>
        <thead><tr><th>任务</th><th>来源</th><th>状态</th><th>新增</th><th>重试</th><th>创建时间</th></tr></thead>
        <tbody><tr v-for="task in tasks" :key="task.id">
          <td>#{{ task.id }}</td><td>{{ task.sourceId }}</td>
          <td><span :class="['check-badge', task.status === 'success' ? 'ok' : task.status === 'failed' ? 'danger' : 'warn']">{{ task.status }}</span></td>
          <td>{{ task.itemsIngested ?? '-' }}</td><td>{{ task.retryCount }}</td><td>{{ formatTime(task.createdAt) }}</td>
        </tr><tr v-if="!tasks.length"><td colspan="6" class="empty-cell">暂无采集任务</td></tr></tbody>
      </table></div>
    </section>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue';
import {
  auditOpinionSource, createOpinionSource, fetchOpinionCollectTasks,
  fetchOpinionSources, runOpinionSource, toggleOpinionSource,
} from '../../api';

const sources = ref([]);
const tasks = ref([]);
const saving = ref(false);
const message = ref('');
const auditTarget = ref(null);
const auditNote = ref('');
const form = reactive({
  name: '', sourceType: 'rss', platform: '', homepage: '', authSubject: '', authScope: '',
  authExpireDate: '', collectMethod: 'http', frequency: 'daily', rateLimit: '', priority: 0,
});

function formatTime(value) {
  if (!value) return '-';
  const raw = String(value).trim();
  const hasTz = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw);
  const date = new Date(hasTz ? raw : `${raw.replace(' ', 'T')}Z`);
  return Number.isNaN(date.getTime()) ? raw : date.toLocaleString();
}
const auditLabel = (value) => ({ approved: '已审核', pending: '待审核', rejected: '已拒绝' }[value] || value);
const auditBadgeClass = (value) => ({ approved: 'ok', pending: 'warn', rejected: 'danger' }[value] || 'warn');
const healthBadgeClass = (value) => ({ healthy: 'ok', degraded: 'warn', paused: 'danger' }[value] || 'warn');
async function loadSources() { sources.value = await fetchOpinionSources(); }
async function loadTasks() { tasks.value = await fetchOpinionCollectTasks(); }
async function loadAll() { try { await Promise.all([loadSources(), loadTasks()]); } catch (e) { message.value = `加载失败：${e.message}`; } }
async function createSource() {
  saving.value = true; message.value = '';
  try {
    await createOpinionSource({
      ...form,
      priority: Number(form.priority) || 0,
      authExpire: form.authExpireDate ? `${form.authExpireDate}T23:59:59` : null,
      status: 'disabled',
    });
    Object.assign(form, { name: '', homepage: '', platform: '', authSubject: '', authScope: '', authExpireDate: '', rateLimit: '', priority: 0 });
    message.value = '来源已登记，等待管理员审核。';
    await loadSources();
  } catch (e) { message.value = `保存失败：${e.message}`; } finally { saving.value = false; }
}
async function runSource(source) {
  try { await runOpinionSource(source.id); message.value = `已触发「${source.name}」采集。`; await loadTasks(); }
  catch (e) { message.value = `触发失败：${e.message}`; }
}
async function toggleSource(source) {
  try { await toggleOpinionSource(source.id); await loadSources(); } catch (e) { message.value = `状态更新失败：${e.message}`; }
}
function openAudit(source) { auditTarget.value = source; auditNote.value = ''; }
function closeAudit() { auditTarget.value = null; }
async function submitAudit(status) {
  try {
    await auditOpinionSource(auditTarget.value.id, { auditStatus: status, auditNote: auditNote.value });
    message.value = status === 'approved' ? '已通过审核。' : '已拒绝来源。';
    closeAudit();
    await loadSources();
  } catch (e) { message.value = `审核失败：${e.message}`; }
}
onMounted(loadAll);
</script>

<style scoped>
.opinion-sources-page { max-width: 1280px; }
.source-form { display: grid; grid-template-columns: 1fr 130px 1fr 1.6fr 1fr 1fr 150px 130px 120px 130px 80px auto; gap: 8px; align-items: center; }
.source-form input, .source-form select { min-height: 38px; font-size: 12px; }
.primary-outline { min-height: 38px; white-space: nowrap; }
.feedback { color: #1d4ed8; }
.table-note { display: block; color: #64748b; font-size: 11px; margin-top: 2px; }
.modal-backdrop { position: fixed; inset: 0; display: grid; place-items: center; background: rgba(15, 23, 42, 0.4); z-index: 30; }
.modal { width: min(480px, 92vw); padding: 20px; border-radius: 10px; background: #fff; box-shadow: 0 20px 40px rgba(0, 0, 0, 0.2); display: grid; gap: 14px; }
.modal h3 { margin: 0; color: #17233a; }
.modal textarea { min-height: 80px; border: 1px solid #cbd5e1; border-radius: 7px; padding: 10px; font-size: 13px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; }
.danger-outline { border-color: #f0b7b2; color: #9f1c16; background: #fff; }
.row-actions button { padding: 6px 8px; font-size: 12px; }
@media (max-width: 1100px) { .source-form { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 700px) { .page-head { align-items: flex-start; flex-direction: column; } .head-button { width: auto; } .source-form { grid-template-columns: 1fr; } }
</style>
