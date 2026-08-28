<template>
  <section class="page-shell">
    <header class="page-head">
      <div>
        <h2>资质编制任务</h2>
        <p class="page-sub">查看并管理企业端的资质编制任务：归档、恢复、编辑、重试与解锁，变更会同步到用户端。</p>
      </div>
      <button class="primary-button" type="button" :disabled="loading" @click="loadTasks">
        {{ loading ? '刷新中…' : '刷新任务' }}
      </button>
    </header>

    <section class="panel filter-bar">
      <label class="field">
        <span>企业</span>
        <select v-model="filters.owner">
          <option value="">全部企业</option>
          <option v-for="item in enterprises" :key="item.ownerKey" :value="item.ownerKey">
            {{ item.nickname || item.username }}（{{ item.ownerKey }}）
          </option>
        </select>
      </label>
      <label class="field">
        <span>状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="(label, key) in statusLabels" :key="key" :value="key">{{ label }}</option>
        </select>
      </label>
      <button class="ghost-button filter-apply" type="button" :disabled="loading" @click="loadTasks">应用筛选</button>
    </section>

    <p v-if="errorMessage" class="error-text" role="alert">{{ errorMessage }}</p>

    <section class="panel">
      <div v-if="!tasks.length && !loading" class="empty-state">暂无符合条件的编制任务。</div>
      <div v-else class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>企业</th>
              <th>资质类型</th>
              <th>指南版本</th>
              <th>文档类型</th>
              <th>状态</th>
              <th>进度</th>
              <th>更新时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="task in tasks" :key="task.id">
              <td>{{ task.ownerName }}</td>
              <td>{{ task.qualificationType }}</td>
              <td>{{ task.guideVersion || '-' }}</td>
              <td>{{ task.documentType }}</td>
              <td>
                <span :class="['status-pill', { online: task.status === 'READY_REVIEW', archived: task.status === 'ARCHIVED' }]">
                  <span></span>{{ statusLabels[task.status] || task.status }}
                </span>
                <small v-if="task.status === 'ARCHIVED' && task.preArchiveStatus" class="archive-from">
                  归档前：{{ statusLabels[task.preArchiveStatus] || task.preArchiveStatus }}
                </small>
              </td>
              <td>{{ task.progress || 0 }}%</td>
              <td>{{ formatTime(task.updatedAt) }}</td>
              <td class="action-cell">
                <button class="ghost-button" type="button" @click="openDetail(task)">详情</button>
                <button v-if="task.status === 'FAILED'" class="ghost-button" type="button" @click="openEdit(task)">编辑</button>
                <button v-if="task.status === 'FAILED'" class="ghost-button" type="button" @click="retryTask(task)">重试</button>
                <button v-if="canArchive(task)" class="ghost-button danger" type="button" @click="archiveTask(task)">归档</button>
                <button v-if="task.status === 'ARCHIVED'" class="ghost-button" type="button" @click="restoreTask(task)">恢复</button>
                <button v-if="task.documentStatus === 'LOCKED'" class="ghost-button danger" type="button" @click="unlockDocument(task)">解锁文档</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section v-if="editing" class="panel editor-panel">
      <div class="page-head">
        <div>
          <h3>编辑失败任务</h3>
          <p class="page-sub">修正文档类型、字数要求或企业档案后，可再次触发重试。</p>
        </div>
        <button class="ghost-button" type="button" @click="editing = null">取消</button>
      </div>
      <div class="editor-grid">
        <label class="field">
          <span>输出文档类型</span>
          <select v-model="editing.documentType">
            <option>资质申报材料初稿</option>
            <option>服务指南</option>
            <option>操作手册</option>
          </select>
        </label>
        <label class="field">
          <span>正文最大字数（0 为不限制）</span>
          <input v-model.number="editing.maxChars" type="number" min="0" step="100" />
        </label>
      </div>
      <div class="material-picker">
        <p class="picker-title">关联企业档案（{{ editing.materialIds.length }} 已选）</p>
        <label v-for="item in ownerMaterials" :key="item.id" class="material-row">
          <input v-model="editing.materialIds" type="checkbox" :value="item.id" />
          <span>{{ item.fileName }}（{{ item.textLength || 0 }} 字）</span>
        </label>
        <p v-if="!ownerMaterials.length" class="empty-state">该企业暂无资质档案。</p>
      </div>
      <div class="modal-actions">
        <button class="primary-button small-primary" type="button" :disabled="saving" @click="saveEdit">
          {{ saving ? '保存中…' : '保存修改' }}
        </button>
      </div>
    </section>

    <section v-if="detail" class="panel detail-panel">
      <div class="page-head">
        <div>
          <h3>任务详情（只读）</h3>
          <p class="page-sub">{{ detail.task.qualificationType }} · {{ detail.task.documentType }} · {{ detail.task.ownerName }}</p>
        </div>
        <button class="ghost-button" type="button" @click="detail = null">关闭</button>
      </div>

      <div class="detail-meta">
        <span>状态：{{ statusLabels[detail.task.status] || detail.task.status }}</span>
        <span v-if="detail.task.failureReason">失败原因：{{ detail.task.failureReason }}</span>
        <span v-if="detail.document">文档：{{ detail.document.title }}（{{ detail.document.status }}）</span>
      </div>

      <template v-if="detail.document">
        <h4 class="detail-subtitle">校验报告</h4>
        <div class="report-summary">
          {{ reportSummaryText }}
        </div>
        <div class="report-items">
          <div v-for="(item, index) in reportItems" :key="index" :class="['report-item', item.status === 'PASS' ? 'pass' : 'fail']">
            <span>{{ item.status === 'PASS' ? '✓' : '!' }}</span>
            <p>{{ item.code }}：{{ item.message }}</p>
          </div>
        </div>

        <h4 class="detail-subtitle">章节内容</h4>
        <article v-for="(section, index) in documentSections" :key="index" class="doc-section">
          <h5>{{ index + 1 }}. {{ section.title || '未命名章节' }}</h5>
          <p v-for="(block, bIndex) in section.blocks || []" :key="bIndex">{{ block.text }}</p>
        </article>

        <h4 class="detail-subtitle">引用来源（{{ (detail.document.sources || []).length }}）</h4>
        <ul class="source-list">
          <li v-for="source in detail.document.sources || []" :key="source.id">
            {{ source.docTitle || '未命名来源' }}（score {{ source.score ?? '-' }}）
          </li>
        </ul>

        <h4 class="detail-subtitle">版本历史（{{ (detail.versions || []).length }}）</h4>
        <ul class="version-list">
          <li v-for="version in detail.versions || []" :key="version.id">
            v{{ version.version }} · {{ version.changeNote || '无变更说明' }} · {{ formatTime(version.createdAt) }}
          </li>
        </ul>
      </template>
      <p v-else class="empty-state">该任务尚未生成文档。</p>
    </section>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import {
  archiveAdminQualTask,
  fetchAdminEnterprises,
  fetchAdminOwnerMaterials,
  fetchAdminQualTaskDetail,
  fetchAdminQualTasks,
  restoreAdminQualTask,
  retryAdminQualTask,
  unlockAdminQualDocument,
  updateAdminQualTask,
} from '../../api';

