<template>
  <main class="workspace">
    <section class="compose-panel">
      <div class="section-title">
        <h2>创建草稿</h2>
        <button class="ghost-button" type="button" @click="resetForm">重置</button>
      </div>

      <label class="field">
        <span>标题</span>
        <input v-model="form.title" placeholder="例如：关于智能办公平台试运行的通知" />
      </label>

      <label class="field">
        <span>核心事项</span>
        <textarea v-model="form.eventDesc" rows="5" placeholder="描述事件背景、发布时间、面向对象、关键动作"></textarea>
      </label>

      <div class="grid two">
        <label class="field">
          <span>模板类型</span>
          <select v-model="form.template">
            <optgroup v-for="(group, category) in templateGroups" :key="category" :label="category">
              <option v-for="template in group" :key="template.name" :value="template.name">
                {{ templateTitle(template) }}
              </option>
            </optgroup>
          </select>
          <small class="muted-hint">当前：{{ currentTemplateCategory }} / {{ currentTemplateTitle }}</small>
        </label>

        <label class="field">
          <span>主文风</span>
          <select v-model="form.style">
            <option v-for="style in styles" :key="style.name" :value="style.name">
              {{ style.name }}
            </option>
          </select>
        </label>
      </div>

      <label class="field">
        <span>受众</span>
        <input v-model="form.audience" placeholder="例如：全体员工、媒体、合作伙伴" />
      </label>

      <div class="subsection">
        <div class="section-title compact">
          <h3>关键要素</h3>
          <button class="icon-button" type="button" title="添加要素" @click="addFact">+</button>
        </div>
        <div v-for="(fact, index) in form.keyFacts" :key="index" class="inline-row">
          <input v-model="fact.name" placeholder="要素名" />
          <input v-model="fact.value" placeholder="要素值" />
          <button class="icon-button danger" type="button" title="删除要素" @click="removeFact(index)">×</button>
        </div>
      </div>

      <div class="subsection">
        <div class="section-title compact">
          <h3>相关人员</h3>
          <button class="icon-button" type="button" title="添加人员" @click="addPerson">+</button>
        </div>
        <div v-for="(person, index) in form.people" :key="index" class="inline-row">
          <input v-model="person.name" placeholder="姓名" />
          <input v-model="person.title" placeholder="职务" />
          <button class="icon-button danger" type="button" title="删除人员" @click="removePerson(index)">×</button>
        </div>
      </div>

      <div class="subsection">
        <div class="section-title compact">
          <h3>素材</h3>
          <small class="muted-hint">素材由后台管理上传</small>
        </div>
        <div class="material-list">
          <label v-for="material in materials" :key="material.id" class="check-row">
            <input v-model="form.referenceMaterials" type="checkbox" :value="material.id" />
            <span>{{ material.filename }}</span>
            <small>{{ material.status }} · {{ material.text_length }} 字</small>
          </label>
        </div>
      </div>

      <button class="primary-button" type="button" :disabled="submitting" @click="submitDraft">
        {{ submitting ? '生成中...' : '生成草稿' }}
      </button>
      <p v-if="errorMessage" class="error-text">{{ errorMessage }}</p>
    </section>

    <section class="draft-panel">
      <div class="draft-header">
        <div>
          <p class="eyebrow">草稿查看</p>
          <h2>{{ currentDraft.title || '未命名草稿' }}</h2>
        </div>
        <div class="draft-actions">
          <button v-if="!editing && currentDraft.id" class="ghost-button" type="button" :disabled="polishing" @click="submitPolish">
            {{ polishing ? '润色中...' : '润色' }}
          </button>
          <button v-if="!editing && currentDraft.id" class="ghost-button" type="button" @click="startEdit">编辑正文</button>
          <div class="meta-stack">
            <span>v{{ currentDraft.version || 1 }}</span>
            <span>{{ currentDraft.status || '已生成' }}</span>
          </div>
        </div>
      </div>

      <div class="summary-strip">
        <div>
          <strong>{{ currentDraft.template_name || form.template }}</strong>
          <span>模板</span>
        </div>
        <div>
          <strong>{{ currentDraft.style || form.style }}</strong>
          <span>文风</span>
        </div>
        <div>
          <strong>{{ currentDraft.model || 'demo-model' }}</strong>
          <span>模型</span>
        </div>
      </div>

      <div class="revision-box">
        <div class="revision-input-row">
          <textarea v-model="revisionInstruction" rows="2" placeholder="修改指令（改哪里、怎么改）：例如 将发布日期改为2026年9月1日，语气更正式，补充反馈渠道"></textarea>
          <button class="primary-button revision-submit" type="button" :disabled="revising || !currentDraft.id" @click="submitRevision">
            {{ revising ? '生成中...' : '重新生成' }}
          </button>
        </div>
      </div>

      <div class="export-box">
        <div class="export-input-row">
          <select v-model="exportFormat">
            <option value="md">Markdown (.md)</option>
            <option value="docx">Word (.docx)</option>
          </select>
          <button class="primary-button export-submit" type="button" :disabled="exporting || !currentDraft.id" @click="submitExport">
            {{ exporting ? '导出中...' : '导出' }}
          </button>
        </div>
      </div>

      <div class="tabs">
        <button v-for="tab in tabs" :key="tab.key" :class="{ active: activeTab === tab.key }" type="button" @click="activeTab = tab.key">
          {{ tab.label }}
        </button>
      </div>

      <article v-if="activeTab === 'content'" class="draft-content">
        <div v-if="editing" class="edit-area">
          <textarea v-model="editText" rows="20" placeholder="在此直接编辑正文..."></textarea>
          <div class="edit-actions">
            <button class="ghost-button" type="button" :disabled="savingEdit" @click="cancelEdit">取消</button>
            <button class="primary-button edit-save" type="button" :disabled="savingEdit" @click="saveEdit">
              {{ savingEdit ? '保存中...' : '保存修改' }}
            </button>
          </div>
        </div>
        <template v-else-if="streamParagraphs.length">
          <p v-for="(paragraph, index) in streamParagraphs" :key="index">{{ paragraph }}</p>
        </template>
        <template v-else>
          <p v-for="(paragraph, index) in draftParagraphs" :key="index">{{ paragraph }}</p>
        </template>
        <p v-if="submitting && streamStage" class="stream-status">{{ stageLabel }}…</p>
      </article>

      <div v-else-if="activeTab === 'suggestions'" class="list-panel">
        <div v-if="polishChanges.length" class="polish-panel">
          <p class="panel-note">润色修改说明（已生成新版本 v{{ currentDraft.version }}）：</p>
          <div v-for="(change, index) in polishChanges" :key="index" class="polish-item">
            <div class="polish-row">
              <small>原文</small>
              <p>{{ change.original }}</p>
            </div>
            <div class="polish-row revised">
              <small>改后</small>
              <p>{{ change.revised }}</p>
            </div>
            <span class="polish-reason">{{ change.reason }}</span>
          </div>
        </div>
        <div v-for="(suggestion, index) in revisionSuggestions" :key="index" class="suggestion-item">
          <span>{{ index + 1 }}</span>
          <p>{{ suggestion }}</p>
          <button class="apply-button" type="button" @click="applySuggestion(suggestion)">应用</button>
        </div>
      </div>

      <div v-else-if="activeTab === 'factcheck'" class="list-panel">
        <div v-for="(item, index) in factChecks" :key="index" class="fact-item">
          <div class="fact-topline">
            <strong>{{ item.claim }}</strong>
            <span :class="['check-badge', badgeClass(item.status)]">{{ item.status }}</span>
          </div>
          <p>{{ item.basis || '暂无依据说明' }}</p>
          <small v-if="item.suggestion">{{ item.suggestion }}</small>
        </div>
      </div>

      <div v-else class="version-tree">
        <VersionNodeView :node="versionTree" :current-id="currentDraft.id" :on-revert="revertToVersion" />
      </div>
    </section>
  </main>
