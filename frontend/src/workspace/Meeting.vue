<template>
  <section class="meeting-page">
    <header class="meeting-head">
      <div>
        <p class="eyebrow">公开行业会议知识库</p>
        <h2>把会议资料<span class="inline-image" aria-hidden="true"></span>整理成结构化纪要</h2>
      </div>
      <div class="head-actions">
        <button v-if="selectedId" class="secondary-button" type="button" @click="closeDetail">返回列表</button>
        <button v-else class="primary-button" type="button" @click="toggleCreate">
          {{ creating ? '收起表单' : '新建' }}
        </button>
      </div>
    </header>

    <p v-if="errorMessage" class="meeting-error" role="alert">{{ errorMessage }}</p>

    <section v-if="creating" class="meeting-form-panel">
      <h3>新建会议</h3>
      <p class="form-hint">填写会议名称与时间，并在同一窗口导入公开资料链接、文件（PPT 截图、PDF、Word、音频等）或转录文本，保存后即可生成结构化纪要、知识卡片与关联信息列表。</p>
      <div class="meeting-form-grid">
        <label><span>会议名称 *</span><input v-model.trim="form.name" maxlength="256" placeholder="例如：2026 智能制造行业峰会" /></label>
        <label><span>开始时间</span><input v-model="form.startTime" type="datetime-local" /></label>
        <label><span>结束时间</span><input v-model="form.endTime" type="datetime-local" /></label>
      </div>
      <div class="material-inputs">
        <div class="stage-box">
          <strong>公开资料链接</strong>
          <label><span>链接</span><input v-model.trim="linkForm.url" type="url" placeholder="https://…" /></label>
          <label><span>标题</span><input v-model.trim="linkForm.title" /></label>
        </div>
        <div class="stage-box">
          <strong>转录文本</strong>
          <label><span>标题</span><input v-model.trim="transcriptForm.title" /></label>
          <label><span>转录内容</span><textarea v-model="transcriptForm.content" rows="4" placeholder="粘贴会议文本或录音转写内容"></textarea></label>
        </div>
        <label class="upload-box">
          <span>上传文件</span>
          <em>支持 PDF、Word、PPTX、图片（PPT 截图）或音频，可多选</em>
          <input type="file" multiple @change="stageFiles" />
        </label>
      </div>
      <ul v-if="pendingFiles.length" class="pending-files">
        <li v-for="(file, index) in pendingFiles" :key="`${file.name}-${index}`">
          <span>{{ file.name }}（{{ sizeText(file.size) }}）</span>
          <button class="text-button danger" type="button" @click="removePendingFile(index)">移除</button>
        </li>
      </ul>
      <div class="form-actions">
        <button class="primary-button" type="button" :disabled="saving" @click="saveMeeting">
          {{ saving ? '保存中…' : '保存会议' }}
        </button>
      </div>
    </section>

    <template v-if="!selectedId">
      <section class="meeting-toolbar" aria-label="会议筛选">
        <label>
          <span>关键词</span>
          <input v-model.trim="filters.keyword" type="search" placeholder="会议名称、主办方或关键词" @keyup.enter="loadMeetings" />
        </label>
        <label>
          <span>状态</span>
          <select v-model="filters.status">
            <option value="">全部状态</option>
            <option value="draft">待整理</option>
            <option value="processing">整理中</option>
            <option value="completed">已完成</option>
          </select>
        </label>
        <button class="primary-button meeting-action" type="button" :disabled="loading" @click="loadMeetings">
          {{ loading ? '查询中…' : '查询' }}
        </button>
      </section>

      <section class="meeting-list-panel">
        <div v-if="!meetings.length && !loading" class="meeting-empty">暂无会议公开信息。</div>
        <div v-else class="meeting-table-wrap">
          <table>
            <thead>
              <tr>
                <th>会议</th>
                <th>类型</th>
                <th>时间</th>
                <th>主办方</th>
                <th>资料</th>
                <th>状态</th>
                <th>纪要</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in meetings" :key="item.id">
                <td class="meeting-name">
                  <strong>{{ item.name }}</strong>
                  <span>{{ item.location || '地点未公开' }}</span>
                </td>
                <td>{{ item.category }}</td>
                <td>{{ formatDate(item.startTime) }}</td>
                <td>{{ item.organizer || '-' }}</td>
                <td>{{ item.materialCount }} 份</td>
                <td><span :class="['meeting-status', `status-${item.status}`]">{{ statusText(item.status) }}</span></td>
                <td>{{ item.latestVersion ? `v${item.latestVersion}` : '-' }}</td>
                <td><button class="text-button" type="button" @click="openDetail(item.id)">查看</button></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>

    <template v-else-if="detail">
      <section class="meeting-summary">
        <div>
          <span :class="['meeting-status', `status-${detail.conference.status}`]">
            {{ statusText(detail.conference.status) }}
          </span>
          <h3>{{ detail.conference.name }}</h3>
          <p>{{ detail.conference.description || '暂无会议简介。' }}</p>
        </div>
        <dl>
          <div><dt>时间</dt><dd>{{ formatRange(detail.conference.startTime, detail.conference.endTime) }}</dd></div>
          <div><dt>地点</dt><dd>{{ detail.conference.location || '-' }}</dd></div>
          <div><dt>主办方</dt><dd>{{ detail.conference.organizer || '-' }}</dd></div>
          <div><dt>关键词</dt><dd>{{ detail.conference.keywords || '-' }}</dd></div>
        </dl>
      </section>

      <section v-if="activeTask && detail.conference.status === 'processing'" class="task-strip" aria-live="polite">
        <div>
          <strong>正在整理公开资料</strong>
          <span>{{ completedSteps }}/{{ activeTask.progress?.length || 5 }} 步</span>
        </div>
        <div class="step-track">
          <span
            v-for="step in activeTask.progress || []"
            :key="step.step"
            :class="['step-dot', step.status]"
            :title="`${step.label}：${stepStatusText(step.status)}`"
          ></span>
        </div>
      </section>

      <section class="material-panel-user">
        <header class="section-row">
          <div>
            <p class="section-kicker">公开资料录入</p>
            <h3>会议资料（{{ detail.materials.length }}/50）</h3>
          </div>
          <button
            class="primary-button"
            type="button"
            :disabled="detail.conference.status === 'processing' || !detail.materials.length"
            @click="organize"
          >
            {{ detail.conference.status === 'processing' ? '整理中…' : (detail.reports.length ? '重新整理' : '生成会议纪要') }}
          </button>
        </header>
        <p class="form-hint">录入公开资料链接、上传文件或粘贴转录文本后，点击生成即可产出结构化会议纪要、知识卡片与关联信息列表；资料更新后可随时点击「重新整理」刷新结果与关联推荐。</p>
        <div class="material-inputs">
          <form @submit.prevent="addLink">
            <strong>公开资料链接</strong>
            <label><span>链接 *</span><input v-model.trim="linkForm.url" type="url" required placeholder="https://…" /></label>
            <label><span>标题</span><input v-model.trim="linkForm.title" /></label>
            <button class="secondary-button" type="submit">添加链接</button>
          </form>
          <form @submit.prevent="addTranscript">
            <strong>转录文本</strong>
            <label><span>标题</span><input v-model.trim="transcriptForm.title" /></label>
            <label><span>转录内容 *</span><textarea v-model="transcriptForm.content" rows="4" required placeholder="粘贴会议录音转写或速记文本"></textarea></label>
            <button class="secondary-button" type="submit">添加转录稿</button>
          </form>
          <label class="upload-box">
            <span>上传文件</span>
            <em>支持 PDF、Word、PPTX、图片或音频</em>
            <input type="file" @change="uploadMaterial" />
          </label>
        </div>
        <ul class="material-list">
          <li v-for="item in detail.materials" :key="item.id">
            <div>
              <strong>{{ item.title }}</strong>
              <span>{{ materialTypeText(item.materialType) }} · {{ sizeText(item.sizeBytes) }}</span>
            </div>
            <span :class="['parse-status', item.parseStatus]">{{ parseStatusText(item.parseStatus) }}</span>
            <p v-if="item.parseResult?.error">{{ item.parseResult.error }}</p>
            <button
              class="text-button danger"
              type="button"
              :disabled="detail.conference.status === 'processing'"
              @click="removeMaterial(item)"
            >删除</button>
          </li>
          <li v-if="!detail.materials.length" class="meeting-empty slim">尚未添加资料，请先录入链接、转录文本或上传文件。</li>
        </ul>
      </section>

      <div class="meeting-detail-grid">
        <main class="meeting-main">
          <section class="report-panel">
            <header class="section-row">
              <div>
                <p class="section-kicker">结构化会议纪要</p>
                <h3>会议纪要</h3>
              </div>
              <div v-if="detail.reports.length" class="report-actions">
                <label>
                  <span class="sr-only">纪要版本</span>
                  <select v-model.number="selectedReportId">
                    <option v-for="report in detail.reports" :key="report.id" :value="report.id">
                      v{{ report.version }} · {{ formatDate(report.createdAt) }}
                    </option>
                  </select>
                </label>
                <button class="secondary-button" type="button" @click="exportReport">导出 Word</button>
              </div>
            </header>
            <article v-if="selectedReport" class="markdown-body" v-html="renderMarkdown(selectedReport.content)"></article>
            <div v-else class="meeting-empty">纪要尚未生成。</div>
          </section>

          <section class="knowledge-section">
            <header class="section-row">
              <div>
                <p class="section-kicker">可检索知识条目</p>
                <h3>知识卡片</h3>
              </div>
              <span>{{ selectedCards.length }} 条</span>
            </header>
            <div class="knowledge-grid">
              <article v-for="card in selectedCards" :key="card.id" class="knowledge-card">
                <div>
                  <span>{{ card.cardType }}</span>
                  <strong>{{ card.title }}</strong>
                </div>
                <p>{{ card.content }}</p>
                <dl v-if="card.actor || card.expectedTime">
                  <div v-if="card.actor"><dt>主体</dt><dd>{{ card.actor }}</dd></div>
                  <div v-if="card.expectedTime"><dt>时间</dt><dd>{{ card.expectedTime }}</dd></div>
                </dl>
                <details>
                  <summary>来源引用（{{ card.sourceRef?.length || 0 }}）</summary>
                  <p v-for="(ref, index) in card.sourceRef || []" :key="index">
                    {{ sourceText(ref) }}
                  </p>
                </details>
              </article>
            </div>
            <div v-if="!selectedCards.length" class="meeting-empty">暂无知识卡片。</div>
          </section>

          <section class="media-section">
            <header class="section-row">
              <div>
                <p class="section-kicker">公开来源</p>
                <h3>媒体报道</h3>
              </div>
            </header>
            <a
              v-for="item in detail.media"
              :key="item.id"
              class="media-row"
              :href="safeUrl(item.sourceUrl)"
              target="_blank"
              rel="noopener noreferrer"
            >
              <div><strong>{{ item.title }}</strong><span>{{ item.summary }}</span></div>
              <time>{{ item.sourceName || '公开来源' }} · {{ formatDate(item.publishedAt) }}</time>
            </a>
            <div v-if="!detail.media.length" class="meeting-empty">暂无补充报道。</div>
          </section>
        </main>

        <aside class="recommendation-panel">
          <section>
            <p class="section-kicker">关联政策</p>
            <h3>政策推荐</h3>
            <article v-for="item in selectedReport?.relatedPolicies || []" :key="item.id" class="recommendation-item">
              <strong>{{ item.title }}</strong>
              <span>相似度 {{ score(item.score) }}</span>
              <p>{{ item.reason }}</p>
            </article>
            <p v-if="!selectedReport?.relatedPolicies?.length" class="side-empty">暂无达到阈值的政策。</p>
          </section>
          <section>
            <p class="section-kicker">竞品情报</p>
            <h3>竞品动态</h3>
            <a
              v-for="item in selectedReport?.relatedCompetitors || []"
              :key="item.title"
              class="recommendation-item meeting-link"
              :href="safeUrl(item.sourceUrl)"
              target="_blank"
              rel="noopener noreferrer"
            >
              <strong>{{ item.title }}</strong>
              <span>相似度 {{ score(item.score) }}</span>
              <p>{{ item.summary || item.reason }}</p>
            </a>
            <p v-if="!selectedReport?.relatedCompetitors?.length" class="side-empty">暂无达到阈值的竞品动态。</p>
          </section>
          <section>
            <p class="section-kicker">历史知识</p>
            <h3>相关会议</h3>
            <button
              v-for="item in selectedReport?.relatedConferences || []"
              :key="item.id"
              class="recommendation-item meeting-link"
              type="button"
              @click="openDetail(item.id)"
            >
              <strong>{{ item.title }}</strong>
              <span>相似度 {{ score(item.score) }}</span>
              <p>{{ item.reason }}</p>
            </button>
            <p v-if="!selectedReport?.relatedConferences?.length" class="side-empty">暂无达到阈值的历史会议。</p>
          </section>
        </aside>
      </div>
    </template>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import {
  addMeetingLink,
  addMeetingTranscript,
  createMeeting,
  deleteMeetingMaterial,
  downloadMeetingReport,
  fetchMeetingDetail,
  fetchMeetings,
  organizeMeeting,
  uploadMeetingMaterial,
} from '../api';

