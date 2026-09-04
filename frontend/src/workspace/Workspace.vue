<template>
  <main ref="workspaceRoot" class="workspace-page">
    <section class="workspace-hero" aria-labelledby="workspace-title">
      <div class="hero-copy">
        <p class="eyebrow">公告与新闻稿智能撰写</p>
        <h2 id="workspace-title">
          把发布事项
          <span class="inline-image" aria-hidden="true"></span>
          变成可审、可改、可导出的正式稿件
        </h2>
      </div>
      <div class="hero-actions" aria-label="主要操作">
        <a class="primary-button hero-button" href="#compose-panel">开始撰写</a>
        <a class="ghost-button hero-link" href="#draft-panel">查看草稿</a>
      </div>
    </section>

    <section v-if="loadFailed" class="compose-panel load-failed-banner" aria-label="数据加载失败">
      <p>后端数据加载失败，当前页面无法获取模板、文风与素材。请检查服务状态后重试。</p>
      <button class="ghost-button" type="button" @click="loadBootstrapData">重试加载</button>
    </section>

    <section class="workspace" aria-label="公告撰写工作区">
    <section id="compose-panel" class="compose-panel motion-card" aria-label="创建草稿">
      <div class="section-title compose-panel-heading">
        <h2>创建草稿</h2>
        <button class="ghost-button" type="button" @click="resetForm">重置</button>
      </div>

      <section class="compose-group" aria-labelledby="writing-elements-title">
        <div class="compose-group-head">
          <h3 id="writing-elements-title">撰写要素</h3>
          <span>说明发布的核心事项</span>
        </div>
      <label class="field">
        <span>标题</span>
        <input v-model="form.title" placeholder="例如：关于智能办公平台试运行的通知" />
      </label>

      <label class="field">
        <span>核心事项</span>
        <textarea v-model="form.eventDesc" rows="5" placeholder="描述事件背景、发布时间、面向对象、关键动作"></textarea>
      </label>
      </section>

      <section class="compose-group" aria-labelledby="template-style-title">
        <div class="compose-group-head">
          <h3 id="template-style-title">模板与文风</h3>
          <span>匹配发布场景与渠道</span>
        </div>
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

      <div class="subsection compact-block">
        <div class="section-title compact">
          <h3>并行文风</h3>
          <small class="muted-hint">生成后可在右侧对比采用</small>
        </div>
        <div class="style-pick-list">
          <label v-for="style in styles" :key="style.name" class="style-check-row">
            <input v-model="form.styles" type="checkbox" :value="style.name" :disabled="style.name === form.style" />
            <span>{{ style.name }}</span>
          </label>
        </div>
      </div>
      </section>

      <section class="compose-group" aria-labelledby="facts-title">
        <div class="compose-group-head">
          <h3 id="facts-title">关键信息</h3>
          <span>为生成和核查提供依据</span>
        </div>
      <label class="field">
        <span>受众</span>
        <input v-model="form.audience" placeholder="例如：全体员工、媒体、合作伙伴" />
      </label>

      <div class="subsection">
        <div class="section-title compact">
          <h3>关键要素</h3>
          <button class="icon-button" type="button" title="添加要素" aria-label="添加要素" @click="addFact">+</button>
        </div>
        <div v-for="(fact, index) in form.keyFacts" :key="index" class="inline-row">
          <input v-model="fact.name" placeholder="要素名" />
          <input v-model="fact.value" placeholder="要素值" />
          <button class="icon-button danger" type="button" title="删除要素" aria-label="删除要素" @click="removeFact(index)">×</button>
        </div>
      </div>

      <div class="subsection">
        <div class="section-title compact">
          <h3>相关人员</h3>
          <button class="icon-button" type="button" title="添加人员" aria-label="添加人员" @click="addPerson">+</button>
        </div>
        <div v-for="(person, index) in form.people" :key="index" class="inline-row">
          <input v-model="person.name" placeholder="姓名" />
          <input v-model="person.title" placeholder="职务" />
          <button class="icon-button danger" type="button" title="删除人员" aria-label="删除人员" @click="removePerson(index)">×</button>
        </div>
      </div>
      </section>

      <section class="compose-group materials-group" aria-labelledby="materials-title">
        <div class="compose-group-head">
          <h3 id="materials-title">参考素材</h3>
          <span>选择可引用的资料</span>
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
        <div class="material-search">
          <div class="export-input-row">
            <input v-model="materialQuery" placeholder="检索素材引用，例如 上线时间、机构名称" />
            <button class="ghost-button" type="button" :disabled="searchingMaterials" @click="submitMaterialSearch">
              {{ searchingMaterials ? '检索中...' : '检索' }}
            </button>
          </div>
          <div v-if="materialHits.length" class="material-hit-list">
            <div v-for="hit in materialHits" :key="hit.id" class="material-hit">
              <div class="fact-topline">
                <strong>{{ hit.filename }} · 片段 {{ hit.chunk_index + 1 }}</strong>
                <span>{{ hit.score }}</span>
              </div>
              <p>{{ hit.text }}</p>
              <button class="apply-button" type="button" @click="applyMaterialHit(hit)">引用</button>
            </div>
          </div>
        </div>
      </div>
      </section>

      <div class="compose-submit">
        <button class="primary-button" type="button" :disabled="submitting" @click="submitDraft">
          {{ submitting ? '生成中...' : '生成草稿' }}
        </button>
        <p v-if="errorMessage" class="error-text" role="alert">{{ errorMessage }}</p>
      </div>
    </section>

    <section id="draft-panel" class="draft-panel motion-card">
      <div class="draft-header">
        <div>
          <p class="eyebrow">草稿查看</p>
          <h2>{{ currentDraft.title || '未命名草稿' }}</h2>
        </div>
        <div class="draft-actions">
          <div v-if="currentDraft.id" class="status-flow">
            <button v-for="action in statusActions" :key="action.status" class="ghost-button" type="button" :disabled="statusUpdating" @click="submitStatus(action.status)">
              {{ action.label }}
            </button>
          </div>
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
            <option value="pdf">PDF (.pdf)</option>
          </select>
          <button class="primary-button export-submit" type="button" :disabled="exporting || !currentDraft.id" @click="submitExport">
            {{ exporting ? '导出中...' : '导出' }}
          </button>
        </div>
        <div v-if="exportHistory.length" class="export-history">
          <a v-for="item in exportHistory" :key="item.id" :title="item.download_url" @click.prevent="downloadExport(item)">
            {{ item.format.toUpperCase() }} · {{ formatDate(item.created_at) }}
          </a>
        </div>
      </div>

      <div class="tabs" role="tablist" aria-label="草稿查看内容">
        <button
          v-for="tab in tabs"
          :id="`draft-tab-${tab.key}`"
          :key="tab.key"
          :aria-controls="`draft-panel-${tab.key}`"
          :aria-selected="activeTab === tab.key"
          :class="{ active: activeTab === tab.key }"
          :tabindex="activeTab === tab.key ? 0 : -1"
          role="tab"
          type="button"
          @click="activeTab = tab.key"
        >
          {{ tab.label }}
        </button>
      </div>

      <article
        v-if="activeTab === 'content'"
        id="draft-panel-content"
        class="draft-content"
        role="tabpanel"
        aria-labelledby="draft-tab-content"
      >
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

      <div
        v-else-if="activeTab === 'suggestions'"
        id="draft-panel-suggestions"
        class="list-panel"
        role="tabpanel"
        aria-labelledby="draft-tab-suggestions"
      >
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
        <section v-if="variants.length" class="variant-section" aria-labelledby="variant-title">
          <div class="variant-section-head">
            <div>
              <h3 id="variant-title">多文风备选</h3>
              <p>可将任一备选文风作为新的正文版本。</p>
            </div>
          </div>
          <div v-for="variant in variants" :key="variant.style" class="variant-card">
            <div class="fact-topline">
              <strong>{{ variant.style }}</strong>
              <button class="apply-button" type="button" :disabled="savingEdit || !currentDraft.id" @click="useVariant(variant)">采用</button>
            </div>
            <pre>{{ variant.content }}</pre>
          </div>
        </section>
      </div>

      <div
        v-else-if="activeTab === 'factcheck'"
        id="draft-panel-factcheck"
        class="list-panel"
        role="tabpanel"
        aria-labelledby="draft-tab-factcheck"
      >
        <div class="list-toolbar">
          <button class="ghost-button" type="button" :disabled="!currentDraft.id" @click="refreshFactcheck">刷新核查报告</button>
        </div>
        <div v-for="(item, index) in factChecks" :key="index" class="fact-item">
          <div class="fact-topline">
            <strong>{{ item.claim }}</strong>
            <span :class="['check-badge', badgeClass(item.status)]">{{ item.status }}</span>
          </div>
          <p>{{ item.basis || '暂无依据说明' }}</p>
          <small v-if="item.suggestion">{{ item.suggestion }}</small>
        </div>
      </div>

      <div
        v-else
        id="draft-panel-versions"
        class="version-tree"
        role="tabpanel"
        aria-labelledby="draft-tab-versions"
      >
        <VersionNodeView :node="versionTree" :current-id="currentDraft.id" :on-revert="revertToVersion" />
      </div>
    </section>
    </section>
  </main>