</template>

<script setup>
import { computed, defineComponent, h, onMounted, reactive, ref, watch } from 'vue';
import { createDraft, createDraftStream, editDraftContent, exportDraft, fetchDraft, fetchMaterials, fetchStyles, fetchTemplates, fetchVersions, polishDraft, revertDraft, reviseDraft } from '../api';
import { demoDraft, demoMaterials, demoStyles, demoSuggestions, demoTemplates, demoVersions } from '../demoData';

const tabs = [
  { key: 'content', label: '正文' },
  { key: 'suggestions', label: '修改建议' },
  { key: 'factcheck', label: '核查报告' },
  { key: 'versions', label: '版本历史' },
];

const apiReady = ref(false);
const submitting = ref(false);
const revising = ref(false);
const exporting = ref(false);
const polishing = ref(false);
const polishChanges = ref([]);
const errorMessage = ref('');
const activeTab = ref('content');
const revisionInstruction = ref('');
const exportFormat = ref('md');
const streamText = ref('');
const streamStage = ref('');
const editing = ref(false);
const editText = ref('');
const savingEdit = ref(false);
const templates = ref(demoTemplates);
const styles = ref(demoStyles);
const materials = ref(demoMaterials);
const currentDraft = ref(demoDraft);
const revisionSuggestions = ref(demoSuggestions);
const versionTree = ref(demoVersions);