const route = useRoute();
const router = useRouter();
const filters = reactive({ keyword: '', status: '' });
const meetings = ref([]);
const detail = ref(null);
const selectedId = ref(null);
const selectedReportId = ref(null);
const loading = ref(false);
const saving = ref(false);
const errorMessage = ref('');
const creating = ref(false);
const form = reactive(blankMeeting());
const linkForm = reactive({ url: '', title: '' });
const transcriptForm = reactive({ title: '', content: '' });
const pendingFiles = ref([]);
let pollTimer = null;

function blankMeeting() {
  return {
    name: '',
    startTime: '',
    endTime: '',
  };
}

const selectedReport = computed(() => (
  detail.value?.reports?.find((item) => item.id === selectedReportId.value) || detail.value?.latestReport || null
));
const selectedCards = computed(() => (
  detail.value?.cardsByReport?.[selectedReportId.value] || detail.value?.cards || []
));
const activeTask = computed(() => detail.value?.tasks?.find((item) => ['pending', 'running', 'partial'].includes(item.status)));
const completedSteps = computed(() => activeTask.value?.progress?.filter((step) => step.status === 'completed').length || 0);

function formatDate(value) {
  if (!value) return '-';
  return new Date(value).toLocaleString('zh-CN', { dateStyle: 'medium', timeStyle: 'short' });
}

