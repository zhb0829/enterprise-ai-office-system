<template>
  <main class="qual-page">
    <section class="qual-hero">
      <div>
        <p class="eyebrow">资质与服务指南智能编制</p>
        <h2>把官方要求，整理成可审核的工作底稿。</h2>
        <p class="qual-lead">
          先锁定指南版本，再引用企业资质档案生成初稿。系统保留来源、校验报告和版本变化，
          初稿必须经人工审核后才能导出正式 DOCX。
        </p>
      </div>
      <div class="qual-guard">
        <span class="qual-guard-dot"></span>
        <div>
          <strong>边界模式已启用</strong>
          <small>仅使用已上传来源，不替代正式申报判断</small>
        </div>
      </div>
    </section>

    <section class="qual-layout">
      <aside class="qual-sidebar" aria-label="资质编制任务">
        <div class="qual-sidebar-head">
          <div>
            <p class="eyebrow">我的任务</p>
            <h3>编制工作台</h3>
          </div>
          <button class="qual-icon-button" type="button" title="刷新任务" aria-label="刷新任务" @click="loadAll">
            ↻
          </button>
        </div>

        <button class="qual-new-task" type="button" @click="startNewTask">
          <span aria-hidden="true">＋</span>
          新建编制任务
        </button>

        <div v-if="tasks.length" class="qual-task-list">
          <button
            v-for="item in tasks"
            :key="item.id"
            type="button"
            :class="['qual-task-item', { active: selectedTask?.id === item.id }]"
            @click="selectTask(item.id)"
          >
            <span class="qual-task-title">{{ item.qualificationType }}</span>
            <span class="qual-task-meta">{{ item.guideVersion || '指南版本待确认' }} · {{ statusLabel(item.status) }}</span>
            <span class="qual-task-progress"><i :style="{ width: `${item.progress || 0}%` }"></i></span>
          </button>
        </div>
        <div v-else class="qual-empty-sidebar">
          <strong>还没有编制任务</strong>
          <span>上传一份官方指南开始。</span>
        </div>
      </aside>

      <section class="qual-main">
        <div v-if="notice" class="qual-notice" :class="noticeType" role="status">{{ notice }}</div>

        <section v-if="view === 'setup'" class="qual-setup">
          <div class="qual-section-head">
            <div>
              <p class="eyebrow">三步准备</p>
              <h3>建立一份有依据的编制任务</h3>
            </div>
            <span class="qual-step-count">STEP {{ setupStep }} / 3</span>
          </div>

          <div class="qual-steps" aria-label="任务创建步骤">
            <button
              v-for="step in steps"
              :key="step.id"
              type="button"
              :class="{ active: setupStep === step.id, done: setupStep > step.id }"
              @click="setupStep = step.id"
            >
              <span>{{ setupStep > step.id ? '✓' : step.id }}</span>
              {{ step.label }}
            </button>
          </div>

          <form v-if="setupStep === 1" class="qual-form" @submit.prevent="parseGuide">
            <div class="qual-form-grid">
              <label class="qual-field">
                <span>资质类型</span>
                <input v-model.trim="form.qualificationType" required placeholder="例如：高新技术企业认定" />
              </label>
              <label class="qual-field">
                <span>指南名称</span>
                <input v-model.trim="form.guideName" required placeholder="例如：2026 年申报指南" />
              </label>
              <label class="qual-field">
                <span>指南版本</span>
                <input v-model.trim="form.version" required placeholder="例如：2026-v1" />
              </label>
              <label class="qual-field">
                <span>官方来源链接 <em>可选</em></span>
                <input v-model.trim="form.sourceUrl" type="url" placeholder="https://..." />
              </label>
            </div>
            <label class="qual-upload">
              <input type="file" accept=".pdf,.docx,.txt,.md" @change="guideFile = $event.target.files?.[0] || null" />
              <span class="qual-upload-icon" aria-hidden="true">↑</span>
              <strong>{{ guideFile?.name || '选择官方指南文件' }}</strong>
              <small>支持原生文字版 PDF、Word、TXT、Markdown；扫描件 OCR 暂不启用</small>
            </label>
            <div class="qual-actions">
              <button class="primary-button" type="submit" :disabled="!guideFile || !form.qualificationType || !form.guideName">
                解析指南并继续
              </button>
            </div>
          </form>

          <form v-else-if="setupStep === 2" class="qual-form" @submit.prevent="setupStep = 3">
            <div v-if="currentGuide" class="qual-guide-summary">
              <div>
                <span class="qual-kicker">已锁定指南解析结果</span>
                <strong>{{ currentGuide.guideName }} · {{ currentGuide.version }}</strong>
                <small>{{ currentGuide.schema?.sections?.length || 0 }} 个章节 · {{ currentGuide.materialChecklist?.length || 0 }} 项材料要求</small>
              </div>
              <span class="qual-status ok">ACTIVE</span>
            </div>
            <div v-else class="qual-guide-picker">
              <label class="qual-field">
                <span>选择已解析指南</span>
                <select v-model="form.guideSchemaId" required @change="syncGuide">
                  <option value="" disabled>请选择指南版本</option>
                  <option v-for="guide in guides" :key="guide.id" :value="guide.id">
                    {{ guide.qualificationType }} · {{ guide.guideName }} · {{ guide.version }}
                  </option>
                </select>
              </label>
              <p v-if="!guides.length" class="qual-muted">还没有已解析指南，请返回上一步上传。</p>
            </div>

            <div class="qual-checklist">
              <div class="qual-subhead">
                <div>
                  <span class="qual-kicker">材料清单</span>
                  <strong>生成只会引用你选择的企业档案</strong>
                </div>
                <span>{{ selectedMaterialIds.length }} 已选择</span>
              </div>
              <div v-if="materials.length" class="qual-material-list">
                <label v-for="material in materials" :key="material.id" class="qual-material-row">
                  <input v-model="selectedMaterialIds" type="checkbox" :value="material.id" />
                  <span>
                    <strong>{{ material.fileName }}</strong>
                    <small>{{ material.textLength || 0 }} 字 · {{ material.parseStatus }}</small>
                  </span>
                </label>
              </div>
              <div v-else class="qual-inline-empty">服务指南或操作手册可仅依据官方指南生成；申报材料建议选择企业资质档案。</div>
              <label class="qual-upload compact">
                <input type="file" accept=".pdf,.docx,.txt,.md" @change="materialFile = $event.target.files?.[0] || null" />
                <span class="qual-upload-icon" aria-hidden="true">＋</span>
                <strong>{{ materialFile?.name || '上传企业资质档案' }}</strong>
                <small>仅限企业手工上传的可追溯材料</small>
              </label>
              <button class="ghost-button" type="button" :disabled="!materialFile || uploadingMaterial" @click="uploadMaterialFile">
                {{ uploadingMaterial ? '解析中…' : '上传并加入档案' }}
              </button>
            </div>
            <div class="qual-actions split">
              <button class="ghost-button" type="button" @click="setupStep = 1">返回</button>
              <button class="primary-button" type="submit" :disabled="!form.guideSchemaId">
                确认材料清单
              </button>
            </div>
          </form>

          <form v-else class="qual-form" @submit.prevent="createTask">
            <div class="qual-launch-card">
              <span class="qual-launch-number">03</span>
              <div>
                <span class="qual-kicker">启动前确认</span>
                <h4>{{ form.qualificationType }} · {{ form.documentType }}</h4>
                <p>任务会锁定当前指南版本，并记录企业档案引用。生成结果默认为 DRAFT，需人工审核。</p>
              </div>
            </div>
            <div class="qual-form-grid">
              <label class="qual-field">
                <span>输出文档类型</span>
                <select v-model="form.documentType">
                  <option>资质申报材料初稿</option>
                  <option>服务指南</option>
                  <option>操作手册</option>
                </select>
              </label>
              <label class="qual-field">
                <span>正文最大字数 <em>可选</em></span>
                <input v-model.number="form.maxChars" type="number" min="0" step="100" placeholder="不限制" />
              </label>
            </div>
            <div class="qual-boundary-note">
              <strong>生成边界</strong>
              <span>模型不得补充不可追溯事实；缺少信息会标记为待人工补充；模型不可用时任务明确失败。</span>
            </div>
            <div class="qual-actions split">
              <button class="ghost-button" type="button" @click="setupStep = 2">返回</button>
              <button class="primary-button" type="submit" :disabled="creatingTask">
                {{ creatingTask ? '正在启动…' : '启动智能编制' }}
              </button>
            </div>
          </form>
        </section>

        <section v-else-if="selectedTask" class="qual-workbench">
          <header class="qual-workbench-head">
            <div>
              <p class="eyebrow">{{ selectedTask.guideName }} · {{ selectedTask.guideVersion }}</p>
              <h3>{{ document?.title || `${selectedTask.qualificationType}编制任务` }}</h3>
              <p class="qual-muted">{{ selectedTask.progressMessage || statusLabel(selectedTask.status) }}</p>
            </div>
            <div class="qual-head-actions">
              <span :class="['qual-status', statusClass(selectedTask.status)]">{{ statusLabel(selectedTask.status) }}</span>
              <button
                class="primary-button compact-button"
                type="button"
                :disabled="document?.status !== 'APPROVED' || exporting"
                @click="exportDocument"
              >
                {{ exporting ? '导出中…' : '导出 DOCX' }}
              </button>
            </div>
          </header>

          <div class="qual-progress">
            <div class="qual-progress-track"><i :style="{ width: `${selectedTask.progress || 0}%` }"></i></div>
            <span>{{ selectedTask.progress || 0 }}%</span>
          </div>

          <div v-if="selectedTask.status === 'FAILED'" class="qual-failure">
            <strong>任务未完成</strong>
            <span>{{ selectedTask.failureReason || 'Worker 返回失败，请检查服务状态后重试。' }}</span>
          </div>

          <div class="qual-editor-layout">
            <aside class="qual-outline">
              <div class="qual-panel-title">
                <span class="qual-kicker">章节结构</span>
                <strong>{{ sections.length }} 个章节</strong>
              </div>
              <button
                v-for="(section, index) in sections"
                :key="section.key || index"
                type="button"
                :class="{ active: activeSection === index }"
                @click="activeSection = index"
              >
                <span>{{ String(index + 1).padStart(2, '0') }}</span>
                {{ section.title || '未命名章节' }}
              </button>
            </aside>

            <section class="qual-editor-panel">
              <div v-if="activeSectionData" class="qual-editor-head">
                <div>
                  <span class="qual-kicker">可编辑初稿</span>
                  <h4>{{ activeSectionData.title }}</h4>
                </div>
                <span class="qual-draft-mark">DRAFT · 待人工核对</span>
              </div>
              <div v-if="activeSectionData" class="qual-blocks">
                <article v-for="(block, index) in activeSectionData.blocks || []" :key="index" class="qual-block">
                  <textarea v-model="block.text" rows="7" :aria-label="`${activeSectionData.title}第 ${index + 1} 段`"></textarea>
                  <div class="qual-block-foot">
                    <span>{{ (block.text || '').length }} 字</span>
                    <span :class="{ warn: !block.citations?.length }">
                      {{ block.citations?.length ? `已关联 ${block.citations.length} 条引用` : '缺少引用' }}
                    </span>
                  </div>
                </article>
                <div v-if="!(activeSectionData.blocks || []).length" class="qual-inline-empty">当前章节暂无可编辑内容。</div>
              </div>
              <div class="qual-editor-actions">
                <label class="qual-note-input">
                  <span>变更说明</span>
                  <input v-model="changeNote" placeholder="例如：补充企业研发组织说明" />
                </label>
                <button class="primary-button compact-button" type="button" :disabled="saving" @click="saveDocument">
                  {{ saving ? '保存中…' : '保存版本' }}
                </button>
              </div>
            </section>

            <aside class="qual-inspector">
              <section class="qual-inspector-section">
                <div class="qual-panel-title">
                  <span class="qual-kicker">引用来源</span>
                  <strong>{{ sources.length }} 条锚点</strong>
                </div>
                <article v-for="(source, index) in sources" :key="source.id || index" class="qual-source">
                  <span>{{ index + 1 }}</span>
                  <div>
                    <strong>{{ source.docTitle || '未命名来源' }}</strong>
                    <p>{{ source.excerpt || '暂无摘录' }}</p>
                    <small>score {{ source.score ?? '待校验' }}</small>
                  </div>
                </article>
                <div v-if="!sources.length" class="qual-inline-empty">生成后此处显示可追溯来源。</div>
              </section>

              <section class="qual-inspector-section">
                <div class="qual-panel-title">
                  <span class="qual-kicker">校验报告</span>
                  <strong>{{ validationSummary }}</strong>
                </div>
                <div v-for="(item, index) in validationItems" :key="item.code || index" :class="['qual-validation', item.status === 'PASS' ? 'pass' : 'fail']">
                  <span>{{ item.status === 'PASS' ? '✓' : '!' }}</span>
                  <p>{{ item.message }}</p>
                </div>
                <div v-if="!validationItems.length" class="qual-inline-empty">任务完成后生成格式与引用校验。</div>
              </section>

              <section class="qual-inspector-section">
                <div class="qual-panel-title">
                  <span class="qual-kicker">人工审核</span>
                  <strong>{{ document?.status || '等待初稿' }}</strong>
                </div>
                <textarea v-model="reviewComment" rows="3" placeholder="填写送审或退回说明"></textarea>
                <div class="qual-review-actions">
                  <button class="ghost-button" type="button" :disabled="reviewing || document?.status !== 'DRAFT'" @click="reviewDocument('submit')">送审</button>
                  <button class="ghost-button danger-button" type="button" :disabled="reviewing || !['IN_REVIEW', 'DRAFT'].includes(document?.status)" @click="reviewDocument('reject')">退回</button>
                  <button class="primary-button" type="button" :disabled="reviewing || document?.status !== 'IN_REVIEW'" @click="reviewDocument('approve')">通过</button>
                </div>
              </section>

              <section class="qual-inspector-section">
                <div class="qual-panel-title">
                  <span class="qual-kicker">版本历史</span>
                  <strong>v{{ document?.currentVersion || 0 }}</strong>
                </div>
                <div v-for="version in versions.slice(0, 4)" :key="version.id" class="qual-version">
                  <strong>v{{ version.version }}</strong>
                  <span>{{ version.changeNote || '无变更说明' }}</span>
                  <small>{{ formatDate(version.createdAt) }}</small>
                </div>
                <div v-if="!versions.length" class="qual-inline-empty">保存后生成版本快照。</div>
              </section>
            </aside>
          </div>
        </section>

        <section v-else class="qual-empty-main">
          <span class="qual-empty-mark">Q</span>
          <h3>选择任务，开始核对编制结果</h3>
          <p>左侧可查看历史任务，也可以新建一份指南解析任务。</p>
          <button class="primary-button compact-button" type="button" @click="startNewTask">新建任务</button>
        </section>
      </section>
    </section>
  </main>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue';