const form = reactive({
  title: '关于智能办公平台试运行的通知',
  eventDesc: '公司计划启动智能办公平台试运行，用于提升公告、新闻稿和内部通知的起草效率。请各部门参与体验并反馈问题。',
  template: 'news_release',
  style: '正式',
  audience: '全体员工',
  keyFacts: [
    { name: '启动时间', value: '2026 年 8 月 20 日' },
    { name: '反馈要求', value: '试运行结束前提交问题和建议' },
  ],
  people: [{ name: '张明', title: '办公室主任' }],
  referenceMaterials: [101],
});

const FORM_STORAGE_KEY = 'eaos-compose-form';
const DRAFT_STORAGE_KEY = 'eaos-compose-draft';

function restoreForm() {
  try {
    const raw = localStorage.getItem(FORM_STORAGE_KEY);
    if (raw) Object.assign(form, JSON.parse(raw));
  } catch {
    // 忽略损坏的缓存
  }
}

function restoreDraftState() {
  try {
    const raw = localStorage.getItem(DRAFT_STORAGE_KEY);
    if (!raw) return;
    const saved = JSON.parse(raw);
    if (saved.currentDraft) currentDraft.value = saved.currentDraft;
    if (saved.revisionSuggestions) revisionSuggestions.value = saved.revisionSuggestions;
    if (saved.versionTree) versionTree.value = saved.versionTree;
    if (saved.revisionInstruction !== undefined) revisionInstruction.value = saved.revisionInstruction;
    if (saved.activeTab) activeTab.value = saved.activeTab;
  } catch {
    // 忽略损坏的缓存
  }
}

restoreForm();
restoreDraftState();

watch(
  form,
  () => {
    localStorage.setItem(FORM_STORAGE_KEY, JSON.stringify(form));
  },
  { deep: true }
);

watch(
  [currentDraft, revisionSuggestions, versionTree, revisionInstruction, activeTab],
  () => {
    localStorage.setItem(
      DRAFT_STORAGE_KEY,
      JSON.stringify({
        currentDraft: currentDraft.value,
        revisionSuggestions: revisionSuggestions.value,
        versionTree: versionTree.value,
        revisionInstruction: revisionInstruction.value,
        activeTab: activeTab.value,
      })
    );
  },
  { deep: true }
);

const draftParagraphs = computed(() => {
  return (currentDraft.value.content || '').split(/\n+/).filter(Boolean);
});

const streamParagraphs = computed(() => {
  return (streamText.value || '').split(/\n+/).filter(Boolean);
});

const stageLabel = computed(() => {
  const map = {
    extract: '正在抽取要素',
    generate: '正在生成正文',
    factcheck: '正在事实核查',
    suggest: '正在生成修改建议',
  };
  return map[streamStage.value] || streamStage.value || '';
});

const factChecks = computed(() => {
  return currentDraft.value.fact_checks?.length ? currentDraft.value.fact_checks : demoDraft.fact_checks;
});

const templateGroups = computed(() => {
  const groups = {};
  for (const t of templates.value) {
    const cat = t.category || '其他';
    (groups[cat] = groups[cat] || []).push(t);
  }
  return groups;
});

const currentTemplateCategory = computed(() => {
  const t = templates.value.find((x) => x.name === form.template);
  return t?.category || '';
});

const currentTemplateTitle = computed(() => {
  const t = templates.value.find((x) => x.name === form.template);
  return templateTitle(t);
});

function templateTitle(t) {
  if (!t) return '';
  return t.title || t.schema?.title || t.name;
}