function formatRange(start, end) {
  return end ? `${formatDate(start)} 至 ${formatDate(end)}` : formatDate(start);
}

function statusText(value) {
  return { draft: '待整理', processing: '整理中', completed: '已完成' }[value] || value;
}

function stepStatusText(value) {
  return { pending: '等待', running: '进行中', retrying: '重试中', completed: '完成', failed: '失败' }[value] || value;
}

function score(value) {
  return `${Math.round(Number(value || 0) * 100)}%`;
}

function toPayloadTime(value) {
  return value ? value.replace('T', ' ') : null;
}

function materialTypeText(value) {
  return { link: '链接', file: '文件', transcript: '转录稿', image: '图片', audio: '音频' }[value] || value;
}

function parseStatusText(value) {
  return { pending: '待解析', parsed: '已解析', failed: '解析失败' }[value] || value;
}

function sizeText(value) {
  const bytes = Number(value || 0);
  if (!bytes) return '-';
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${Math.ceil(bytes / 1024)} KB`;
}

function sourceText(ref) {
  if (ref.status === '待确认') return `待确认：${ref.reason || '缺少来源'}`;
  return `资料 #${ref.materialId} · ${ref.location || '原文'}${ref.quote ? `：${ref.quote}` : ''}`;
}

function safeUrl(value) {
  try {
    const url = new URL(value, window.location.href);
    return ['http:', 'https:'].includes(url.protocol) ? url.href : '#';
  } catch {
    return '#';
  }
}