import {
  createQualTask,
  downloadQualDocument,
  fetchQualDocument,
  fetchQualGuides,
  fetchQualMaterials,
  fetchQualReports,
  fetchQualTasks,
  fetchQualVersions,
  reviewQualDocument,
  saveQualDocument,
  subscribeQualTask,
  uploadQualGuide,
  uploadQualMaterial,
} from '../api';

const steps = [
  { id: 1, label: '上传官方指南' },
  { id: 2, label: '确认企业档案' },
  { id: 3, label: '启动编制' },
];
const setupStep = ref(1);
const view = ref('setup');
const guides = ref([]);
const materials = ref([]);
const tasks = ref([]);
const selectedTask = ref(null);
const currentGuide = ref(null);
const document = ref(null);
const reports = ref([]);
const versions = ref([]);
const activeSection = ref(0);
const selectedMaterialIds = ref([]);
const guideFile = ref(null);
const materialFile = ref(null);
const uploadingMaterial = ref(false);
const creatingTask = ref(false);
const saving = ref(false);
const reviewing = ref(false);
const exporting = ref(false);
const notice = ref('');
const noticeType = ref('success');
const changeNote = ref('');
const reviewComment = ref('');
let eventSource = null;
let noticeTimer;

const form = reactive({
  qualificationType: '',
  guideName: '',
  version: '2026-v1',
  sourceUrl: '',
  guideSchemaId: '',
  documentType: '资质申报材料初稿',
  maxChars: 0,
});

