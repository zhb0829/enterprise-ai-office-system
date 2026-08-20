<template>
  <div class="page-shell policy-admin-page">
    <div class="page-head">
      <div>
        <h2>政策法规知识库</h2>
        <p class="page-sub">管理公开政策文件、条款切分状态与时效标签，问答只引用现行有效内容。</p>
      </div>
      <label class="upload-button">
        {{ uploading ? '解析中...' : '上传政策文件' }}
        <input type="file" accept=".pdf,.docx,.txt,.md" :disabled="uploading" @change="handleUpload" />
      </label>
    </div>

    <section class="panel source-panel">
      <div class="panel-head">
        <div>
          <h3>采集公开链接</h3>
          <p class="page-sub">仅采集用户主动提交的公开网页，正文提取后进入条款级索引。</p>
        </div>
      </div>
      <form class="source-form" @submit.prevent="handleCollect">
        <input v-model="sourceForm.url" type="url" required placeholder="https://www.gov.cn/..." aria-label="公开政策链接" />
        <input v-model="sourceForm.title" placeholder="文件名称（可选）" aria-label="文件名称" />
        <input v-model="sourceForm.industryTags" placeholder="行业标签，用逗号分隔" aria-label="行业标签" />
        <button class="primary-button" type="submit" :disabled="collecting">{{ collecting ? '采集中...' : '提交采集' }}</button>
      </form>
      <p v-if="message" class="page-sub feedback">{{ message }}</p>
    </section>

    <section class="panel">
      <div class="table-toolbar">
        <input v-model="keyword" placeholder="按文件名称筛选" aria-label="按文件名称筛选" @keyup.enter="loadDocuments" />
        <select v-model="status" aria-label="按时效筛选" @change="loadDocuments">
          <option value="">全部时效</option>
          <option value="现行有效">现行有效</option>
          <option value="已修订">已修订</option>
          <option value="已废止">已废止</option>
        </select>
        <button class="apply-button" type="button" @click="loadDocuments">刷新</button>
      </div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>文件名称</th><th>级别</th><th>来源</th><th>条款数</th><th>解析状态</th><th>时效</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="document in documents" :key="document.id">
              <td class="strong">{{ document.title }}<small class="table-note">{{ document.doc_number || '未填写文号' }}</small></td>
              <td>{{ document.level }}</td>
              <td><a v-if="document.source_url" :href="document.source_url" target="_blank" rel="noreferrer">公开链接</a><span v-else>上传文件</span></td>
              <td>{{ document.clause_count }}</td>
              <td><span class="check-badge ok">{{ document.parse_status }}</span></td>
              <td><span :class="['check-badge', document.status === '现行有效' ? 'ok' : 'warn']">{{ document.status }}</span></td>
              <td class="row-actions">
                <button v-if="document.status !== '现行有效'" class="apply-button" type="button" @click="setStatus(document, '现行有效')">标为有效</button>
                <button v-if="document.status !== '已废止'" class="apply-button danger" type="button" @click="setStatus(document, '已废止')">标为废止</button>
              </td>
            </tr>
            <tr v-if="!documents.length"><td colspan="7" class="empty-cell">暂无政策文件，请上传公开文件或提交公开链接</td></tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue';
import { collectPolicyUrl, fetchPolicyDocuments, updatePolicyDocumentStatus, uploadPolicyDocument } from '../../api';

const documents = ref([]);
const keyword = ref('');
const status = ref('');
const uploading = ref(false);
const collecting = ref(false);
const message = ref('');
const sourceForm = reactive({ url: '', title: '', industryTags: '' });

async function loadDocuments() {
  try {
    documents.value = await fetchPolicyDocuments({ keyword: keyword.value, status: status.value });
  } catch (error) {
    message.value = `加载失败：${error.message}`;
  }
}

async function handleUpload(event) {
  const [file] = event.target.files || [];
  if (!file) return;
  uploading.value = true;
  message.value = '';
  try {
    await uploadPolicyDocument(file, { level: '其他', industry_tags: sourceForm.industryTags });
    message.value = `已上传并完成解析：${file.name}`;
    await loadDocuments();
  } catch (error) {
    message.value = `上传失败：${error.message}`;
  } finally {
    uploading.value = false;
    event.target.value = '';
  }
}

async function handleCollect() {
  collecting.value = true;
  message.value = '';
  try {
    await collectPolicyUrl({
      url: sourceForm.url,
      title: sourceForm.title,
      industryTags: sourceForm.industryTags.split(',').map((item) => item.trim()).filter(Boolean),
    });
    message.value = '公开链接已采集并完成条款切分。';
    sourceForm.url = '';
    sourceForm.title = '';
    await loadDocuments();
  } catch (error) {
    message.value = `采集失败：${error.message}`;
  } finally {
    collecting.value = false;
  }
}

async function setStatus(document, nextStatus) {
  try {
    await updatePolicyDocumentStatus(document.id, nextStatus);
    await loadDocuments();
  } catch (error) {
    message.value = `状态更新失败：${error.message}`;
  }
}

onMounted(loadDocuments);
</script>

<style scoped>
.policy-admin-page { display: grid; gap: 18px; }
.source-panel { padding: 20px; }
.panel-head h3 { margin: 0; }
.source-form, .table-toolbar { display: grid; grid-template-columns: minmax(0, 1.8fr) minmax(140px, 1fr) minmax(160px, 1fr) auto; gap: 10px; align-items: center; margin-top: 14px; }
.table-toolbar { grid-template-columns: minmax(220px, 1fr) 160px auto; margin: 0 0 14px; }
.source-form input, .table-toolbar input, .table-toolbar select { min-height: 40px; border: 1px solid #d4dbe5; border-radius: 6px; padding: 8px 10px; background: #fff; }
.source-form .primary-button { width: auto; min-height: 40px; white-space: nowrap; }
.feedback { margin: 12px 0 0; color: #1d4ed8; }
.table-note { display: block; margin-top: 4px; color: #8a94a6; font-size: 12px; font-weight: 400; }
.row-actions { white-space: nowrap; }
@media (max-width: 900px) { .source-form, .table-toolbar { grid-template-columns: 1fr; } .source-form .primary-button { width: 100%; } }
</style>