function renderMarkdown(markdown) {
  const escape = (value) => String(value || '')
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;').replaceAll("'", '&#039;');
  const inline = (value) => escape(value)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`(.+?)`/g, '<code>$1</code>');
  const lines = String(markdown || '').split(/\r?\n/);
  const output = [];
  let list = '';
  const closeList = () => {
    if (list) output.push(`</${list}>`);
    list = '';
  };
  for (const raw of lines) {
    const line = raw.trim();
    if (!line) {
      closeList();
      continue;
    }
    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      closeList();
      const level = heading[1].length + 1;
      output.push(`<h${level}>${inline(heading[2])}</h${level}>`);
      continue;
    }
    const bullet = line.match(/^[-*]\s+(.+)$/);
    const ordered = line.match(/^\d+\.\s+(.+)$/);
    if (bullet || ordered) {
      const nextList = bullet ? 'ul' : 'ol';
      if (list !== nextList) {
        closeList();
        list = nextList;
        output.push(`<${list}>`);
      }
      output.push(`<li>${inline((bullet || ordered)[1])}</li>`);
      continue;
    }
    closeList();
    output.push(`<p>${inline(line)}</p>`);
  }
  closeList();
  return output.join('');
}

function toggleCreate() {
  creating.value = !creating.value;
  errorMessage.value = '';
  Object.assign(form, blankMeeting());
}

function stageFiles(event) {
  const picked = Array.from(event.target.files || []);
  if (picked.length) pendingFiles.value.push(...picked);
  event.target.value = '';
}