</template>

<script setup>
import { computed, defineComponent, h, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import {
  createDraftStream,
  downloadFile,
  editDraftContent,
  exportDraft,
  fetchDraft,
  fetchExportHistory,
  fetchFactCheckReport,
  fetchMaterials,
  fetchStyles,
  fetchTemplates,
  fetchVersions,
  polishDraft,
  revertDraft,
  reviseDraft,
  searchMaterials,
  updateDraftStatus,
} from '../api';
import { demoDraft, demoMaterials, demoStyles, demoSuggestions, demoTemplates, demoVersions } from '../demoData';

gsap.registerPlugin(ScrollTrigger);

const tabs = [
  { key: 'content', label: '正文' },
  { key: 'suggestions', label: '修改建议' },
  { key: 'factcheck', label: '核查报告' },
  { key: 'versions', label: '版本历史' },
];

const workspaceRoot = ref(null);
const apiReady = ref(false);
const loadFailed = ref(false);
const submitting = ref(false);
const revising = ref(false);
const exporting = ref(false);
const polishing = ref(false);
const statusUpdating = ref(false);
const polishChanges = ref([]);
const variants = ref([]);
const exportHistory = ref([]);
const materialQuery = ref('');
const materialHits = ref([]);
const searchingMaterials = ref(false);
const errorMessage = ref('');
const activeTab = ref('content');
const revisionInstruction = ref('');
const exportFormat = ref('md');
const streamText = ref('');
const streamStage = ref('');
const editing = ref(false);
const editText = ref('');
const savingEdit = ref(false);
// 演示数据仅在开发环境启用（Q19）：生产环境接口失败时显示错误态 + 重试
const IS_DEV = import.meta.env.DEV;
const templates = ref(IS_DEV ? demoTemplates : []);
const styles = ref(IS_DEV ? demoStyles : []);
const materials = ref(IS_DEV ? demoMaterials : []);
const currentDraft = ref(IS_DEV ? demoDraft : { fact_checks: [] });
const revisionSuggestions = ref(IS_DEV ? demoSuggestions : []);
const versionTree = ref(IS_DEV ? demoVersions : null);

const form = reactive({
  title: '关于智能办公平台试运行的通知',
  eventDesc: '公司计划启动智能办公平台试运行，用于提升公告、新闻稿和内部通知的起草效率。请各部门参与体验并反馈问题。',
  template: 'news_release',
  style: '正式',
  styles: ['正式', '严谨', '活泼'],
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
    if (tabs.some((tab) => tab.key === saved.activeTab)) activeTab.value = saved.activeTab;
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
  () => form.style,
  (style) => {
    if (!Array.isArray(form.styles)) form.styles = [];
    if (style && !form.styles.includes(style)) form.styles.unshift(style);
  }
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
  return currentDraft.value.fact_checks?.length
    ? currentDraft.value.fact_checks
    : (IS_DEV ? demoDraft.fact_checks : []);
});

const statusActions = computed(() => {
  const status = currentDraft.value.status || '草稿';
  if (status === '草稿' || status === '已生成') return [{ label: '送审', status: '审阅' }];
  if (status === '审阅' || status === '待审核') {
    return [
      { label: '退回草稿', status: '草稿' },
      { label: '发布', status: '发布' },
    ];
  }
  return [];
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
  form.styles = [form.style];
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
    templates.value = templateRows.length ? templateRows : (IS_DEV ? demoTemplates : []);
    styles.value = stylePayload.styles?.length ? stylePayload.styles : (IS_DEV ? demoStyles : []);
    materials.value = materialRows.length ? materialRows : (IS_DEV ? demoMaterials : []);
    if (!templates.value.some((t) => t.name === form.template)) form.template = templates.value[0]?.name || form.template;
    if (!styles.value.some((s) => s.name === form.style)) form.style = styles.value[0]?.name || form.style;
    if (!Array.isArray(form.styles) || !form.styles.length) form.styles = [form.style];
    if (!form.styles.includes(form.style)) form.styles.unshift(form.style);
    apiReady.value = true;
    loadFailed.value = false;
  } catch {
    apiReady.value = false;
    // 生产环境展示错误态（配合重试按钮），开发环境仍回落演示数据
    loadFailed.value = !IS_DEV;
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
    styles: form.styles?.length ? form.styles : [form.style],
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
  variants.value = result.variants || [];
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
  revisionSuggestions.value = result.revisionSuggestions?.length ? result.revisionSuggestions : (IS_DEV ? demoSuggestions : []);
  try {
    currentDraft.value = await fetchDraft(result.versionId);
    versionTree.value = await fetchVersions(result.versionId);
    exportHistory.value = await fetchExportHistory(result.versionId);
  } catch {
    versionTree.value = IS_DEV
      ? { ...demoVersions, id: result.versionId, title: form.title || '未命名草稿' }
      : { id: result.versionId, title: form.title || '未命名草稿' };
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

async function submitStatus(status) {
  if (!currentDraft.value.id) return;
  statusUpdating.value = true;
  errorMessage.value = '';
  try {
    currentDraft.value = await updateDraftStatus(currentDraft.value.id, status);
  } catch (error) {
    errorMessage.value = `状态流转失败：${error.message}`;
  } finally {
    statusUpdating.value = false;
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
    exportHistory.value = await fetchExportHistory(versionId);
  } catch {
    versionTree.value = IS_DEV ? { ...demoVersions, id: versionId } : { id: versionId };
  }
  activeTab.value = 'content';
  apiReady.value = true;
}

async function refreshFactcheck() {
  if (!currentDraft.value.id) return;
  errorMessage.value = '';
  try {
    const report = await fetchFactCheckReport(currentDraft.value.id);
    currentDraft.value = { ...currentDraft.value, fact_checks: report };
  } catch (error) {
    errorMessage.value = `核查报告刷新失败：${error.message}`;
  }
}

async function useVariant(variant) {
  if (!variant?.content || !currentDraft.value.id) return;
  savingEdit.value = true;
  errorMessage.value = '';
  try {
    const result = await editDraftContent(currentDraft.value.id, variant.content);
    revisionSuggestions.value = [`已采用「${variant.style}」文风版本作为当前正文。`];
    await loadDraft(result.versionId);
  } catch (error) {
    errorMessage.value = `采用文风版本失败：${error.message}`;
  } finally {
    savingEdit.value = false;
  }
}

async function submitMaterialSearch() {
  const query = (materialQuery.value || form.eventDesc || form.title).trim();
  if (!query) {
    errorMessage.value = '请输入素材检索关键词。';
    return;
  }
  searchingMaterials.value = true;
  errorMessage.value = '';
  try {
    materialHits.value = await searchMaterials(query, form.referenceMaterials, 6);
    if (!materialHits.value.length) errorMessage.value = '没有检索到匹配素材片段。';
  } catch (error) {
    errorMessage.value = `素材检索失败：${error.message}`;
  } finally {
    searchingMaterials.value = false;
  }
}

function applyMaterialHit(hit) {
  const text = `参考素材「${hit.filename}」片段：${hit.text}`;
  form.eventDesc = form.eventDesc ? `${form.eventDesc}\n${text}` : text;
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
    exportHistory.value = await fetchExportHistory(currentDraft.value.id);
  } catch (error) {
    errorMessage.value = `导出失败：${error.message}`;
  } finally {
    exporting.value = false;
  }
}

function downloadExport(item) {
  downloadFile(item.download_url).catch((error) => {
    errorMessage.value = `下载失败：${error.message}`;
  });
}

async function triggerDownload(url) {
  try {
    await downloadFile(url);
  } catch (error) {
    errorMessage.value = `下载失败：${error.message}`;
  }
}

function initWorkspaceMotion() {
  const root = workspaceRoot.value;
  if (!root || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  const ctx = gsap.context(() => {
    gsap.from('.workspace-hero .eyebrow, .workspace-hero h2, .hero-actions', {
      y: 28,
      opacity: 0,
      duration: 0.9,
      ease: 'power3.out',
      stagger: 0.08,
    });

    gsap.from('.motion-card', {
      scrollTrigger: {
        trigger: '.workspace',
        start: 'top 76%',
      },
      y: 42,
      opacity: 0,
      duration: 0.8,
      ease: 'power3.out',
      stagger: 0.12,
    });

    gsap.to('.hero-copy', {
      scrollTrigger: {
        trigger: '.workspace-hero',
        start: 'top top+=96',
        end: 'bottom top+=140',
        scrub: true,
      },
      opacity: 0.28,
      y: -18,
      ease: 'none',
    });
  }, root);

  return () => ctx.revert();
}

let teardownMotion;

onMounted(() => {
  loadBootstrapData();
  teardownMotion = initWorkspaceMotion();
});

onBeforeUnmount(() => {
  if (typeof teardownMotion === 'function') teardownMotion();
});
</script>

<style scoped>
.load-failed-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  border: 1px solid #fca5a5;
  background: #fef2f2;
  color: #991b1b;
}
.load-failed-banner p { margin: 0; }
</style>