const sections = computed(() => document.value?.content?.sections || []);
const activeSectionData = computed(() => sections.value[activeSection.value]);
const sources = computed(() => document.value?.sources || []);
const validationItems = computed(() => reports.value[0]?.items || []);
const validationSummary = computed(() => {
  const summary = reports.value[0]?.summary;
  if (!summary) return '待生成';
  return summary.passed ? `通过 ${summary.total}` : `失败 ${summary.failed}/${summary.total}`;
});

function statusLabel(status) {
  return {
    CREATED: '已创建',
    PARSING: '解析中',
    GENERATING: '生成中',
    VALIDATING: '校验中',
    READY_REVIEW: '待审核',
    FAILED: '失败',
  }[status] || status || '未知';
}

function statusClass(status) {
  return ['READY_REVIEW', 'APPROVED'].includes(status) ? 'ok' : status === 'FAILED' ? 'danger' : 'working';
}

function formatDate(value) {
  if (!value) return '刚刚';
  return new Date(value).toLocaleString('zh-CN', { dateStyle: 'short', timeStyle: 'short' });
}

function showNotice(message, type = 'success') {
  notice.value = message;
  noticeType.value = type;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => (notice.value = ''), 4500);
}

async function loadAll() {
  try {
    const [guideData, materialData, taskData] = await Promise.all([fetchQualGuides(), fetchQualMaterials(), fetchQualTasks()]);
    guides.value = Array.isArray(guideData) ? guideData : [];
    materials.value = Array.isArray(materialData) ? materialData : [];
    tasks.value = Array.isArray(taskData) ? taskData : [];
    if (selectedTask.value) {
      const refreshed = tasks.value.find((item) => item.id === selectedTask.value.id);
      if (refreshed) await selectTask(refreshed.id, false);
    }
  } catch (error) {
    showNotice(error.message, 'error');
  }
}