function removePendingFile(index) {
  pendingFiles.value.splice(index, 1);
}

async function saveMeeting() {
  if (!form.name) {
    errorMessage.value = '会议名称不能为空';
    return;
  }
  saving.value = true;
  errorMessage.value = '';
  const link = { ...linkForm };
  const transcript = { ...transcriptForm };
  const files = [...pendingFiles.value];
  try {
    const saved = await createMeeting({
      ...form,
      startTime: toPayloadTime(form.startTime),
      endTime: toPayloadTime(form.endTime),
    });
    const errors = [];
    if (link.url) {
      try {
        await addMeetingLink(saved.id, link);
      } catch (error) {
        errors.push(`链接添加失败：${error.message}`);
      }
    }
    if (transcript.content) {
      try {
        await addMeetingTranscript(saved.id, transcript);
      } catch (error) {
        errors.push(`转录稿添加失败：${error.message}`);
      }
    }
    for (const file of files) {
      try {
        await uploadMeetingMaterial(saved.id, file);
      } catch (error) {
        errors.push(`${file.name} 上传失败：${error.message}`);
      }
    }
    creating.value = false;
    Object.assign(form, blankMeeting());
    linkForm.url = '';
    linkForm.title = '';
    transcriptForm.title = '';
    transcriptForm.content = '';
    pendingFiles.value = [];
    if (errors.length) errorMessage.value = errors.join('；');
    await loadMeetings();
    await openDetail(saved.id);
    if (!errors.length && (link.url || transcript.content || files.length)
      && window.confirm('会议与资料已保存，是否立即生成结构化会议纪要？')) {
      try {
        await organizeMeeting(saved.id);
        await openDetail(saved.id);
      } catch (error) {
        errorMessage.value = error.message;
      }
    }
  } catch (error) {
    errorMessage.value = error.message;
  } finally {
    saving.value = false;
  }
}

async function addLink() {
  if (!detail.value) return;
  try {
    await addMeetingLink(detail.value.conference.id, linkForm);
    linkForm.url = '';
    linkForm.title = '';
    await openDetail(detail.value.conference.id);
  } catch (error) {
    errorMessage.value = error.message;
  }
}

async function addTranscript() {
  if (!detail.value) return;
  try {
    await addMeetingTranscript(detail.value.conference.id, transcriptForm);
    transcriptForm.title = '';
    transcriptForm.content = '';
    await openDetail(detail.value.conference.id);
  } catch (error) {
    errorMessage.value = error.message;
  }
}

async function uploadMaterial(event) {
  const file = event.target.files?.[0];
  if (!file || !detail.value) return;
  try {
    await uploadMeetingMaterial(detail.value.conference.id, file);
    event.target.value = '';
    await openDetail(detail.value.conference.id);
  } catch (error) {
    errorMessage.value = error.message;
  }
}

async function removeMaterial(item) {
  if (!window.confirm(`确认删除资料“${item.title}”？`)) return;
  try {
    await deleteMeetingMaterial(detail.value.conference.id, item.id);
    await openDetail(detail.value.conference.id);
  } catch (error) {
    errorMessage.value = error.message;
  }
}

async function organize() {
  if (!detail.value) return;
  if (!window.confirm('确认开始整理？系统将解析资料、采集公开报道，并生成结构化会议纪要、知识卡片与关联信息列表。')) return;
  try {
    await organizeMeeting(detail.value.conference.id);
    await openDetail(detail.value.conference.id);
  } catch (error) {
    errorMessage.value = error.message;
  }
}

async function loadMeetings() {
  loading.value = true;
  errorMessage.value = '';
  try {
    const data = await fetchMeetings(filters);
    meetings.value = data?.items || [];
    scheduleListPolling();
  } catch (error) {
    errorMessage.value = error.message;
  } finally {
    loading.value = false;
  }
}

async function openDetail(id) {
  selectedId.value = Number(id);
  errorMessage.value = '';
  router.replace({ path: '/workspace/meeting', query: { id } });
  try {
    detail.value = await fetchMeetingDetail(id);
    selectedReportId.value = detail.value.latestReport?.id || null;
    scheduleDetailPolling();
  } catch (error) {
    errorMessage.value = error.message;
  }
}

function closeDetail() {
  selectedId.value = null;
  detail.value = null;
  router.replace('/workspace/meeting');
  loadMeetings();
}

