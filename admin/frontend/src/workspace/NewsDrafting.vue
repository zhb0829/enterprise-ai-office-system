<template>
  <div class="drafting-page feature-page">
    <div class="page-breadcrumb">
      <router-link to="/workspace"><AppIcon name="arrow-left" :size="16" /> 工作台</router-link>
      <span>/</span>
      <span>公告新闻撰写</span>
    </div>

    <section class="feature-hero tone-cyan drafting-hero">
      <div class="feature-hero-copy">
        <div class="feature-icon large"><AppIcon name="pen" :size="27" /></div>
        <p class="eyebrow">AI WORKSPACE · 内容创作</p>
        <h1>企业公告与新闻稿智能撰写</h1>
        <p>从已填写要素和授权素材生成可追溯的初稿，并同步完成事实核查。</p>
      </div>
      <div class="hero-stat drafting-hero-stat">
        <span>本场景已生成</span>
        <strong>846</strong>
        <small>份企业文稿</small>
      </div>
    </section>

    <div v-if="notice" class="drafting-notice" :class="notice.type" role="status" aria-live="polite">
      <AppIcon :name="notice.type === 'error' ? 'bell' : 'check'" :size="17" />
      <span>{{ notice.text }}</span>
    </div>

    <div class="drafting-layout">
      <section class="drafting-form-panel" aria-labelledby="drafting-input-title">
        <div class="drafting-section-heading">
          <div>
            <p class="eyebrow">STEP 01</p>
            <h2 id="drafting-input-title">填写生成要素</h2>
          </div>
          <button class="drafting-text-button" type="button" @click="resetForm">重置</button>
        </div>

        <label class="drafting-field">
          <span>文稿标题</span>
          <input v-model="form.title" placeholder="例如：关于智能办公平台试运行的通知" />
        </label>

        <fieldset class="drafting-fieldset">
          <legend>选择模板</legend>
          <div class="template-choice-grid">
            <button
              v-for="template in templateOptions"
              :key="template.key"
              class="template-choice"
              :class="{ selected: form.template === template.key }"
              type="button"
              :aria-pressed="form.template === template.key"
              @click="form.template = template.key"
            >
              <AppIcon :name="template.icon" :size="18" />
              <span>{{ template.label }}</span>
              <small>{{ template.hint }}</small>
            </button>
          </div>
        </fieldset>

        <div class="drafting-field-row">
          <label class="drafting-field">
            <span>发布渠道</span>
            <select v-model="form.channel" @change="applyChannelStyle">
              <option v-for="channel in channels" :key="channel" :value="channel">{{ channel }}</option>
            </select>
          </label>
          <label class="drafting-field">
            <span>目标受众</span>
            <input v-model="form.audience" placeholder="例如：全体员工" />
          </label>
        </div>

        <fieldset class="drafting-fieldset">
          <legend>文风适配</legend>
          <div class="style-choice-row">
            <button
              v-for="style in styleOptions"
              :key="style.key"
              class="style-choice"
              :class="{ selected: form.style === style.label }"
              type="button"
              :aria-pressed="form.style === style.label"
              @click="form.style = style.label"
            >
              {{ style.label }}
            </button>
          </div>
          <p class="drafting-helper">已按“{{ form.channel }}”推荐{{ recommendedStyle }}文风，可手动调整。</p>
        </fieldset>

        <label class="drafting-field">
          <span>核心事项</span>
          <textarea
            id="event-desc"
            v-model="form.eventDesc"
            rows="5"
            placeholder="说明事件背景、时间、范围、行动要求和需要重点传达的信息。"
            aria-describedby="event-desc-help"
          ></textarea>
          <small id="event-desc-help" class="drafting-helper">请将日期、金额、人名等关键事实明确写入要素或授权素材。</small>
        </label>

        <fieldset class="drafting-fieldset">
          <div class="drafting-subhead">
            <legend>关键事实</legend>
            <button class="drafting-text-button" type="button" @click="addFact">添加要素</button>
          </div>
          <p class="drafting-helper">数据、金额、日期和机构名称将以这里的内容作为核查依据。</p>
          <div v-for="(fact, index) in form.keyFacts" :key="`fact-${index}`" class="drafting-inline-fields">
            <input v-model="fact.name" placeholder="要素名称，例如：生效日期" :aria-label="`第 ${index + 1} 个事实名称`" />
            <input v-model="fact.value" placeholder="要素值，例如：2026 年 8 月 20 日" :aria-label="`第 ${index + 1} 个事实内容`" />
            <button v-if="form.keyFacts.length > 1" class="drafting-remove-button" type="button" :aria-label="`删除第 ${index + 1} 个事实`" @click="removeFact(index)">删除</button>
          </div>
        </fieldset>

        <fieldset class="drafting-fieldset">
          <div class="drafting-subhead">
            <legend>相关人员</legend>
            <button class="drafting-text-button" type="button" @click="addPerson">添加人员</button>
          </div>
          <div v-for="(person, index) in form.people" :key="`person-${index}`" class="drafting-inline-fields">
            <input v-model="person.name" placeholder="姓名" :aria-label="`第 ${index + 1} 个人员姓名`" />
            <input v-model="person.title" placeholder="职务或头衔" :aria-label="`第 ${index + 1} 个人员职务`" />
            <button class="drafting-remove-button" type="button" :aria-label="`删除第 ${index + 1} 个人员`" @click="removePerson(index)">删除</button>
          </div>
          <p v-if="!form.people.length" class="drafting-empty-inline">暂未添加相关人员。</p>
        </fieldset>

        <fieldset class="drafting-fieldset">
          <legend>授权参考素材</legend>
          <p class="drafting-helper">默认不联网抓取未授权内容；仅选中的素材会参与生成和核验。</p>
          <div class="material-choice-list">
            <label v-for="material in materials" :key="material.id" class="material-choice">
              <input v-model="form.referenceMaterials" type="checkbox" :value="material.id" />
              <span class="material-choice-name"><AppIcon name="file" :size="16" /> {{ material.filename }}</span>
              <small>{{ material.status || '已授权' }}</small>
            </label>
            <p v-if="!materials.length" class="drafting-empty-inline">暂未接入参考素材，可先根据已填写要素生成初稿。</p>
          </div>
        </fieldset>

        <button class="drafting-generate-button" type="button" :disabled="isGenerating" @click="submitDraft">
          <AppIcon :name="isGenerating ? 'clock' : 'sparkles'" :size="18" />
          {{ isGenerating ? stageLabel : '生成初稿并核查事实' }}
        </button>
      </section>

      <section class="drafting-result-panel" aria-labelledby="drafting-result-title">
        <div class="drafting-result-header">
          <div>
            <p class="eyebrow">STEP 02</p>
            <h2 id="drafting-result-title">{{ currentDraft.title || '初稿工作区' }}</h2>
            <p class="drafting-version-meta">v{{ currentDraft.version || 1 }} · {{ currentDraft.model || '待生成' }} · {{ draftTime }}</p>
          </div>
          <div class="drafting-header-actions">
            <button class="drafting-icon-action" type="button" title="润色初稿" aria-label="润色初稿" :disabled="isPolishing || !currentDraft.id" @click="submitPolish">
              <AppIcon :name="isPolishing ? 'clock' : 'sparkles'" :size="17" />
            </button>
            <button class="drafting-icon-action" type="button" title="编辑正文" aria-label="编辑正文" :disabled="!currentDraft.id" @click="startEdit">
              <AppIcon name="pen" :size="17" />
            </button>
            <select v-model="exportFormat" class="drafting-export-select" aria-label="导出格式">
              <option value="md">MD</option>
              <option value="docx">DOCX</option>
              <option value="pdf">PDF</option>
            </select>
            <button class="drafting-export-button" type="button" :disabled="isExporting || !currentDraft.id" @click="submitExport">
              {{ isExporting ? '导出中' : '导出' }}
            </button>
          </div>
        </div>

        <div class="drafting-summary-strip">
          <div><span>模板</span><strong>{{ selectedTemplate.label }}</strong></div>
          <div><span>文风</span><strong>{{ form.style }}</strong></div>
          <div><span>核查项</span><strong>{{ factChecks.length }}</strong></div>
          <div :class="{ warning: unresolvedCount }"><span>待核实</span><strong>{{ unresolvedCount }}</strong></div>
        </div>

        <div class="drafting-review-banner" :class="{ blocked: unresolvedCount }">
          <div>
            <AppIcon :name="unresolvedCount ? 'bell' : 'check'" :size="18" />
            <div>
              <strong>{{ unresolvedCount ? `存在 ${unresolvedCount} 项待核实信息` : '核查结果已处理，可进入人工审核' }}</strong>
              <span>{{ unresolvedCount ? '请补充依据并重新生成，待核实信息不能提交审核。' : '发布前仍须由人工审阅并完成签发。' }}</span>
            </div>
          </div>
          <button class="drafting-review-button" type="button" :disabled="unresolvedCount > 0 || !currentDraft.id" @click="submitForReview">
            {{ reviewSubmitted ? '已提交审核' : '提交审核' }}
          </button>
        </div>

        <div class="drafting-tabs" role="tablist" aria-label="初稿内容">
          <button v-for="tab in tabs" :key="tab.key" type="button" role="tab" :aria-selected="activeTab === tab.key" :class="{ active: activeTab === tab.key }" @click="activeTab = tab.key">
            {{ tab.label }}<span v-if="tab.key === 'factcheck' && unresolvedCount" class="drafting-tab-count">{{ unresolvedCount }}</span>
          </button>
        </div>

        <div class="drafting-tab-panel">
          <div v-if="activeTab === 'content'" class="drafting-content-view">
            <div v-if="isGenerating" class="drafting-streaming-state" aria-live="polite">
              <span class="drafting-stream-dot"></span>
              <strong>{{ stageLabel }}</strong>
              <span>正在按模板组织内容并核对用户提供的关键事实。</span>
            </div>
            <div v-else-if="isEditing" class="drafting-editor">
              <label for="draft-content-editor">编辑初稿正文</label>
              <textarea id="draft-content-editor" v-model="editingContent" rows="18"></textarea>
              <div class="drafting-editor-actions">
                <button class="drafting-secondary-button" type="button" @click="cancelEdit">取消</button>
                <button class="drafting-primary-button" type="button" :disabled="isSavingEdit" @click="saveEdit">{{ isSavingEdit ? '保存中' : '保存并生成版本' }}</button>
              </div>
            </div>
            <article v-else class="drafting-article">
              <template v-if="displayParagraphs.length">
                <p v-for="(paragraph, index) in displayParagraphs" :key="index">
                  <template v-for="(segment, segmentIndex) in highlightSegments(paragraph)" :key="segmentIndex">
                    <mark v-if="segment.unverified">{{ segment.text }}</mark>
                    <template v-else>{{ segment.text }}</template>
                  </template>
                </p>
              </template>
              <div v-else class="drafting-empty-state">
                <AppIcon name="pen" :size="22" />
                <strong>等待生成初稿</strong>
                <p>填写左侧要素后，系统将在这里展示模板化初稿和核查结果。</p>
              </div>
            </article>
          </div>

          <section v-else-if="activeTab === 'factcheck'" class="drafting-factcheck-view">
            <div class="factcheck-intro">
              <strong>事实核查报告</strong>
              <span>核对范围仅限用户输入要素、已授权素材及授权公开来源。</span>
            </div>
            <div v-if="factChecks.length" class="factcheck-table-wrap">
              <table class="factcheck-table">
                <thead><tr><th>事实断言</th><th>判定</th><th>依据</th><th>建议</th></tr></thead>
                <tbody>
                  <tr v-for="(item, index) in factChecks" :key="index">
                    <td>{{ item.claim }}</td>
                    <td><span class="fact-status" :class="factStatusClass(item.status)">{{ readableStatus(item.status) }}</span></td>
                    <td>{{ item.basis || '暂无可用依据' }}</td>
                    <td>{{ item.suggestion || '无需处理' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-else class="drafting-empty-state"><AppIcon name="search" :size="22" /><strong>暂无核查结果</strong><p>生成初稿后会同步输出关键事实核查报告。</p></div>
          </section>

          <section v-else-if="activeTab === 'polish'" class="drafting-polish-view">
            <div class="polish-heading">
              <div><strong>润色与修改说明</strong><span>语法纠错、逻辑优化和表达提升均会保留为新版本。</span></div>
              <button class="drafting-primary-button compact" type="button" :disabled="isPolishing || !currentDraft.id" @click="submitPolish">{{ isPolishing ? '润色中' : '执行润色' }}</button>
            </div>
            <div v-if="polishChanges.length" class="polish-change-list">
              <article v-for="(change, index) in polishChanges" :key="index" class="polish-change">
                <span class="polish-index">{{ index + 1 }}</span>
                <div><small>原文</small><p>{{ change.original || '表达优化' }}</p></div>
                <div><small>调整后</small><p>{{ change.revised || change.content || '已完成润色' }}</p></div>
                <p class="polish-reason">{{ change.reason || '增强表达清晰度与语气一致性。' }}</p>
              </article>
            </div>
            <div v-else-if="revisionSuggestions.length" class="drafting-suggestion-list">
              <article v-for="(suggestion, index) in revisionSuggestions" :key="index">
                <span>{{ index + 1 }}</span>
                <p>{{ suggestion }}</p>
                <button class="drafting-text-button" type="button" @click="applySuggestion(suggestion)">用于修改</button>
              </article>
            </div>
            <div v-else class="drafting-empty-state"><AppIcon name="sparkles" :size="22" /><strong>暂无润色建议</strong><p>生成后可对正文执行润色，系统会在这里说明每一项调整。</p></div>
          </section>

          <section v-else class="drafting-version-view">
            <div class="version-heading"><strong>版本历史</strong><span>每次生成、润色、手动保存或回退都会形成可追溯版本。</span></div>
            <div v-if="versionItems.length" class="version-list">
              <article v-for="version in versionItems" :key="version.id" class="version-row" :class="{ current: version.id === currentDraft.id }">
                <div class="version-marker"><AppIcon :name="version.id === currentDraft.id ? 'check' : 'clock'" :size="15" /></div>
                <div class="version-copy"><strong>v{{ version.version || 1 }} · {{ version.title || '未命名初稿' }}</strong><span>{{ version.revision_instruction || version.status || '初稿生成' }} · {{ formatDate(version.created_at) }}</span></div>
                <button v-if="version.id !== currentDraft.id" class="drafting-secondary-button small" type="button" :disabled="isRevising" @click="revertToVersion(version)">回退</button>
                <span v-else class="version-current-label">当前版本</span>
              </article>
            </div>
            <div v-else class="drafting-empty-state"><AppIcon name="clock" :size="22" /><strong>尚无版本历史</strong><p>首次生成后会自动记录版本。</p></div>
          </section>
        </div>

        <div class="drafting-revision-bar">
          <label for="revision-instruction">继续修改</label>
          <textarea id="revision-instruction" v-model="revisionInstruction" rows="2" placeholder="例如：将语气调整得更严谨，补充反馈方式，并保留所有已核实事实。"></textarea>
          <button class="drafting-primary-button" type="button" :disabled="isRevising || !currentDraft.id || !revisionInstruction.trim()" @click="submitRevision">
            <AppIcon :name="isRevising ? 'clock' : 'send'" :size="16" /> {{ isRevising ? '修改中' : '生成新版本' }}
          </button>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import AppIcon from '../components/AppIcon.vue';
import {
  createDraftStream,
  editDraftContent,
  exportDraft,
  fetchDraft,
  fetchMaterials,
  fetchStyles,
  fetchTemplates,
  fetchVersions,
  polishDraft,
  revertDraft,
  reviseDraft,
} from '../api';

const templateOptions = [
  { key: 'formal_announcement', label: '正式公告', hint: '制度发布与内部通知', icon: 'file' },
  { key: 'news_release', label: '新闻稿', hint: '官网与媒体传播', icon: 'pen' },
  { key: 'pr_statement', label: '公关声明', hint: '风险回应与说明', icon: 'pulse' },
  { key: 'event_notice', label: '活动通知', hint: '活动安排与报名', icon: 'calendar' },
];
const styleOptions = [
  { key: 'formal', label: '正式' },
  { key: 'rigorous', label: '严谨' },
  { key: 'neutral', label: '中性' },
  { key: 'lively', label: '活泼' },
  { key: 'warm', label: '温情' },
];
const channels = ['内部公告', '官网', '媒体通稿', '公众号'];
const channelStyles = { 内部公告: '正式', 官网: '正式', 媒体通稿: '中性', 公众号: '活泼' };
const tabs = [
  { key: 'content', label: '正文' },
  { key: 'polish', label: '修改建议' },
  { key: 'factcheck', label: '核查报告' },
  { key: 'versions', label: '版本历史' },
];

const fallbackDraft = {
  id: 'demo-news-v2',
  title: '关于智能办公平台试运行的通知',
  template_name: 'formal_announcement',
  style: '正式',
  content: `各部门：\n\n为提升企业办公协同效率，公司将于 2026 年 8 月 20 日启动智能办公平台试运行。\n\n试运行期间，平台将提供要素采集、素材解析、初稿生成、事实核查、版本回溯及导出等功能。请各部门指定专人参与体验，并在试运行结束前反馈使用问题和改进建议。\n\n【待核实】本次试运行覆盖全部部门，具体参与范围请以办公室最终通知为准。\n\n特此通知。`,
  version: 2,
  status: '待审核',
  model: '演示模式',
  created_at: '2026-08-20T08:30:00Z',
  fact_checks: [
    { claim: '平台将于 2026 年 8 月 20 日启动试运行', status: '一致', basis: '与用户填写的生效日期一致', suggestion: '' },
    { claim: '本次试运行覆盖全部部门', status: '无法核实', basis: '已选素材与输入要素未提供具体部门范围', suggestion: '发布前请补充参与部门清单或改为“相关部门”。' },
  ],
};
const fallbackMaterials = [
  { id: 101, filename: '董事会决议摘要.docx', status: '已授权' },
  { id: 102, filename: '试运行日程.pdf', status: '已授权' },
];
const fallbackSuggestions = [
  '建议补充试运行结束日期，便于各部门安排反馈节奏。',
  '建议明确反馈渠道，例如联系人、邮箱或工单入口。',
  '对外发布前，请确认“全部部门”的表述是否具有正式依据。',
];

const form = reactive({
  title: '关于智能办公平台试运行的通知',
  template: 'formal_announcement',
  channel: '内部公告',
  audience: '全体员工',
  style: '正式',
  eventDesc: '公司计划启动智能办公平台试运行，用于提升公告、新闻稿和内部通知的起草效率。请各部门参与体验并反馈使用问题。',
  keyFacts: [
    { name: '生效日期', value: '2026 年 8 月 20 日' },
    { name: '发布部门', value: '办公室' },
  ],
  people: [],
  referenceMaterials: [101],
});

const materials = ref(fallbackMaterials);
const templates = ref([]);
const currentDraft = ref({ ...fallbackDraft });
const factChecks = ref(fallbackDraft.fact_checks);
const revisionSuggestions = ref([...fallbackSuggestions]);
const polishChanges = ref([]);
const versionTree = ref({
  id: 'demo-news-v1',
  version: 1,
  title: fallbackDraft.title,
  status: '已生成',
  created_at: '2026-08-20T08:10:00Z',
  children: [{ id: fallbackDraft.id, version: 2, title: fallbackDraft.title, status: '待审核', revision_instruction: '补充反馈要求', created_at: fallbackDraft.created_at, children: [] }],
});
const activeTab = ref('content');
const notice = ref(null);
const activeStage = ref('');
const streamText = ref('');
const revisionInstruction = ref('');
const exportFormat = ref('md');
const editingContent = ref('');
const isGenerating = ref(false);
const isPolishing = ref(false);
const isRevising = ref(false);
const isExporting = ref(false);
const isEditing = ref(false);
const isSavingEdit = ref(false);
const reviewSubmitted = ref(false);

const selectedTemplate = computed(() => templateOptions.find((item) => item.key === form.template) || templateOptions[0]);
const recommendedStyle = computed(() => channelStyles[form.channel] || '正式');
const draftTime = computed(() => currentDraft.value.created_at ? formatDate(currentDraft.value.created_at) : '等待生成');
const displayParagraphs = computed(() => (streamText.value || currentDraft.value.content || '').split(/\n+/).map((item) => item.trim()).filter(Boolean));
const unresolvedChecks = computed(() => factChecks.value.filter((item) => isUnverified(item.status)));
const unresolvedCount = computed(() => unresolvedChecks.value.length);
const stageLabel = computed(() => ({
  extract: '正在提取要素',
  generate: '正在按模板生成',
  factcheck: '正在核查事实',
  suggest: '正在生成修改建议',
}[activeStage.value] || '正在生成初稿'));
const versionItems = computed(() => flattenVersions(versionTree.value));

watch(
  form,
  () => {
    localStorage.setItem('eaos-news-drafting-form', JSON.stringify(form));
  },
  { deep: true }
);

function restoreForm() {
  try {
    const cached = JSON.parse(localStorage.getItem('eaos-news-drafting-form'));
    if (cached) Object.assign(form, cached);
  } catch {
    // Ignore stale local form data.
  }
}

function applyChannelStyle() {
  form.style = recommendedStyle.value;
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
  form.template = 'formal_announcement';
  form.channel = '内部公告';
  form.audience = '';
  form.style = '正式';
  form.eventDesc = '';
  form.keyFacts = [{ name: '', value: '' }];
  form.people = [];
  form.referenceMaterials = [];
  showNotice('success', '已重置生成要素。');
}

async function loadBootstrapData() {
  try {
    const [templateRows, styles, materialRows] = await Promise.all([fetchTemplates(), fetchStyles(), fetchMaterials()]);
    templates.value = templateRows || [];
    const availableTemplateNames = templates.value.map((item) => item.name);
    if (availableTemplateNames.length && !availableTemplateNames.includes(form.template)) {
      form.template = availableTemplateNames.includes('formal_announcement') ? 'formal_announcement' : availableTemplateNames[0];
    }
    const availableStyles = styles?.styles || styles || [];
    const styleNames = availableStyles.map((item) => item.name || item.label);
    if (styleNames.length && !styleNames.includes(form.style)) form.style = styleNames[0];
    materials.value = materialRows?.length ? materialRows : fallbackMaterials;
  } catch {
    materials.value = fallbackMaterials;
    showNotice('info', '后端服务暂未连接，当前展示可交互的演示数据。');
  }
}

async function submitDraft() {
  isGenerating.value = true;
  reviewSubmitted.value = false;
  streamText.value = '';
  activeStage.value = 'extract';
  notice.value = null;

  const payload = {
    title: form.title,
    eventDesc: form.eventDesc,
    audience: form.audience,
    style: form.style,
    styles: [form.style],
    template: form.template,
    keyFacts: form.keyFacts.filter((item) => item.name.trim() || item.value.trim()),
    people: form.people.filter((item) => item.name.trim() || item.title.trim()),
    referenceMaterials: form.referenceMaterials,
  };

  try {
    await createDraftStream(payload, (event) => {
      if (event.type === 'status') activeStage.value = event.stage;
      if (event.type === 'delta') streamText.value += event.text || '';
      if (event.type === 'error') {
        const missing = event.detail?.missing;
        showNotice('error', Array.isArray(missing) && missing.length ? `后端仍启用了模板要素校验：${missing.join('、')}` : event.detail?.message || '生成过程中出现异常，请调整内容后重试。');
      }
      if (event.type === 'done') applyGeneratedDraft(event);
    });
  } catch {
    currentDraft.value = {
      ...fallbackDraft,
      id: `demo-news-${Date.now()}`,
      title: form.title || fallbackDraft.title,
      template_name: form.template,
      style: form.style,
      content: streamText.value || fallbackDraft.content,
      created_at: new Date().toISOString(),
    };
    factChecks.value = fallbackDraft.fact_checks;
    revisionSuggestions.value = fallbackSuggestions;
    versionTree.value = makeDemoVersionTree(currentDraft.value);
    activeTab.value = 'content';
    showNotice('info', '未连接到生成服务，已加载演示初稿与核查报告。');
  } finally {
    isGenerating.value = false;
    activeStage.value = '';
    streamText.value = '';
  }
}

async function applyGeneratedDraft(result) {
  const draftContent = result.draft || streamText.value || '';
  currentDraft.value = {
    ...currentDraft.value,
    id: result.versionId || currentDraft.value.id,
    title: form.title || currentDraft.value.title || '未命名初稿',
    template_name: form.template,
    style: form.style,
    content: draftContent,
    version: result.version || 1,
    status: '待审核',
    model: result.model || '生成模型',
    created_at: result.generatedAt || new Date().toISOString(),
  };
  factChecks.value = result.factCheckReport || [];
  revisionSuggestions.value = result.revisionSuggestions || [];
  polishChanges.value = [];
  activeTab.value = 'content';

  if (result.versionId) {
    try {
      const [draft, versions] = await Promise.all([fetchDraft(result.versionId), fetchVersions(result.versionId)]);
      currentDraft.value = normalizeDraft(draft, currentDraft.value);
      factChecks.value = currentDraft.value.fact_checks || factChecks.value;
      versionTree.value = versions || makeDemoVersionTree(currentDraft.value);
    } catch {
      versionTree.value = makeDemoVersionTree(currentDraft.value);
    }
  } else {
    versionTree.value = makeDemoVersionTree(currentDraft.value);
  }
  showNotice('success', unresolvedCount.value ? '初稿已生成，存在待核实信息，请处理后再提交审核。' : '初稿与事实核查报告已生成。');
}

async function submitPolish() {
  if (!currentDraft.value.id) return;
  isPolishing.value = true;
  notice.value = null;
  try {
    const result = await polishDraft(currentDraft.value.id);
    polishChanges.value = result.changes || result.diffSummary || [];
    if (result.versionId) await loadDraft(result.versionId);
    else if (result.polished) currentDraft.value = { ...currentDraft.value, content: result.polished };
    activeTab.value = 'polish';
    showNotice('success', '已完成润色并保留修改说明。');
  } catch (error) {
    showNotice('error', `润色失败：${error.message || '请稍后重试。'}`);
  } finally {
    isPolishing.value = false;
  }
}

function startEdit() {
  editingContent.value = currentDraft.value.content || '';
  isEditing.value = true;
  activeTab.value = 'content';
}

function cancelEdit() {
  isEditing.value = false;
  editingContent.value = '';
}

async function saveEdit() {
  if (!editingContent.value.trim()) {
    showNotice('error', '正文不能为空。');
    return;
  }
  isSavingEdit.value = true;
  try {
    const result = await editDraftContent(currentDraft.value.id, editingContent.value);
    isEditing.value = false;
    revisionSuggestions.value = result.diffSummary || ['已手动编辑正文。'];
    await loadDraft(result.versionId);
    showNotice('success', '已保存正文并生成新版本。');
  } catch (error) {
    showNotice('error', `保存失败：${error.message || '请稍后重试。'}`);
  } finally {
    isSavingEdit.value = false;
  }
}

function applySuggestion(suggestion) {
  revisionInstruction.value = revisionInstruction.value.trim() ? `${revisionInstruction.value.trim()}\n${suggestion}` : suggestion;
}

async function submitRevision() {
  const instruction = revisionInstruction.value.trim();
  if (!instruction || !currentDraft.value.id) return;
  isRevising.value = true;
  try {
    const result = await reviseDraft(currentDraft.value.id, instruction);
    revisionInstruction.value = '';
    revisionSuggestions.value = result.diffSummary || [];
    await loadDraft(result.versionId);
    showNotice('success', '已根据修改指令生成新版本。');
  } catch (error) {
    showNotice('error', `修改失败：${error.message || '请调整指令后重试。'}`);
  } finally {
    isRevising.value = false;
  }
}

async function revertToVersion(version) {
  if (!currentDraft.value.id || !window.confirm(`确定以 v${version.version || 1} 为基础生成一个新的回退版本吗？`)) return;
  isRevising.value = true;
  try {
    const result = await revertDraft(currentDraft.value.id, version.id);
    await loadDraft(result.versionId);
    showNotice('success', `已回退至 v${version.version || 1} 的内容，并创建新版本。`);
  } catch (error) {
    showNotice('error', `回退失败：${error.message || '请稍后重试。'}`);
  } finally {
    isRevising.value = false;
  }
}

async function loadDraft(versionId) {
  try {
    const [draft, versions] = await Promise.all([fetchDraft(versionId), fetchVersions(versionId)]);
    currentDraft.value = normalizeDraft(draft, currentDraft.value);
    factChecks.value = currentDraft.value.fact_checks || [];
    versionTree.value = versions || versionTree.value;
  } catch {
    currentDraft.value = { ...currentDraft.value, id: versionId, version: (currentDraft.value.version || 1) + 1 };
  }
  activeTab.value = 'content';
}

async function submitExport() {
  isExporting.value = true;
  try {
    const result = await exportDraft(currentDraft.value.id, exportFormat.value);
    if (!result.download_url) throw new Error('未收到下载地址');
    const anchor = document.createElement('a');
    anchor.href = result.download_url;
    anchor.download = decodeURIComponent(result.download_url.split('/').pop() || 'draft');
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    showNotice('success', `已开始导出 ${exportFormat.value.toUpperCase()} 文件。`);
  } catch (error) {
    const suffix = exportFormat.value === 'pdf' ? '请确认服务端已安装 pandoc、xelatex 和中文字体。' : '请稍后重试。';
    showNotice('error', `导出失败：${error.message || suffix} ${suffix}`);
  } finally {
    isExporting.value = false;
  }
}

function submitForReview() {
  if (unresolvedCount.value || !currentDraft.value.id) return;
  reviewSubmitted.value = true;
  showNotice('success', '已提交人工审核。审核通过并完成签发后方可发布。');
}

function isUnverified(status) {
  const value = String(status || '').toLowerCase();
  return value.includes('无法核实') || value.includes('待核实') || value.includes('unverified') || value.includes('unverifiable');
}

function readableStatus(status) {
  if (isUnverified(status)) return '待核实';
  const value = String(status || '').toLowerCase();
  if (value.includes('不一致') || value.includes('inconsistent')) return '不一致';
  return '一致';
}

function factStatusClass(status) {
  if (isUnverified(status)) return 'pending';
  const value = String(status || '').toLowerCase();
  return value.includes('不一致') || value.includes('inconsistent') ? 'mismatch' : 'verified';
}

function highlightSegments(text) {
  const patterns = [/【待核实】[^。；\n]*/g];
  unresolvedChecks.value.forEach((item) => {
    if (item.claim && text.includes(item.claim)) patterns.push(new RegExp(escapeRegExp(item.claim), 'g'));
  });
  const matches = [];
  patterns.forEach((pattern) => {
    for (const match of text.matchAll(pattern)) matches.push({ start: match.index, end: match.index + match[0].length });
  });
  const merged = matches.sort((a, b) => a.start - b.start).reduce((items, match) => {
    const previous = items.at(-1);
    if (previous && match.start <= previous.end) previous.end = Math.max(previous.end, match.end);
    else items.push(match);
    return items;
  }, []);
  if (!merged.length) return [{ text, unverified: false }];
  let cursor = 0;
  return merged.flatMap((match) => {
    const segments = [];
    if (match.start > cursor) segments.push({ text: text.slice(cursor, match.start), unverified: false });
    segments.push({ text: text.slice(match.start, match.end), unverified: true });
    cursor = match.end;
    return segments;
  }).concat(cursor < text.length ? [{ text: text.slice(cursor), unverified: false }] : []);
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function normalizeDraft(payload, fallback) {
  const draft = payload?.draft || payload || {};
  return {
    ...fallback,
    ...draft,
    content: draft.content || draft.draft || fallback.content,
    fact_checks: draft.fact_checks || draft.factCheckReport || fallback.fact_checks,
  };
}

function flattenVersions(node) {
  if (!node) return [];
  const root = node.versions ? node.versions : [node];
  const result = [];
  const visit = (item) => {
    if (!item) return;
    result.push(item);
    (item.children || []).forEach(visit);
  };
  root.forEach(visit);
  return result.sort((a, b) => Number(b.version || 0) - Number(a.version || 0));
}

function makeDemoVersionTree(draft) {
  return {
    id: `${draft.id}-root`,
    version: Math.max(1, (draft.version || 1) - 1),
    title: draft.title,
    status: '已生成',
    created_at: draft.created_at,
    children: [{ id: draft.id, version: draft.version || 1, title: draft.title, status: draft.status || '待审核', revision_instruction: '当前版本', created_at: draft.created_at, children: [] }],
  };
}

function formatDate(value) {
  if (!value) return '刚刚';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(date);
}

function showNotice(type, text) {
  notice.value = { type, text };
  window.clearTimeout(showNotice.timer);
  showNotice.timer = window.setTimeout(() => {
    notice.value = null;
  }, 5000);
}

restoreForm();
onMounted(loadBootstrapData);
</script>
