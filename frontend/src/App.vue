<template>
  <div class="app-shell">
    <header class="topbar">
      <div>
        <p class="eyebrow">企业 AI 办公助手</p>
        <h1>公告与新闻稿智能撰写</h1>
      </div>
      <div class="status-pill" :class="{ online: apiReady }">
        <span></span>{{ apiReady ? '后端已连接' : '演示模式' }}
      </div>
    </header>

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
            <span>模板</span>
            <select v-model="form.template">
              <option v-for="template in templates" :key="template.name" :value="template.name">
                {{ template.category }} / {{ template.name }}
              </option>
            </select>
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
            <label class="upload-button">
              上传
              <input type="file" @change="handleUpload" />
            </label>
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
          <div class="meta-stack">
            <span>v{{ currentDraft.version || 1 }}</span>
            <span>{{ currentDraft.status || '已生成' }}</span>
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
          <p v-for="(paragraph, index) in draftParagraphs" :key="index">{{ paragraph }}</p>
        </article>

        <div v-else-if="activeTab === 'suggestions'" class="list-panel">
          <div v-for="(suggestion, index) in revisionSuggestions" :key="index" class="suggestion-item">
            <span>{{ index + 1 }}</span>
            <p>{{ suggestion }}</p>
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
  </div>
</template>

<script setup>
import { computed, defineComponent, h, onMounted, reactive, ref, watch } from 'vue';
import { createDraft, exportDraft, fetchDraft, fetchMaterials, fetchStyles, fetchTemplates, fetchVersions, revertDraft, reviseDraft, uploadMaterial } from './api';
import { demoDraft, demoMaterials, demoStyles, demoSuggestions, demoTemplates, demoVersions } from './demoData';

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
const errorMessage = ref('');
const activeTab = ref('content');
const revisionInstruction = ref('');
const exportFormat = ref('md');
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

const factChecks = computed(() => {
  return currentDraft.value.fact_checks?.length ? currentDraft.value.fact_checks : demoDraft.fact_checks;
});

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

  submitting.value = true;
  try {
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
    const result = await createDraft(payload);
    currentDraft.value = {
      ...currentDraft.value,
      id: result.versionId,
      title: form.title || '未命名草稿',
      template_name: form.template,
      style: form.style,
      content: result.draft,
      version: 1,
      status: '已生成',
      model: result.model,
      created_at: result.generatedAt,
      fact_checks: result.factCheckReport,
    };
    revisionSuggestions.value = result.revisionSuggestions?.length ? result.revisionSuggestions : demoSuggestions;
    try {
      currentDraft.value = await fetchDraft(result.versionId);
      versionTree.value = await fetchVersions(result.versionId);
    } catch {
      versionTree.value = { ...demoVersions, id: result.versionId, title: form.title || '未命名草稿' };
    }
    activeTab.value = 'content';
    apiReady.value = true;
  } catch (error) {
    errorMessage.value = `${error.message}；当前仍保留演示草稿。`;
  } finally {
    submitting.value = false;
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

async function handleUpload(event) {
  const [file] = event.target.files || [];
  if (!file) return;
  try {
    const material = await uploadMaterial(file);
    materials.value = [material, ...materials.value];
    form.referenceMaterials.push(material.id);
    apiReady.value = true;
  } catch (error) {
    errorMessage.value = `素材上传失败：${error.message}`;
  } finally {
    event.target.value = '';
  }
}

onMounted(loadBootstrapData);
</script>