async function exportReport() {
  if (!selectedReport.value) return;
  try {
    await downloadMeetingReport(
      detail.value.conference.id,
      selectedReport.value.id,
      `${detail.value.conference.name}-会议纪要-v${selectedReport.value.version}.docx`,
    );
  } catch (error) {
    errorMessage.value = error.message;
  }
}

function clearPolling() {
  if (pollTimer) window.clearTimeout(pollTimer);
  pollTimer = null;
}

function scheduleListPolling() {
  clearPolling();
  if (meetings.value.some((item) => item.status === 'processing')) {
    pollTimer = window.setTimeout(loadMeetings, 15000);
  }
}

function scheduleDetailPolling() {
  clearPolling();
  if (detail.value?.conference?.status === 'processing') {
    pollTimer = window.setTimeout(() => openDetail(selectedId.value), 5000);
  }
}

onMounted(() => {
  if (route.query.id) openDetail(route.query.id);
  else loadMeetings();
});

onBeforeUnmount(clearPolling);
</script>

<style scoped>
.meeting-page {
  width: min(1440px, calc(100% - 40px));
  margin: 0 auto;
  padding: 28px 0 48px;
  color: #172d2b;
}

.meeting-head,
.section-row,
.task-strip,
.meeting-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.meeting-head {
  margin-bottom: 20px;
}

.head-actions {
  display: flex;
  gap: 10px;
}

.primary-button {
  min-height: 40px;
  padding: 8px 16px;
  border: 0;
  border-radius: 8px;
  background: #0f6962;
  color: #fff;
  font-weight: 700;
}

.primary-button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.meeting-form-panel,
.material-panel-user {
  border: 1px solid #d8e5e1;
  border-radius: 8px;
  background: #fff;
  padding: 20px;
  margin-bottom: 14px;
}

.meeting-form-panel h3,
.material-panel-user h3 {
  margin: 3px 0 0;
}

.form-hint {
  margin: 8px 0 0;
  color: #71817e;
  font-size: 12px;
}

.meeting-form-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-top: 14px;
}

.meeting-form-grid label,
.material-inputs label {
  display: grid;
  gap: 6px;
  color: #48615d;
  font-size: 13px;
  font-weight: 700;
}

.form-wide {
  grid-column: 1 / -1;
}

.meeting-form-grid input,
.meeting-form-grid select,
.meeting-form-grid textarea,
.material-inputs input,
.material-inputs textarea {
  min-height: 40px;
  border: 1px solid #cddbd7;
  border-radius: 7px;
  padding: 8px 10px;
  background: #fff;
  color: #172d2b;
  font-weight: 400;
}

.meeting-form-grid textarea,
.material-inputs textarea {
  resize: vertical;
  line-height: 1.6;
}

.pending-files {
  margin: 12px 0 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 6px;
}

.pending-files li {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  border: 1px solid #e3ece9;
  border-radius: 8px;
  background: #fbfdfc;
}

.pending-files li span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #4d625e;
  font-size: 12px;
}

.form-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}

.material-inputs {
  display: grid;
  grid-template-columns: 1fr 1.4fr 0.8fr;
  gap: 12px;
  margin-top: 16px;
}

.material-inputs form,
.material-inputs .stage-box {
  display: grid;
  align-content: start;
  gap: 10px;
  padding: 12px;
  border: 1px solid #e0ebe7;
  border-radius: 8px;
  background: #fbfdfc;
}

.material-inputs form strong,
.material-inputs .stage-box strong {
  color: #163c38;
  font-size: 13px;
}

.material-inputs form .secondary-button {
  justify-self: start;
}

.upload-box {
  min-height: 150px;
  display: grid;
  place-items: center;
  align-content: center;
  gap: 4px;
  padding: 16px;
  border: 1px dashed #9dbcb4;
  border-radius: 8px;
  background: #f5faf8;
  color: #2c5a54;
  font-size: 13px;
  text-align: center;
  cursor: pointer;
}

.upload-box em {
  color: #71817e;
  font-size: 12px;
  font-style: normal;
  font-weight: 400;
}

.upload-box input {
  width: 100%;
}

.material-list {
  margin: 16px 0 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 8px;
}

.material-list li:not(.meeting-empty) {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  gap: 12px;
  align-items: center;
  padding: 10px 12px;
  border: 1px solid #e3ece9;
  border-radius: 8px;
}

.material-list li > div {
  min-width: 0;
  display: grid;
  gap: 3px;
}