const statusLabels = {
  CREATED: '已创建',
  PARSING: '解析中',
  GENERATING: '生成中',
  VALIDATING: '校验中',
  READY_REVIEW: '待审核/待导出',
  FAILED: '失败',
  ARCHIVED: '已归档',
};

const tasks = ref([]);
const enterprises = ref([]);
const ownerMaterials = ref([]);
const filters = reactive({ owner: '', status: '' });
const loading = ref(false);
const saving = ref(false);
const errorMessage = ref('');
const editing = ref(null);
const detail = ref(null);

const documentSections = computed(() => detail.value?.document?.content?.sections || []);
const reportItems = computed(() => detail.value?.reports?.[0]?.items || []);
const reportSummaryText = computed(() => {
  const summary = detail.value?.reports?.[0]?.summary;
  if (!summary) return '尚未生成校验报告。';
  return summary.passed ? `校验通过，共 ${summary.total} 项。` : `校验未通过：${summary.failed}/${summary.total} 项失败。`;
});

function formatTime(value) {
  if (!value) return '-';
  return new Date(value).toLocaleString('zh-CN', { dateStyle: 'short', timeStyle: 'short' });
}

function canArchive(task) {
  return ['CREATED', 'READY_REVIEW', 'FAILED'].includes(task.status);
}

async function loadEnterprises() {
  try {
    const data = await fetchAdminEnterprises();
    enterprises.value = Array.isArray(data) ? data : [];
  } catch (error) {
    errorMessage.value = error.message;
  }
}

async function loadTasks() {
  loading.value = true;
  errorMessage.value = '';
  try {
    const data = await fetchAdminQualTasks({ owner: filters.owner, status: filters.status });
    tasks.value = Array.isArray(data) ? data : [];
  } catch (error) {
    errorMessage.value = error.message;
  } finally {
    loading.value = false;
  }
}

async function openDetail(task) {
  errorMessage.value = '';
  try {
    detail.value = await fetchAdminQualTaskDetail(task.id);
  } catch (error) {
    errorMessage.value = error.message;
  }
}

async function openEdit(task) {
  errorMessage.value = '';
  try {
    const materials = await fetchAdminOwnerMaterials(task.ownerEnterpriseId);
    ownerMaterials.value = Array.isArray(materials) ? materials : [];
    editing.value = {
      id: task.id,
      documentType: task.documentType,
      maxChars: task.formatRequirements?.maxChars || 0,
      materialIds: [...(task.materialIds || [])],
    };
  } catch (error) {
    errorMessage.value = error.message;
  }
}