function startNewTask() {
  stopEvents();
  view.value = 'setup';
  setupStep.value = 1;
  selectedTask.value = null;
  currentGuide.value = null;
  document.value = null;
  reports.value = [];
  versions.value = [];
  activeSection.value = 0;
  selectedMaterialIds.value = [];
  guideFile.value = null;
  materialFile.value = null;
  Object.assign(form, {
    qualificationType: '',
    guideName: '',
    version: '2026-v1',
    sourceUrl: '',
    guideSchemaId: '',
    documentType: '资质申报材料初稿',
    maxChars: 0,
  });
}

async function parseGuide() {
  try {
    currentGuide.value = await uploadQualGuide(guideFile.value, {
      qualificationType: form.qualificationType,
      guideName: form.guideName,
      version: form.version,
      sourceUrl: form.sourceUrl,
    });
    form.guideSchemaId = currentGuide.value.id;
    await loadAll();
    showNotice('指南已解析并保存为 ACTIVE 版本。');
    setupStep.value = 2;
  } catch (error) {
    showNotice(error.message, 'error');
  }
}

async function uploadMaterialFile() {
  uploadingMaterial.value = true;
  try {
    const material = await uploadQualMaterial(materialFile.value);
    materials.value = [material, ...materials.value];
    selectedMaterialIds.value = [...selectedMaterialIds.value, material.id];
    materialFile.value = null;
    showNotice('企业档案已解析并加入可追溯素材。');
  } catch (error) {
    showNotice(error.message, 'error');
  } finally {
    uploadingMaterial.value = false;
  }
}

