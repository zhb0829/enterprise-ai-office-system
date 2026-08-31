<template>
  <section class="page-shell meeting-admin">
    <header class="page-head">
      <div>
        <h2>会议公开信息整理</h2>
        <p class="page-sub">公开会议录入、资料管理与整理任务监控。</p>
      </div>
      <div class="head-actions">
        <button class="ghost-button" type="button" :disabled="loading" @click="loadMeetings">刷新</button>
      </div>
    </header>

    <p v-if="errorMessage" class="error-text" role="alert">{{ errorMessage }}</p>

    <section class="panel filter-bar">
      <label class="field">
        <span>关键词</span>
        <input v-model.trim="filters.keyword" type="search" placeholder="会议、主办方、关键词" @keyup.enter="loadMeetings" />
      </label>
      <label class="field">
        <span>状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option value="draft">待整理</option>
          <option value="processing">整理中</option>
          <option value="completed">已完成</option>
        </select>
      </label>
      <button class="ghost-button filter-apply" type="button" @click="loadMeetings">应用筛选</button>
    </section>

    <section class="panel">
      <div v-if="!meetings.length && !loading" class="empty-state">暂无会议。</div>
      <div v-else class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>会议</th>
              <th>类型</th>
              <th>时间</th>
              <th>资料</th>
              <th>状态</th>
              <th>纪要</th>
              <th>创建人</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in meetings" :key="item.id">
              <td class="strong">{{ item.name }}</td>
              <td>{{ item.category }}</td>
              <td>{{ formatTime(item.startTime) }}</td>
              <td>{{ item.materialCount }} 份</td>
              <td><span :class="['task-status', item.status]">{{ statusText(item.status) }}</span></td>
              <td>{{ item.latestVersion ? `v${item.latestVersion}` : '-' }}</td>
              <td>{{ item.createdBy || '-' }}</td>
              <td class="row-actions">
                <button class="ghost-button compact" type="button" @click="openDetail(item.id)">管理</button>
                <button class="ghost-button compact" type="button" @click="editMeeting(item.id)">编辑</button>
                <button class="ghost-button compact danger" type="button" @click="removeRow(item)">删除</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section v-if="editing" class="panel editor-panel">
      <div class="page-head">
        <div>
          <h3>{{ editing.id ? '编辑会议' : '新建会议' }}</h3>
          <p class="page-sub">会议名称与关键词将用于后续公开报道采集和关联检索。</p>
        </div>
        <button class="ghost-button" type="button" @click="editing = null">关闭</button>
      </div>
      <div class="form-grid">
        <label class="field field-wide"><span>会议名称</span><input v-model.trim="editing.name" maxlength="256" /></label>
        <label class="field"><span>类型</span>
          <select v-model="editing.category">
            <option>行业会议</option><option>论坛</option><option>发布会</option><option>其他</option>
          </select>
        </label>
        <label class="field"><span>主办方</span><input v-model.trim="editing.organizer" /></label>
        <label class="field"><span>开始时间</span><input v-model="editing.startTime" type="datetime-local" /></label>
        <label class="field"><span>结束时间</span><input v-model="editing.endTime" type="datetime-local" /></label>
        <label class="field"><span>地点</span><input v-model.trim="editing.location" /></label>
        <label class="field"><span>采集关键词</span><input v-model.trim="editing.keywords" placeholder="使用逗号分隔" /></label>
        <label class="field"><span>竞品名单</span><input v-model.trim="editing.competitors" placeholder="逗号分隔，用于竞品动态关联" /></label>
        <label class="field field-wide"><span>简介</span><textarea v-model.trim="editing.description" rows="4"></textarea></label>
      </div>
      <div class="modal-actions">
        <button class="primary-button" type="button" :disabled="saving" @click="saveMeeting">
          {{ saving ? '保存中…' : '保存会议' }}
        </button>
      </div>
    </section>

    <section v-if="detail" class="meeting-detail">
      <section class="panel detail-header">
        <div>
          <span :class="['task-status', detail.conference.status]">{{ statusText(detail.conference.status) }}</span>
          <h3>{{ detail.conference.name }}</h3>
          <p>{{ detail.conference.organizer || '主办方未填写' }} · {{ formatTime(detail.conference.startTime) }}</p>
        </div>
        <div class="head-actions">
          <button
            class="primary-button"
            type="button"
            :disabled="detail.conference.status === 'processing' || !detail.materials.length"
            @click="organize"
          >
            {{ detail.latestReport ? '重新整理' : '开始整理' }}
          </button>
          <button class="ghost-button danger" type="button" :disabled="detail.conference.status === 'processing'" @click="removeMeeting">
            删除
          </button>
          <button class="ghost-button" type="button" @click="closeDetail">关闭</button>
        </div>
      </section>

      <section class="panel material-panel">
        <div class="page-head">
          <div>
            <h3>会议资料</h3>
            <p class="page-sub">{{ detail.materials.length }}/50 份</p>
          </div>
        </div>
        <div class="material-inputs">
          <form @submit.prevent="addLink">
            <label class="field"><span>公开资料链接</span><input v-model.trim="linkForm.url" type="url" required /></label>
            <label class="field"><span>标题</span><input v-model.trim="linkForm.title" /></label>
            <button class="ghost-button" type="submit">添加链接</button>
          </form>
          <form @submit.prevent="addTranscript">
            <label class="field"><span>转录稿标题</span><input v-model.trim="transcriptForm.title" /></label>
            <label class="field transcript-field"><span>转录文本</span><textarea v-model="transcriptForm.content" rows="4" required></textarea></label>
            <button class="ghost-button" type="submit">添加转录稿</button>
          </form>
          <label class="upload-box">
            <span>上传 PDF、Word、PPTX、图片或音频</span>
            <input type="file" @change="uploadMaterial" />
          </label>
        </div>
        <div class="material-list">
          <article v-for="item in detail.materials" :key="item.id">
            <div>
              <strong>{{ item.title }}</strong>
              <span>{{ materialTypeText(item.materialType) }} · {{ sizeText(item.sizeBytes) }}</span>
            </div>
            <span :class="['parse-status', item.parseStatus]">{{ parseStatusText(item.parseStatus) }}</span>
            <p v-if="item.parseResult?.error">{{ item.parseResult.error }}</p>
            <button
              class="ghost-button compact danger"
              type="button"
              :disabled="detail.conference.status === 'processing'"
              @click="removeMaterial(item)"
            >删除</button>
          </article>
          <div v-if="!detail.materials.length" class="empty-state">尚未添加资料。</div>
        </div>
      </section>

      <section class="panel task-panel">
        <div class="page-head">
          <div>
            <h3>整理任务</h3>
            <p class="page-sub">五步进度、耗时与失败详情。</p>
          </div>
        </div>
        <article v-for="task in detail.tasks" :key="task.id" class="task-row">
          <header>
            <div>
              <strong>任务 #{{ task.id }}</strong>
              <span :class="['task-status', task.status]">{{ taskStatusText(task.status) }}</span>
            </div>
            <button
              v-if="task.status === 'failed'"
              class="ghost-button compact"
              type="button"
              @click="retryTask(task)"
            >断点重试</button>
          </header>
          <div class="task-steps">
            <div v-for="step in task.progress || []" :key="step.step" :class="['task-step', step.status]">
              <strong>{{ step.label }}</strong>
              <span>{{ stepStatusText(step.status) }}<template v-if="step.elapsedMs"> · {{ step.elapsedMs }}ms</template></span>
              <p v-if="step.error">{{ step.error }}</p>
            </div>
          </div>
          <p v-if="task.error" class="task-error">{{ task.error }}</p>
        </article>
        <div v-if="!detail.tasks.length" class="empty-state">尚未发起整理任务。</div>
      </section>

      <section v-if="detail.latestReport" class="panel result-summary">
        <div><span>最新纪要</span><strong>v{{ detail.latestReport.version }}</strong></div>
        <div><span>知识卡片</span><strong>{{ detail.cards.length }}</strong></div>
        <div><span>政策推荐</span><strong>{{ detail.latestReport.relatedPolicies?.length || 0 }}</strong></div>
        <div><span>竞品动态</span><strong>{{ detail.latestReport.relatedCompetitors?.length || 0 }}</strong></div>
        <div><span>历史会议</span><strong>{{ detail.latestReport.relatedConferences?.length || 0 }}</strong></div>
        <div><span>媒体报道</span><strong>{{ detail.media.length }}</strong></div>
      </section>
    </section>
  </section>