const VersionNodeView = defineComponent({
  name: 'VersionNodeView',
  props: {
    node: { type: Object, required: true },
    currentId: { type: String, default: '' },
    onRevert: { type: Function, default: null },
  },
  setup(props) {
    return () =>
      h('div', { class: 'version-node' }, [
        h('div', { class: 'version-card' }, [
          h('div', { class: 'version-card-top' }, [
            h('div', { class: 'version-info' }, [
              h('strong', `v${props.node.version} · ${props.node.title || '草稿版本'}`),
              h('span', props.node.revision_instruction || props.node.status || '版本记录'),
            ]),
            props.onRevert && props.node.id !== props.currentId
              ? h('button', { class: 'revert-button', onClick: () => props.onRevert(props.node) }, `回退到此版本`)
              : null,
          ]),
          h('small', formatDate(props.node.created_at)),
        ]),
        props.node.children?.length
          ? h('div', { class: 'version-children' }, props.node.children.map((child) => h(VersionNodeView, { node: child, key: child.id, currentId: props.currentId, onRevert: props.onRevert })))
          : null,
      ]);
  },
});

function formatDate(value) {
  if (!value) return '';
  let text = String(value);
  if (!/(Z|[+-]\d{2}:?\d{2})$/.test(text)) text += 'Z';
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(text));
}

function badgeClass(status) {
  if (status?.includes('一致')) return 'ok';
  if (status?.includes('无法')) return 'warn';
  return 'danger';
}

function addFact() {
  form.keyFacts.push({ name: '', value: '' });
}

function removeFact(index) {
  form.keyFacts.splice(index, 1);
}

function addPerson() {
  form.people.push({ name: '', title: '' });
}

function removePerson(index) {
  form.people.splice(index, 1);
}

function resetForm() {
  form.title = '';
  form.eventDesc = '';
  form.template = templates.value[0]?.name || 'news_release';
  form.style = styles.value[0]?.name || '正式';
  form.audience = '';
  form.keyFacts = [{ name: '', value: '' }];
  form.people = [];
  form.referenceMaterials = [];
  localStorage.removeItem(FORM_STORAGE_KEY);
  errorMessage.value = '';
}

async function loadBootstrapData() {
  try {
    const [templateRows, stylePayload, materialRows] = await Promise.all([fetchTemplates(), fetchStyles(), fetchMaterials()]);
    templates.value = templateRows.length ? templateRows : demoTemplates;
    styles.value = stylePayload.styles?.length ? stylePayload.styles : demoStyles;
    materials.value = materialRows.length ? materialRows : demoMaterials;
    if (!templates.value.some((t) => t.name === form.template)) form.template = templates.value[0]?.name || form.template;
    if (!styles.value.some((s) => s.name === form.style)) form.style = styles.value[0]?.name || form.style;
    apiReady.value = true;
  } catch {
    apiReady.value = false;
  }
}

async function submitDraft() {
  errorMessage.value = '';
  if (!form.eventDesc.trim()) {
    errorMessage.value = '请先填写核心事项。';
    return;
  }

  const payload = {
    title: form.title,
    eventDesc: form.eventDesc,
    keyFacts: form.keyFacts.filter((item) => item.name || item.value),
    people: form.people.filter((item) => item.name || item.title),
    audience: form.audience,
    style: form.style,
    styles: [form.style],
    template: form.template,
    referenceMaterials: form.referenceMaterials,
  };

  submitting.value = true;
  streamText.value = '';
  streamStage.value = 'extract';
  try {
    await createDraftStream(payload, (event) => {
      if (event.type === 'status') {
        streamStage.value = event.stage;
      } else if (event.type === 'delta') {
        streamText.value += event.text;
      } else if (event.type === 'error') {
        const detail = event.detail || {};
        errorMessage.value = typeof detail.message === 'string' ? detail.message : JSON.stringify(detail);
      } else if (event.type === 'done') {
        applyGeneratedDraft(event);
      }
    });
  } catch (error) {
    errorMessage.value = `${error.message}；当前仍保留演示草稿。`;
  } finally {
    submitting.value = false;
    streamStage.value = '';
  }
}