function syncGuide() {
  currentGuide.value = guides.value.find((guide) => guide.id === form.guideSchemaId) || null;
  if (currentGuide.value && !form.qualificationType) form.qualificationType = currentGuide.value.qualificationType;
}

async function createTask() {
  creatingTask.value = true;
  try {
    const task = await createQualTask({
      qualificationType: form.qualificationType,
      guideSchemaId: form.guideSchemaId,
      documentType: form.documentType,
      materialIds: selectedMaterialIds.value,
      formatRequirements: form.maxChars > 0 ? { maxChars: form.maxChars } : {},
      idempotencyKey: `${form.guideSchemaId}-${Date.now()}`,
    });
    tasks.value = [task, ...tasks.value.filter((item) => item.id !== task.id)];
    await selectTask(task.id);
    showNotice('任务已启动，页面会实时接收处理进度。');
  } catch (error) {
    showNotice(error.message, 'error');
  } finally {
    creatingTask.value = false;
  }
}

async function selectTask(taskId, switchView = true) {
  try {
    const task = await fetchQualTask(taskId);
    selectedTask.value = task;
    if (switchView) view.value = 'workbench';
    if (task.documentId) {
      document.value = await fetchQualDocument(task.documentId);
      reports.value = await fetchQualReports(task.id);
      versions.value = await fetchQualVersions(task.documentId);
      activeSection.value = Math.min(activeSection.value, Math.max(sections.value.length - 1, 0));
    }
    subscribeToTask(task.id);
  } catch (error) {
    showNotice(error.message, 'error');
  }
}

function subscribeToTask(taskId) {
  stopEvents();
  eventSource = subscribeQualTask(
    taskId,
    async (type, payload) => {
      if (type === 'progress') {
        selectedTask.value = { ...selectedTask.value, ...payload };
      } else if (type === 'document' || type === 'partial') {
        await selectTask(taskId, false);
      } else if (type === 'failed') {
        selectedTask.value = { ...selectedTask.value, status: 'FAILED', failureReason: payload.message };
        showNotice(payload.message || '任务失败', 'error');
      }
    },
    () => {},
  );
}

function stopEvents() {
  eventSource?.close();
  eventSource = null;
}

async function saveDocument() {
  if (!document.value) return;
  saving.value = true;
  try {
    document.value = await saveQualDocument(document.value.id, document.value.content, changeNote.value);
    versions.value = await fetchQualVersions(document.value.id);
    changeNote.value = '';
    showNotice('已保存新版本，原版本仍可追溯。');
  } catch (error) {
    showNotice(error.message, 'error');
  } finally {
    saving.value = false;
  }
}

async function reviewDocument(action) {
  if (!document.value) return;
  reviewing.value = true;
  try {
    document.value = await reviewQualDocument(document.value.id, action, reviewComment.value);
    reviewComment.value = '';
    showNotice(action === 'approve' ? '文档已通过审核，可导出正式版。' : action === 'submit' ? '文档已送审。' : '文档已退回修改。');
  } catch (error) {
    showNotice(error.message, 'error');
  } finally {
    reviewing.value = false;
  }
}

async function exportDocument() {
  if (!document.value) return;
  exporting.value = true;
  try {
    await downloadQualDocument(document.value.id);
    document.value.status = 'LOCKED';
    showNotice('正式 DOCX 已导出，文档进入 LOCKED 归档状态。');
  } catch (error) {
    showNotice(error.message, 'error');
  } finally {
    exporting.value = false;
  }
}

onMounted(loadAll);
onBeforeUnmount(stopEvents);
</script>

<style scoped>
.qual-page {
  max-width: 1540px;
  margin: 0 auto;
  padding: clamp(24px, 4vw, 56px);
  color: var(--ink);
}

.qual-hero {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 32px;
  padding: 28px 0 38px;
  border-bottom: 1px solid var(--line);
}

.qual-hero h2 {
  max-width: 850px;
  margin: 0;
  font-size: clamp(2rem, 4.2vw, 4.8rem);
  line-height: 1.06;
}

.qual-lead {
  max-width: 720px;
  margin: 18px 0 0;
  color: var(--ink-muted);
  line-height: 1.75;
}

.qual-guard {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 230px;
  padding: 14px 16px;
  border: 1px solid rgba(15, 118, 110, 0.2);
  border-radius: var(--radius);
  background: #f4fbf8;
}