</template>

<script setup>
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue';
import {
  addAdminMeetingLink,
  addAdminMeetingTranscript,
  createAdminMeeting,
  deleteAdminMeeting,
  deleteAdminMeetingMaterial,
  fetchAdminMeetingDetail,
  fetchAdminMeetings,
  organizeAdminMeeting,
  retryAdminMeetingTask,
  updateAdminMeeting,
  uploadAdminMeetingMaterial,
} from '../../api';

const meetings = ref([]);
const detail = ref(null);
const editing = ref(null);
const loading = ref(false);
const saving = ref(false);
const errorMessage = ref('');
const filters = reactive({ keyword: '', status: '' });
const linkForm = reactive({ url: '', title: '' });
const transcriptForm = reactive({ title: '', content: '' });
let timer = null;

function formatTime(value) {
  return value ? new Date(value).toLocaleString('zh-CN', { dateStyle: 'short', timeStyle: 'short' }) : '-';
}

function toInputTime(value) {
  if (!value) return '';
  const date = new Date(value);
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 16);
}

function toPayloadTime(value) {
  return value ? value.replace('T', ' ') : null;
}

function statusText(value) {
  return { draft: '待整理', processing: '整理中', completed: '已完成' }[value] || value;
}

function taskStatusText(value) {
  return { pending: '等待派发', running: '运行中', partial: '部分完成', succeeded: '成功', failed: '失败' }[value] || value;
}