.material-list li span {
  color: #71817e;
  font-size: 12px;
}

.material-list li p {
  grid-column: 1 / -1;
  margin: 0;
  color: #a33227;
  font-size: 12px;
}

.material-list li .danger {
  color: #a33227;
}

.material-list li .danger:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.parse-status {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 3px 8px;
  border-radius: 12px;
  background: #f1f4f3;
  color: #5d6d6a;
  font-size: 11px;
  font-weight: 800;
}

.parse-status.parsed {
  background: #e7f7f1;
  color: #0d6b53;
}

.parse-status.failed {
  background: #fff0ee;
  color: #a33227;
}

.meeting-empty.slim {
  padding: 16px;
}

.meeting-head h2,
.section-row h3,
.recommendation-panel h3 {
  margin: 3px 0 0;
  letter-spacing: 0;
}

.meeting-head h2 {
  max-width: 860px;
  font-size: clamp(1.9rem, 4.2vw, 4rem);
  line-height: 1.06;
  text-wrap: balance;
}

.meeting-toolbar,
.meeting-list-panel,
.meeting-summary,
.report-panel,
.knowledge-section,
.media-section,
.recommendation-panel,
.task-strip {
  border: 1px solid #d8e5e1;
  border-radius: 8px;
  background: #fff;
}

.meeting-toolbar {
  justify-content: flex-start;
  align-items: end;
  padding: 16px;
  margin-bottom: 14px;
}

.meeting-toolbar label {
  min-width: 210px;
  display: grid;
  gap: 6px;
  color: #48615d;
  font-size: 13px;
  font-weight: 700;
}

.meeting-toolbar input,
.meeting-toolbar select,
.report-actions select {
  min-height: 40px;
  border: 1px solid #cddbd7;
  border-radius: 7px;
  padding: 8px 10px;
  background: #fff;
  color: #172d2b;
}

.meeting-action,
.secondary-button {
  width: auto;
  min-height: 40px;
  padding: 8px 14px;
}

.secondary-button {
  border: 1px solid #b9cec8;
  border-radius: 8px;
  background: #fff;
  color: #0f6962;
  font-weight: 700;
}

.meeting-list-panel {
  overflow: hidden;
}

.meeting-table-wrap {
  overflow-x: auto;
}

table {
  width: 100%;
  min-width: 900px;
  border-collapse: collapse;
  font-size: 13px;
}

th,
td {
  padding: 12px 14px;
  border-bottom: 1px solid #e8efed;
  text-align: left;
}

th {
  background: #f5faf8;
  color: #58706c;
}

.meeting-name {
  min-width: 240px;
}

.meeting-name strong,
.meeting-name span {
  display: block;
}

.meeting-name span {
  margin-top: 4px;
  color: #71817e;
  font-size: 12px;
}

.meeting-status {
  display: inline-flex;
  align-items: center;
  min-height: 26px;
  padding: 4px 9px;
  border-radius: 13px;
  font-size: 12px;
  font-weight: 800;
}

.status-draft {
  background: #f1f4f3;
  color: #5d6d6a;
}

.status-processing {
  background: #fff4e8;
  color: #a54813;
}

.status-completed {
  background: #e7f7f1;
  color: #0d6b53;
}

.text-button {
  min-height: 36px;
  border: 0;
  background: transparent;
  color: #0f766e;
  font-weight: 800;
}

.meeting-summary {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(320px, 1fr);
  gap: 24px;
  padding: 22px;
  margin-bottom: 14px;
}

.meeting-summary h3 {
  margin: 12px 0 6px;
  font-size: 24px;
}

.meeting-summary p {
  margin: 0;
  color: #586d69;
  line-height: 1.7;
}

.meeting-summary dl,
.knowledge-card dl {
  margin: 0;
}

.meeting-summary dl {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.meeting-summary dl div,
.knowledge-card dl div {
  display: grid;
  gap: 3px;
}

dt {
  color: #71817e;
  font-size: 11px;
}

dd {
  margin: 0;
  font-size: 13px;
  font-weight: 700;
}

.task-strip {
  padding: 14px 18px;
  margin-bottom: 14px;
}

.task-strip > div:first-child {
  display: grid;
  gap: 3px;
}

.task-strip span {
  color: #60736f;
  font-size: 12px;
}

.step-track {
  display: flex;
  gap: 8px;
}

.step-dot {
  width: 42px;
  height: 8px;
  border-radius: 4px;
  background: #dfe8e5;
}

.step-dot.completed {
  background: #0f766e;
}

.step-dot.running,
.step-dot.retrying {
  background: #d97706;
}

.step-dot.failed {
  background: #c9362b;
}

.meeting-detail-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: 14px;
  align-items: start;
}