.qual-guard-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #16877b;
  box-shadow: 0 0 0 5px rgba(22, 135, 123, 0.12);
}

.qual-guard strong,
.qual-guard small {
  display: block;
}

.qual-guard small,
.qual-muted,
.qual-kicker {
  color: var(--ink-muted);
  font-size: 12px;
}

.qual-layout {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
  gap: 22px;
  margin-top: 22px;
}

.qual-sidebar,
.qual-setup,
.qual-workbench,
.qual-empty-main {
  border: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.86);
  box-shadow: 0 14px 45px rgba(18, 43, 40, 0.06);
}

.qual-sidebar {
  align-self: start;
  padding: 18px 14px;
}

.qual-sidebar-head,
.qual-section-head,
.qual-workbench-head,
.qual-panel-title,
.qual-editor-head,
.qual-subhead {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.qual-sidebar-head h3,
.qual-section-head h3,
.qual-workbench-head h3,
.qual-editor-head h4 {
  margin: 0;
}

.qual-sidebar-head .eyebrow,
.qual-section-head .eyebrow,
.qual-workbench-head .eyebrow {
  margin-bottom: 4px;
}

.qual-icon-button {
  width: 40px;
  height: 40px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  color: var(--primary-strong);
  font-size: 20px;
}

.qual-new-task {
  width: 100%;
  min-height: 44px;
  margin: 22px 0 16px;
  border: 0;
  border-radius: 8px;
  background: #112927;
  color: #fff;
  font-weight: 800;
}

.qual-new-task span {
  margin-right: 5px;
  font-size: 18px;
}

.qual-task-list {
  display: grid;
  gap: 8px;
}

.qual-task-item {
  display: grid;
  gap: 7px;
  width: 100%;
  padding: 12px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: #f6faf8;
  color: var(--ink);
  text-align: left;
}

.qual-task-item:hover,
.qual-task-item.active {
  border-color: rgba(15, 118, 110, 0.3);
  background: #eaf7f3;
}

.qual-task-title {
  overflow: hidden;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.qual-task-meta {
  color: var(--ink-muted);
  font-size: 12px;
}

.qual-task-progress,
.qual-progress-track {
  display: block;
  height: 5px;
  overflow: hidden;
  border-radius: 99px;
  background: #dcece8;
}

.qual-task-progress i,
.qual-progress-track i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: #138479;
  transition: width 0.25s ease;
}

.qual-empty-sidebar,
.qual-inline-empty {
  display: grid;
  gap: 4px;
  color: var(--ink-muted);
  font-size: 13px;
  line-height: 1.6;
}

.qual-main {
  min-width: 0;
}

.qual-notice {
  margin-bottom: 14px;
  padding: 12px 14px;
  border: 1px solid;
  border-radius: 8px;
  font-size: 13px;
}

.qual-notice.success {
  border-color: #a7dccc;
  background: #effbf7;
  color: #116052;
}

.qual-notice.error {
  border-color: #f0b9b0;
  background: #fff4f2;
  color: #9b2c20;
}

.qual-setup {
  padding: clamp(22px, 3vw, 38px);
}

.qual-step-count {
  color: var(--primary);
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.12em;
}

.qual-steps {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  margin: 28px 0;
  padding-bottom: 18px;
  border-bottom: 1px solid var(--line);
}

.qual-steps button {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 0 0 10px;
  border: 0;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: var(--ink-muted);
  font-size: 13px;
  font-weight: 800;
  text-align: left;
}

.qual-steps button span {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: #e5f2ef;
  color: var(--primary-strong);
}

.qual-steps button.active {
  border-color: var(--primary);
  color: var(--ink);
}

.qual-steps button.active span,
.qual-steps button.done span {
  background: #112927;
  color: #fff;
}

.qual-form {
  display: grid;
  gap: 20px;
}

.qual-form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.qual-field {
  display: grid;
  gap: 7px;
  color: #263a37;
  font-size: 13px;
  font-weight: 800;
}

.qual-field em {
  color: var(--ink-muted);
  font-size: 11px;
  font-style: normal;
  font-weight: 500;
}

.qual-field input,
.qual-field select,
.qual-note-input input,
.qual-inspector textarea {
  width: 100%;
  min-height: 42px;
  border: 1px solid rgba(37, 67, 63, 0.18);
  border-radius: 6px;
  padding: 9px 11px;
  outline: none;
  background: #fff;
  color: var(--ink);
}

.qual-field input:focus,
.qual-field select:focus,
.qual-note-input input:focus,
.qual-inspector textarea:focus,
.qual-block textarea:focus {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px rgba(15, 118, 110, 0.12);
}

.qual-upload {
  display: grid;
  place-items: center;
  gap: 8px;
  min-height: 180px;
  padding: 24px;
  border: 1px dashed rgba(15, 118, 110, 0.42);
  border-radius: 8px;
  background: #f6fcfa;
  text-align: center;
}

.qual-upload.compact {
  min-height: 110px;
  margin-top: 14px;
}

.qual-upload input {
  position: absolute;
  width: 1px;
  height: 1px;
  opacity: 0;
}

.qual-upload-icon {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  border-radius: 50%;
  background: #dff2ed;
  color: var(--primary-strong);
  font-size: 22px;
}

.qual-upload small {
  max-width: 460px;
  color: var(--ink-muted);
  font-size: 12px;
}

.qual-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.qual-actions.split {
  justify-content: space-between;
}

.qual-actions .primary-button {
  width: auto;
  min-width: 170px;
}

.qual-guide-summary,
.qual-launch-card,
.qual-boundary-note {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  padding: 16px;
  border: 1px solid #bfe1d8;
  border-radius: 8px;
  background: #f1fbf8;
}

.qual-guide-summary strong,
.qual-guide-summary small {
  display: block;
  margin-top: 5px;
}

.qual-status {
  flex: 0 0 auto;
  border-radius: 999px;
  padding: 5px 9px;
  background: #edf1f0;
  color: var(--ink-muted);
  font-size: 11px;
  font-weight: 800;
}

.qual-status.ok {
  background: #dff5eb;
  color: #176847;
}

.qual-status.working {
  background: #fff3d5;
  color: #8a5b00;
}

.qual-status.danger {
  background: #ffe3df;
  color: #a52e21;
}

.qual-checklist {
  display: grid;
  gap: 12px;
}

.qual-subhead {
  align-items: center;
}

.qual-subhead > span {
  color: var(--primary);
  font-size: 12px;
  font-weight: 800;
}

.qual-material-list {
  display: grid;
  gap: 8px;
}

.qual-material-row {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 11px 12px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: #fbfdfc;
}

.qual-material-row input {
  width: 17px;
  height: 17px;
  accent-color: var(--primary);
}

.qual-material-row span {
  min-width: 0;
}

.qual-material-row strong,
.qual-material-row small {
  display: block;
}

.qual-material-row strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.qual-material-row small {
  margin-top: 4px;
  color: var(--ink-muted);
  font-size: 11px;
}

.qual-checklist > .ghost-button {
  width: max-content;
}

.qual-launch-number {
  color: var(--primary);
  font-size: 28px;
  font-weight: 900;
}

.qual-launch-card h4 {
  margin: 5px 0;
}

.qual-launch-card p,
.qual-boundary-note span {
  margin: 0;
  color: var(--ink-muted);
  font-size: 13px;
  line-height: 1.6;
}

.qual-boundary-note {
  border-color: #f0d49b;
  background: #fffaf0;
}

.qual-boundary-note strong {
  color: #805c13;
}

.qual-workbench {
  padding: clamp(20px, 3vw, 32px);
}

.qual-workbench-head {
  align-items: center;
}

.qual-workbench-head h3 {
  font-size: clamp(1.4rem, 2.5vw, 2.2rem);
}

.qual-head-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.compact-button {
  width: auto;
  min-height: 40px;
  padding: 8px 13px;
  white-space: nowrap;
}

.qual-progress {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 22px 0;
}

.qual-progress-track {
  flex: 1;
  height: 8px;
}

.qual-progress > span {
  min-width: 40px;
  color: var(--primary-strong);
  font-size: 12px;
  font-weight: 800;
  text-align: right;
}

.qual-failure {
  display: grid;
  gap: 5px;
  margin-bottom: 18px;
  padding: 13px 15px;
  border-left: 3px solid #b42318;
  background: #fff4f2;
  color: #8f261c;
  font-size: 13px;
}

.qual-editor-layout {
  display: grid;
  grid-template-columns: 190px minmax(0, 1fr) 290px;
  gap: 14px;
  align-items: start;
}

.qual-outline,
.qual-editor-panel,
.qual-inspector {
  min-width: 0;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fbfdfc;
}

.qual-outline {
  padding: 14px 10px;
}

.qual-panel-title {
  align-items: center;
  padding: 2px 4px 12px;
}

.qual-panel-title strong {
  font-size: 13px;
}

.qual-outline > button {
  display: grid;
  grid-template-columns: 27px minmax(0, 1fr);
  gap: 7px;
  width: 100%;
  padding: 10px 7px;
  border: 0;
  border-left: 2px solid transparent;
  background: transparent;
  color: var(--ink-muted);
  font-size: 12px;
  text-align: left;
}

.qual-outline > button span {
  color: #91aaa5;
  font-weight: 800;
}

.qual-outline > button.active {
  border-left-color: var(--primary);
  background: #eaf7f3;
  color: var(--ink);
  font-weight: 800;
}

.qual-editor-panel {
  padding: 16px;
}

.qual-editor-head {
  align-items: center;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--line);
}