async function saveEdit() {
  if (!editing.value) return;
  saving.value = true;
  errorMessage.value = '';
  try {
    await updateAdminQualTask(editing.value.id, {
      documentType: editing.value.documentType,
      maxChars: editing.value.maxChars,
      materialIds: editing.value.materialIds,
    });
    editing.value = null;
    await loadTasks();
  } catch (error) {
    errorMessage.value = error.message;
  } finally {
    saving.value = false;
  }
}

async function confirmAction(message, action) {
  if (!window.confirm(message)) return false;
  errorMessage.value = '';
  try {
    await action();
    await loadTasks();
    return true;
  } catch (error) {
    errorMessage.value = error.message;
    return false;
  }
}

function archiveTask(task) {
  return confirmAction(`确认归档该任务？归档后用户端将不再显示，可随时恢复。`, () => archiveAdminQualTask(task.id));
}

function restoreTask(task) {
  return confirmAction('确认恢复该任务到归档前状态？', () => restoreAdminQualTask(task.id));
}

function retryTask(task) {
  return confirmAction('确认重试该失败任务？任务将重新进入生成流程。', () => retryAdminQualTask(task.id));
}

function unlockDocument(task) {
  return confirmAction('确认解锁已归档导出的文档？解锁后文档回到 APPROVED，用户可再次编辑导出。', () => unlockAdminQualDocument(task.documentId));
}

onMounted(async () => {
  await Promise.all([loadEnterprises(), loadTasks()]);
});
</script>

<style scoped>
.primary-button {
  width: auto;
  min-height: 38px;
  padding: 8px 14px;
  border: 0;
  border-radius: 8px;
  background: #1f6feb;
  color: #fff;
  font-weight: 700;
}

.small-primary {
  min-width: 110px;
}

.ghost-button {
  min-height: 34px;
  padding: 6px 10px;
  border: 1px solid #cfd6e3;
  border-radius: 8px;
  background: #fff;
  color: #1f4f9f;
  font-weight: 700;
}

.ghost-button.danger {
  color: #b42318;
  border-color: #ecc4bf;
}

.filter-bar {
  display: flex;
  align-items: end;
  gap: 14px;
  flex-wrap: wrap;
}

.filter-bar .field {
  min-width: 220px;
}

.filter-apply {
  min-height: 38px;
}

.field {
  display: grid;
  gap: 7px;
  color: #263a37;
  font-size: 13px;
  font-weight: 700;
}

.field select,
.field input {
  width: 100%;
  min-height: 38px;
  border: 1px solid #d6dce6;
  border-radius: 7px;
  padding: 8px 10px;
  color: #17233a;
  background: #fff;
}

.empty-state {
  padding: 28px 12px;
  color: #64748b;
  text-align: center;
}

.status-pill.archived {
  background: #eef1f6;
  color: #64748b;
}

.archive-from {
  display: block;
  margin-top: 4px;
  color: #94a3b8;
  font-size: 11px;
}

.action-cell {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.editor-panel,
.detail-panel {
  display: grid;
  gap: 16px;
}

.editor-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.material-picker {
  display: grid;
  gap: 8px;
}

.picker-title {
  margin: 0;
  color: #475569;
  font-size: 13px;
  font-weight: 700;
}

.material-row {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 8px 10px;
  border: 1px solid #e2e8f0;
  border-radius: 7px;
  font-size: 13px;
  color: #17233a;
}

.detail-meta {
  display: flex;
  gap: 18px;
  flex-wrap: wrap;
  color: #475569;
  font-size: 13px;
}

.detail-subtitle {
  margin: 8px 0 0;
  padding-top: 12px;
  border-top: 1px solid #e2e8f0;
  font-size: 14px;
  color: #17233a;
}

.report-summary {
  color: #475569;
  font-size: 13px;
}

.report-items {
  display: grid;
  gap: 6px;
}

.report-item {
  display: flex;
  gap: 8px;
  align-items: start;
  font-size: 12px;
  color: #475569;
}

.report-item.pass span {
  color: #16803c;
}

.report-item.fail span {
  color: #b42318;
  font-weight: 800;
}

.report-item p {
  margin: 0;
}

.doc-section {
  padding: 10px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}

.doc-section h5 {
  margin: 0 0 6px;
  color: #17233a;
}

.doc-section p {
  margin: 4px 0;
  color: #475569;
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
}

.source-list,
.version-list {
  margin: 0;
  padding-left: 18px;
  color: #475569;
  font-size: 13px;
  line-height: 1.8;
}

@media (max-width: 800px) {
  .editor-grid {
    grid-template-columns: 1fr;
  }
}
</style>