function stepStatusText(value) {
  return { pending: '等待', running: '进行中', retrying: '重试中', completed: '完成', failed: '失败' }[value] || value;
}

function parseStatusText(value) {
  return { pending: '待解析', parsed: '已解析', failed: '解析失败' }[value] || value;
}

function materialTypeText(value) {
  return { link: '链接', file: '文件', transcript: '转录稿', image: '图片', audio: '音频' }[value] || value;
}

function sizeText(value) {
  const bytes = Number(value || 0);
  if (!bytes) return '-';
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${Math.ceil(bytes / 1024)} KB`;
}

function blankMeeting() {
  return {
    id: null,
    name: '',
    category: '行业会议',
    startTime: '',
    endTime: '',
    location: '',
    organizer: '',
    keywords: '',
    competitors: '',
    description: '',
  };
}

async function loadMeetings() {
  loading.value = true;
  errorMessage.value = '';
  try {
    meetings.value = (await fetchAdminMeetings(filters))?.items || [];
    schedulePolling();
  } catch (error) {
    errorMessage.value = error.message;
  } finally {
    loading.value = false;
  }
}

async function openDetail(id) {
  errorMessage.value = '';
  try {
    detail.value = await fetchAdminMeetingDetail(id);
    schedulePolling();
  } catch (error) {
    errorMessage.value = error.message;
  }
}

function closeDetail() {
  detail.value = null;
}

async function editMeeting(id) {
  try {
    const data = await fetchAdminMeetingDetail(id);
    const item = data.conference;
    editing.value = {
      ...item,
      startTime: toInputTime(item.startTime),
      endTime: toInputTime(item.endTime),
    };
  } catch (error) {
    errorMessage.value = error.message;
  }
}

async function saveMeeting() {
  if (!editing.value?.name) {
    errorMessage.value = '会议名称不能为空';
    return;
  }
  saving.value = true;
  errorMessage.value = '';
  const payload = {
    ...editing.value,
    startTime: toPayloadTime(editing.value.startTime),
    endTime: toPayloadTime(editing.value.endTime),
  };
  try {
    const saved = editing.value.id
      ? await updateAdminMeeting(editing.value.id, payload)
      : await createAdminMeeting(payload);
    editing.value = null;
    await loadMeetings();
    await openDetail(saved.id);
  } catch (error) {
    errorMessage.value = error.message;
  } finally {
    saving.value = false;
  }
}

async function addLink() {
  if (!detail.value) return;
  try {
    await addAdminMeetingLink(detail.value.conference.id, linkForm);
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
    await addAdminMeetingTranscript(detail.value.conference.id, transcriptForm);
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
    await uploadAdminMeetingMaterial(detail.value.conference.id, file);
    event.target.value = '';
    await openDetail(detail.value.conference.id);
  } catch (error) {
    errorMessage.value = error.message;
  }
}

async function removeMaterial(item) {
  if (!window.confirm(`确认删除资料“${item.title}”？`)) return;
  try {
    await deleteAdminMeetingMaterial(detail.value.conference.id, item.id);
    await openDetail(detail.value.conference.id);
  } catch (error) {
    errorMessage.value = error.message;
  }
}

async function organize() {
  if (!window.confirm('确认开始整理？系统将采集公开报道并生成新版本纪要。')) return;
  try {
    await organizeAdminMeeting(detail.value.conference.id);
    await openDetail(detail.value.conference.id);
    await loadMeetings();
  } catch (error) {
    errorMessage.value = error.message;
  }
}

async function retryTask(task) {
  if (!window.confirm('确认重试？已解析成功的资料不会重复解析。')) return;
  try {
    await retryAdminMeetingTask(detail.value.conference.id, task.id);
    await openDetail(detail.value.conference.id);
  } catch (error) {
    errorMessage.value = error.message;
  }
}

async function removeRow(item) {
  if (!window.confirm(`确认永久删除“${item.name}”？其全部资料、纪要与关联推荐将一并清除，用户端不再显示该记录。`)) return;
  try {
    await deleteAdminMeeting(item.id);
    if (detail.value?.conference.id === item.id) detail.value = null;
    await loadMeetings();
  } catch (error) {
    errorMessage.value = error.message;
  }
}

async function removeMeeting() {
  if (!window.confirm(`确认永久删除“${detail.value.conference.name}”及其全部资料和纪要？`)) return;
  try {
    await deleteAdminMeeting(detail.value.conference.id);
    detail.value = null;
    await loadMeetings();
  } catch (error) {
    errorMessage.value = error.message;
  }
}

function schedulePolling() {
  if (timer) window.clearTimeout(timer);
  const processing = meetings.value.some((item) => item.status === 'processing')
    || detail.value?.conference.status === 'processing';
  if (processing) {
    timer = window.setTimeout(async () => {
      await loadMeetings();
      if (detail.value) await openDetail(detail.value.conference.id);
    }, 5000);
  }
}

onMounted(loadMeetings);
onBeforeUnmount(() => {
  if (timer) window.clearTimeout(timer);
});
</script>

<style scoped>
.meeting-admin {
  max-width: 1400px;
}

.primary-button,
.ghost-button {
  min-height: 38px;
  padding: 8px 14px;
  border-radius: 8px;
  font-weight: 700;
}

.primary-button {
  border: 0;
  background: #1f6feb;
  color: #fff;
}

.ghost-button {
  border: 1px solid #cfd6e3;
  background: #fff;
  color: #1f4f9f;
}

.ghost-button.compact {
  min-height: 32px;
  padding: 5px 8px;
  font-size: 12px;
}

.ghost-button.danger {
  border-color: #efc7c2;
  color: #b42318;
}

.filter-bar,
.head-actions,
.row-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.filter-bar {
  align-items: end;
}

.filter-bar .field {
  min-width: 200px;
}

.field {
  display: grid;
  gap: 6px;
  color: #374861;
  font-size: 13px;
  font-weight: 700;
}

.field input,
.field select,
.field textarea {
  width: 100%;
  min-height: 38px;
  border: 1px solid #d3dae5;
  border-radius: 7px;
  padding: 8px 10px;
  background: #fff;
  color: #17233a;
}

.field textarea {
  resize: vertical;
  line-height: 1.6;
}

.task-status,
.parse-status {
  display: inline-flex;
  min-height: 24px;
  align-items: center;
  padding: 3px 8px;
  border-radius: 12px;
  background: #eef1f6;
  color: #586579;
  font-size: 11px;
  font-weight: 800;
}

.task-status.processing,
.task-status.running,
.task-status.partial,
.parse-status.pending {
  background: #fff2df;
  color: #a34b0d;
}

.task-status.completed,
.task-status.succeeded,
.parse-status.parsed {
  background: #e7f6ed;
  color: #14723a;
}

.task-status.failed,
.parse-status.failed {
  background: #fff0ee;
  color: #b42318;
}

.editor-panel,
.meeting-detail,
.material-panel,
.task-panel {
  display: grid;
  gap: 16px;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.field-wide {
  grid-column: 1 / -1;
}

.detail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.detail-header h3 {
  margin: 8px 0 4px;
  color: #17233a;
}

.detail-header p {
  margin: 0;
  color: #64748b;
  font-size: 13px;
}

.material-inputs {
  display: grid;
  grid-template-columns: 1fr 1.4fr 0.8fr;
  gap: 12px;
}

.material-inputs form {
  display: grid;
  align-content: start;
  gap: 10px;
  padding: 12px;
  border: 1px solid #e0e6ee;
  border-radius: 8px;
}

.upload-box {
  min-height: 150px;
  display: grid;
  place-items: center;
  padding: 16px;
  border: 1px dashed #9db0ca;
  border-radius: 8px;
  background: #f8fafc;
  color: #425d83;
  font-size: 13px;
  font-weight: 700;
  text-align: center;
  cursor: pointer;
}

.upload-box input {
  width: 100%;
}

.material-list {
  display: grid;
  gap: 8px;
}

.material-list article {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  gap: 12px;
  align-items: center;
  padding: 10px 12px;
  border: 1px solid #e3e8ef;
  border-radius: 8px;
}

.material-list article > div {
  min-width: 0;
  display: grid;
  gap: 3px;
}

.material-list article span,
.material-list article p {
  color: #64748b;
  font-size: 12px;
}

.material-list article p {
  grid-column: 1 / -1;
  margin: 0;
}

.task-row {
  display: grid;
  gap: 12px;
  padding: 14px 0;
  border-bottom: 1px solid #e4e9f0;
}

.task-row header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.task-row header > div {
  display: flex;
  align-items: center;
  gap: 10px;
}

.task-steps {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 8px;
}

.task-step {
  min-width: 0;
  padding: 10px;
  border: 1px solid #e1e7ef;
  border-top: 3px solid #cbd5e1;
  border-radius: 6px;
  background: #fbfcfe;
}

.task-step.completed {
  border-top-color: #16803c;
}

.task-step.running,
.task-step.retrying {
  border-top-color: #d97706;
}

.task-step.failed {
  border-top-color: #d92d20;
}

.task-step strong,
.task-step span {
  display: block;
  overflow-wrap: anywhere;
}

.task-step strong {
  font-size: 12px;
}

.task-step span,
.task-step p,
.task-error {
  color: #64748b;
  font-size: 11px;
}

.task-step p,
.task-error {
  margin: 6px 0 0;
}

.task-error {
  color: #b42318;
}

.result-summary {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 1px;
  padding: 0;
  overflow: hidden;
  background: #e1e7ef;
}

.result-summary div {
  display: grid;
  gap: 5px;
  padding: 16px;
  background: #fff;
}

.result-summary span {
  color: #64748b;
  font-size: 12px;
}

.result-summary strong {
  color: #17233a;
  font-size: 22px;
}

@media (max-width: 1050px) {
  .form-grid,
  .material-inputs {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .upload-box {
    grid-column: 1 / -1;
  }

  .task-steps,
  .result-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .form-grid,
  .material-inputs,
  .task-steps,
  .result-summary {
    grid-template-columns: 1fr;
  }

  .detail-header {
    align-items: stretch;
    flex-direction: column;
  }

  .material-list article {
    grid-template-columns: 1fr;
  }
}
</style>