.qual-editor-head h4 {
  margin-top: 4px;
  font-size: 18px;
}

.qual-draft-mark {
  color: #9a6c16;
  font-size: 11px;
  font-weight: 800;
}

.qual-blocks {
  display: grid;
  gap: 12px;
  padding: 16px 0;
}

.qual-block {
  border: 1px solid var(--line);
  border-radius: 6px;
  background: #fff;
}

.qual-block textarea {
  display: block;
  width: 100%;
  min-height: 140px;
  resize: vertical;
  border: 0;
  border-bottom: 1px solid var(--line);
  border-radius: 6px 6px 0 0;
  padding: 13px;
  outline: none;
  color: var(--ink);
  line-height: 1.75;
}

.qual-block-foot {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 11px;
  color: var(--ink-muted);
  font-size: 11px;
}

.qual-block-foot .warn {
  color: #b45309;
}

.qual-editor-actions {
  display: flex;
  align-items: end;
  gap: 10px;
  padding-top: 14px;
  border-top: 1px solid var(--line);
}

.qual-note-input {
  display: grid;
  flex: 1;
  gap: 6px;
  color: var(--ink-muted);
  font-size: 11px;
}

.qual-inspector {
  display: grid;
  gap: 0;
}

.qual-inspector-section {
  display: grid;
  gap: 10px;
  padding: 14px;
  border-bottom: 1px solid var(--line);
}

