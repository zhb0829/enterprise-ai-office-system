<template>
  <div class="page-shell">
    <div class="page-head">
      <h2>稿件审核</h2>
      <div class="row-actions">
        <label>状态 <select v-model="status" :disabled="busy" @change="offset = 0; loadList()">
          <option>审阅</option><option>草稿</option><option>发布</option>
        </select></label>
        <button type="button" class="ghost-button" :disabled="busy" @click="loadList">刷新</button>
      </div>
    </div>
    <p v-if="error" class="load-failed" role="alert">{{ error }}</p>
    <p v-if="message" role="status">{{ message }}</p>
    <section class="table-wrap" aria-label="稿件列表">
      <table>
        <thead><tr><th>标题</th><th>版本</th><th>作者</th><th>状态</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="item in items" :key="item.id">
            <td class="strong">{{ item.title || '未命名稿件' }}</td><td>v{{ item.version }}</td>
            <td>{{ item.createdBy || '未记录' }}</td><td>{{ item.status }}</td>
            <td><button type="button" class="apply-button" :disabled="busy" @click="openDraft(item.id)">查看</button></td>
          </tr>
          <tr v-if="!items.length"><td colspan="5" class="empty-cell">{{ busy ? '加载中...' : '暂无稿件' }}</td></tr>
        </tbody>
      </table>
    </section>
    <div class="row-actions">
      <button type="button" class="ghost-button" :disabled="busy || offset === 0" @click="offset -= 20; loadList()">上一页</button>
      <span>{{ total }} 条</span>
      <button type="button" class="ghost-button" :disabled="busy || offset + 20 >= total" @click="offset += 20; loadList()">下一页</button>
    </div>
    <section v-if="draft" class="review-detail" aria-label="审核详情">
      <div class="page-head"><h3>{{ draft.title || '未命名稿件' }} · v{{ draft.version }}</h3><span>{{ draft.status }}</span></div>
      <pre class="review-content">{{ draft.content }}</pre>
      <h3>事实证据</h3>
      <div v-for="item in draft.evidence" :key="item.id" class="review-evidence">
        <div class="fact-topline"><strong>{{ item.claim }}</strong>
          <span :class="['check-badge', item.status === '一致' ? 'ok' : 'warn']">{{ item.status }}</span>
        </div>
        <pre v-for="(source, index) in item.sources" :key="index">{{ JSON.stringify(source, null, 2) }}</pre>
        <p v-if="!item.sources?.length">无可定位证据</p>
      </div>
      <p v-if="!draft.evidence?.length">暂无事实证据</p>
      <h3>审核记录</h3>
      <p v-for="item in draft.reviews" :key="item.id">
        {{ decisionLabel(item.decision) }} · {{ item.reviewerId }} · {{ item.createdAt }}<br />{{ item.comment }}
      </p>
      <label class="field" v-if="draft.status === '审阅'"><span>审核意见</span>
        <textarea v-model="comment" rows="3" maxlength="4000"></textarea>
      </label>
      <div class="row-actions">
        <button v-if="draft.status !== '发布'" type="button" class="ghost-button" :disabled="busy" @click="perform('verify')">重新核查</button>
        <button v-if="draft.status === '草稿'" type="button" class="apply-button" :disabled="busy" @click="perform('submit')">送审</button>
        <button v-if="draft.status === '审阅'" type="button" class="apply-button danger" :disabled="busy || !comment.trim()" @click="perform('reject')">退回</button>
        <button v-if="draft.status === '审阅'" type="button" class="primary-button" :disabled="busy || !evidenceReady" @click="perform('approve')">审核通过</button>
        <button v-if="draft.status === '审阅'" type="button" class="primary-button" :disabled="busy || !approved" @click="perform('publish')">发布</button>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { fetchDraft, fetchReviewDrafts, submitDraftReview, updateReviewDraftStatus, verifyDraft } from '../../api';

const items = ref([]);
const total = ref(0);
const offset = ref(0);
const status = ref('审阅');
const draft = ref(null);
const comment = ref('');
const busy = ref(false);
const error = ref('');
const message = ref('');
const evidenceReady = computed(() => draft.value?.evidence?.length > 0
  && draft.value.evidence.every((item) => item.status === '一致' && item.sources?.length > 0));
const approved = computed(() => evidenceReady.value && draft.value?.reviews?.at(-1)?.decision === 'approve');
const decisionLabel = (value) => ({ approve: '通过', reject: '退回', invalidated: '审批失效' }[value] || value);

async function loadList() {
  busy.value = true;
  error.value = '';
  try {
    const result = await fetchReviewDrafts(status.value, offset.value);
    items.value = result.items;
    total.value = result.total;
  } catch (e) {
    items.value = [];
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}

async function openDraft(id) {
  busy.value = true;
  error.value = '';
  draft.value = null;
  comment.value = '';
  try { draft.value = await fetchDraft(id); }
  catch (e) { error.value = e.message; }
  finally { busy.value = false; }
}

async function perform(action) {
  if (action === 'publish' && !window.confirm('确认发布当前已审批版本？')) return;
  busy.value = true;
  error.value = '';
  message.value = '';
  const id = draft.value.id;
  try {
    if (action === 'verify') await verifyDraft(id);
    else if (action === 'submit' || action === 'publish') await updateReviewDraftStatus(id, action === 'submit' ? '审阅' : '发布');
    else await submitDraftReview(id, action, comment.value);
    draft.value = await fetchDraft(id);
    const result = await fetchReviewDrafts(status.value, offset.value);
    items.value = result.items;
    total.value = result.total;
    message.value = '操作已完成';
  } catch (e) { error.value = e.message; }
  finally { busy.value = false; }
}

onMounted(loadList);
</script>

<style scoped>
.page-shell { min-width: 0; }
.page-head { flex-wrap: wrap; }
.table-wrap { min-width: 0; overflow-x: auto; }
.table-wrap table { min-width: 560px; }
.review-detail { padding: 24px 0; border-top: 1px solid var(--line, #ddd); }
.review-content, .review-evidence pre { white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; line-height: 1.7; }
.review-evidence { padding: 16px 0; border-bottom: 1px solid var(--line, #ddd); }
.review-detail h3 { margin: 20px 0 12px; }
.row-actions { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; }
.row-actions label { display: flex; align-items: center; gap: 8px; }
.row-actions select { width: auto; min-width: 88px; }
.row-actions > .primary-button { width: auto; }
.review-detail textarea { width: 100%; box-sizing: border-box; }
.fact-topline strong { min-width: 0; overflow-wrap: anywhere; }
</style>