.meeting-main {
  display: grid;
  gap: 14px;
}

.report-panel,
.knowledge-section,
.media-section,
.recommendation-panel {
  padding: 20px;
}

.report-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.section-kicker {
  margin: 0;
  color: #b14b16;
  font-size: 11px;
  font-weight: 800;
}

.markdown-body {
  max-width: 850px;
  padding-top: 12px;
  color: #2c403d;
  line-height: 1.8;
}

.markdown-body :deep(h2) {
  margin: 24px 0 8px;
  color: #163c38;
  font-size: 20px;
}

.markdown-body :deep(h3),
.markdown-body :deep(h4) {
  margin: 18px 0 7px;
  color: #24514c;
  font-size: 16px;
}

.markdown-body :deep(p),
.markdown-body :deep(li) {
  margin: 6px 0;
}

.markdown-body :deep(code) {
  padding: 2px 5px;
  border-radius: 4px;
  background: #edf5f2;
}

.knowledge-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-top: 14px;
}

.knowledge-card {
  min-width: 0;
  padding: 14px;
  border: 1px solid #dde8e5;
  border-radius: 8px;
  background: #fbfdfc;
}

.knowledge-card > div:first-child {
  display: grid;
  gap: 5px;
}

.knowledge-card > div:first-child span {
  color: #b14b16;
  font-size: 11px;
  font-weight: 800;
}

.knowledge-card p {
  color: #4d625e;
  line-height: 1.65;
  overflow-wrap: anywhere;
}

.knowledge-card dl {
  display: flex;
  gap: 24px;
}

.knowledge-card details {
  margin-top: 12px;
  color: #55706b;
  font-size: 12px;
}

.knowledge-card summary {
  cursor: pointer;
  font-weight: 700;
}

.media-row {
  display: flex;
  justify-content: space-between;
  gap: 20px;
  padding: 14px 0;
  border-bottom: 1px solid #e7efec;
  color: inherit;
  text-decoration: none;
}

.media-row div {
  min-width: 0;
  display: grid;
  gap: 5px;
}

.media-row span {
  color: #62736f;
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.media-row time {
  flex: 0 0 auto;
  color: #71817e;
  font-size: 12px;
}

.recommendation-panel {
  position: sticky;
  top: 14px;
  display: grid;
  gap: 22px;
}

.recommendation-item {
  width: 100%;
  display: grid;
  gap: 5px;
  padding: 12px 0;
  border: 0;
  border-bottom: 1px solid #e7efec;
  background: transparent;
  color: #253d39;
  text-align: left;
}

.recommendation-item span {
  color: #0f766e;
  font-size: 12px;
  font-weight: 800;
}

.recommendation-item p {
  margin: 0;
  color: #647773;
  font-size: 12px;
  line-height: 1.5;
}

.meeting-link {
  cursor: pointer;
}

.meeting-empty,
.side-empty {
  color: #71817e;
  text-align: center;
}

.meeting-empty {
  padding: 36px 16px;
}

.side-empty {
  font-size: 12px;
}

.meeting-error {
  padding: 10px 12px;
  border: 1px solid #efc9c3;
  border-radius: 8px;
  background: #fff5f3;
  color: #a33227;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
}

@media (max-width: 1050px) {
  .meeting-detail-grid {
    grid-template-columns: 1fr;
  }

  .meeting-form-grid,
  .material-inputs {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .upload-box {
    grid-column: 1 / -1;
  }

  .recommendation-panel {
    position: static;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .meeting-page {
    width: min(100% - 24px, 1440px);
    padding-top: 18px;
  }

  .meeting-toolbar,
  .meeting-head,
  .section-row,
  .task-strip {
    align-items: stretch;
    flex-direction: column;
  }

  .meeting-toolbar label {
    min-width: 0;
  }

  .meeting-summary {
    grid-template-columns: 1fr;
  }

  .meeting-summary dl,
  .knowledge-grid,
  .recommendation-panel {
    grid-template-columns: 1fr;
  }

  .meeting-form-grid,
  .material-inputs {
    grid-template-columns: 1fr;
  }

  .material-list li:not(.meeting-empty) {
    grid-template-columns: 1fr;
  }

  .report-actions,
  .media-row {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