.qual-inspector-section:last-child {
  border-bottom: 0;
}

.qual-source {
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr);
  gap: 8px;
  padding: 9px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: #fff;
}

.qual-source > span {
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: #e1f2ed;
  color: var(--primary-strong);
  font-size: 11px;
  font-weight: 800;
}

.qual-source strong {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
}

.qual-source p {
  display: -webkit-box;
  overflow: hidden;
  margin: 4px 0;
  color: var(--ink-muted);
  font-size: 11px;
  line-height: 1.5;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
}

.qual-source small {
  color: var(--primary);
  font-size: 10px;
}

.qual-validation {
  display: grid;
  grid-template-columns: 20px minmax(0, 1fr);
  gap: 7px;
  align-items: start;
  font-size: 11px;
}

.qual-validation > span {
  display: grid;
  place-items: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  font-weight: 900;
}

.qual-validation.pass > span {
  background: #dff5eb;
  color: #176847;
}

.qual-validation.fail > span {
  background: #ffe3df;
  color: #a52e21;
}

.qual-validation p {
  margin: 2px 0 0;
  color: var(--ink-muted);
  line-height: 1.5;
}

.qual-review-actions {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 6px;
}

.qual-review-actions button {
  width: auto;
  min-width: 0;
  padding: 8px 5px;
  font-size: 11px;
}

.danger-button {
  color: #a52e21;
}

.qual-version {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr);
  gap: 3px 7px;
  padding: 8px 0;
  border-bottom: 1px solid rgba(37, 67, 63, 0.08);
  font-size: 11px;
}

.qual-version strong {
  grid-row: span 2;
  color: var(--primary);
}

.qual-version span {
  color: var(--ink);
}

.qual-version small {
  color: var(--ink-muted);
}

.qual-empty-main {
  display: grid;
  place-items: center;
  min-height: 480px;
  padding: 40px;
  text-align: center;
}

.qual-empty-mark {
  display: grid;
  place-items: center;
  width: 58px;
  height: 58px;
  border-radius: 50%;
  background: #e2f2ee;
  color: var(--primary-strong);
  font-weight: 900;
}

.qual-empty-main h3 {
  margin: 16px 0 4px;
}

.qual-empty-main p {
  margin: 0 0 18px;
  color: var(--ink-muted);
}

@media (max-width: 1180px) {
  .qual-editor-layout {
    grid-template-columns: 170px minmax(0, 1fr);
  }

  .qual-inspector {
    grid-column: 1 / -1;
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .qual-inspector-section {
    border-right: 1px solid var(--line);
    border-bottom: 0;
  }

  .qual-inspector-section:last-child {
    border-right: 0;
  }
}

@media (max-width: 820px) {
  .qual-hero {
    display: grid;
  }

  .qual-layout {
    grid-template-columns: 1fr;
  }

  .qual-sidebar {
    position: static;
  }

  .qual-task-list {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .qual-page {
    padding: 18px 14px 30px;
  }

  .qual-form-grid,
  .qual-steps,
  .qual-editor-layout,
  .qual-inspector {
    grid-template-columns: 1fr;
  }

  .qual-task-list {
    grid-template-columns: 1fr;
  }

  .qual-steps button {
    font-size: 11px;
  }

  .qual-workbench-head,
  .qual-editor-head,
  .qual-editor-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .qual-head-actions,
  .qual-actions,
  .qual-actions.split {
    align-items: stretch;
    flex-direction: column;
  }

  .qual-actions .primary-button,
  .qual-head-actions .primary-button {
    width: 100%;
  }

  .qual-inspector-section {
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }
}
</style>