async function applyGeneratedDraft(result) {
  polishChanges.value = [];
  if (streamText.value) {
    currentDraft.value = {
      ...currentDraft.value,
      id: result.versionId,
      title: form.title || '未命名草稿',
      template_name: form.template,
      style: form.style,
      content: streamText.value,
      version: 1,
      status: '已生成',
      model: result.model,
      created_at: result.generatedAt,
      fact_checks: result.factCheckReport,
    };
    streamText.value = '';
  }
  revisionSuggestions.value = result.revisionSuggestions?.length ? result.revisionSuggestions : demoSuggestions;
  try {
    currentDraft.value = await fetchDraft(result.versionId);
    versionTree.value = await fetchVersions(result.versionId);
  } catch {
    versionTree.value = { ...demoVersions, id: result.versionId, title: form.title || '未命名草稿' };
  }
  activeTab.value = 'content';
  apiReady.value = true;
}

async function submitPolish() {
  if (!currentDraft.value.id) {
    errorMessage.value = '请先生成草稿。';
    return;
  }
  polishing.value = true;
  errorMessage.value = '';
  try {
    const result = await polishDraft(currentDraft.value.id);
    if (result.versionId) {
      await loadDraft(result.versionId);
    } else {
      currentDraft.value = { ...currentDraft.value, content: result.polished };
    }
    polishChanges.value = result.changes || [];
    activeTab.value = 'suggestions';
  } catch (error) {
    errorMessage.value = `润色失败：${error.message}`;
  } finally {
    polishing.value = false;
  }
}

function applySuggestion(text) {
  const current = revisionInstruction.value.trim();
  revisionInstruction.value = current ? current + '\n' + text : text;
}

function startEdit() {
  if (!currentDraft.value.id) {
    errorMessage.value = '请先生成草稿。';
    return;
  }
  editText.value = currentDraft.value.content || '';
  editing.value = true;
  errorMessage.value = '';
}

function cancelEdit() {
  editing.value = false;
  editText.value = '';
}

async function saveEdit() {
  if (!editText.value.trim()) {
    errorMessage.value = '正文不能为空。';
    return;
  }
  savingEdit.value = true;
  errorMessage.value = '';
  try {
    const result = await editDraftContent(currentDraft.value.id, editText.value);
    editing.value = false;
    editText.value = '';
    revisionSuggestions.value = result.diffSummary || ['已手动编辑正文'];
    await loadDraft(result.versionId);
  } catch (error) {
    errorMessage.value = `保存失败：${error.message}`;
  } finally {
    savingEdit.value = false;
  }
}

async function submitRevision() {
  errorMessage.value = '';
  if (!currentDraft.value.id) {
    errorMessage.value = '请先生成草稿。';
    return;
  }
  const instruction = revisionInstruction.value.trim();
  if (!instruction) {
    errorMessage.value = '请输入修改指令。';
    return;
  }
  revising.value = true;
  try {
    const result = await reviseDraft(currentDraft.value.id, instruction);
    revisionInstruction.value = '';
    await loadDraft(result.versionId);
    if (result.diffSummary?.length) revisionSuggestions.value = result.diffSummary;
  } catch (error) {
    errorMessage.value = `修改失败：${error.message}`;
  } finally {
    revising.value = false;
  }
}

async function revertToVersion(target) {
  if (!currentDraft.value.id || target.id === currentDraft.value.id) return;
  if (!window.confirm(`确定回退到 v${target.version}？将基于当前草稿生成一个新版本。`)) return;
  errorMessage.value = '';
  revising.value = true;
  try {
    const result = await revertDraft(currentDraft.value.id, target.id);
    revisionSuggestions.value = result.diffSummary || ['已回退至目标版本'];
    await loadDraft(result.versionId);
  } catch (error) {
    errorMessage.value = `回退失败：${error.message}`;
  } finally {
    revising.value = false;
  }
}

async function loadDraft(versionId) {
  polishChanges.value = [];
  try {
    currentDraft.value = await fetchDraft(versionId);
    versionTree.value = await fetchVersions(versionId);
  } catch {
    versionTree.value = { ...demoVersions, id: versionId };
  }
  activeTab.value = 'content';
  apiReady.value = true;
}

async function submitExport() {
  errorMessage.value = '';
  if (!currentDraft.value.id) {
    errorMessage.value = '请先生成草稿。';
    return;
  }
  exporting.value = true;
  try {
    const result = await exportDraft(currentDraft.value.id, exportFormat.value);
    triggerDownload(result.download_url);
  } catch (error) {
    errorMessage.value = `导出失败：${error.message}`;
  } finally {
    exporting.value = false;
  }
}

function triggerDownload(url) {
  const filename = decodeURIComponent(url.split('/').filter(Boolean).pop() || 'draft');
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

onMounted(loadBootstrapData);
</script>