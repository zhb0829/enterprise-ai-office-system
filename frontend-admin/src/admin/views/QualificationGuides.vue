<template>
  <section class="page-shell">
    <header class="page-head">
      <div>
        <h2>资质指南库</h2>
        <p class="page-sub">上传官方原生文字版指南，解析后形成可锁定的 schema 版本。</p>
      </div>
      <button class="primary-button" type="button" @click="showUpload = !showUpload">
        {{ showUpload ? '收起上传' : '上传指南' }}
      </button>
    </header>

    <p v-if="errorMessage" class="error-text" role="alert">{{ errorMessage }}</p>

    <section v-if="showUpload" class="panel upload-panel">
      <div class="page-head">
        <div>
          <h3>新增指南版本</h3>
          <p class="page-sub">只接受 PDF、Word、TXT、Markdown；扫描件 OCR 暂不启用。</p>
        </div>
      </div>
      <div class="guide-form-grid">
        <label class="field">
          <span>资质类型</span>
          <input v-model.trim="form.qualificationType" required placeholder="例如：高新技术企业认定" />
        </label>
        <label class="field">
          <span>指南名称</span>
          <input v-model.trim="form.guideName" required placeholder="例如：2026 年申报指南" />
        </label>
        <label class="field">
          <span>版本</span>
          <input v-model.trim="form.version" required placeholder="例如：2026-v1" />
        </label>
        <label class="field">
          <span>来源链接</span>
          <input v-model.trim="form.sourceUrl" type="url" placeholder="https://..." />
        </label>
      </div>
      <label class="file-picker">
        <input type="file" accept=".pdf,.docx,.txt,.md" @change="file = $event.target.files?.[0] || null" />
        {{ file?.name || '选择官方指南文件' }}
      </label>
      <div class="modal-actions">
        <button class="primary-button small-primary" type="button" :disabled="loading || !file || !form.qualificationType || !form.guideName" @click="upload">
          {{ loading ? '解析并保存中…' : '解析并保存 ACTIVE 版本' }}
        </button>
      </div>
    </section>

    <section class="panel">
      <div v-if="!guides.length && !loading" class="empty-state">暂无已解析指南。</div>
      <div v-else class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>资质类型</th>
              <th>指南名称</th>
              <th>版本</th>
              <th>解析结构</th>
              <th>状态</th>
              <th>来源</th>
              <th>创建时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="guide in guides" :key="guide.id">
              <td>{{ guide.qualificationType }}</td>
              <td>{{ guide.guideName }}</td>
              <td><code>{{ guide.version }}</code></td>
              <td>{{ guide.schema?.sections?.length || 0 }} 章节 · {{ guide.materialChecklist?.length || 0 }} 材料</td>
              <td><span class="status-pill online"><span></span>{{ guide.status }}</span></td>
              <td>
                <a v-if="guide.sourceUrl" :href="guide.sourceUrl" target="_blank" rel="noreferrer">打开来源</a>
                <span v-else class="muted">上传文件</span>
              </td>
              <td>{{ formatDate(guide.createdAt) }}</td>
              <td>
                <button class="ghost-button" type="button" @click="viewing = viewing?.id === guide.id ? null : guide">
                  {{ viewing?.id === guide.id ? '收起' : '查看' }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section v-if="viewing" class="panel guide-detail">
      <div class="page-head">
        <div>
          <h3>指南解析详情（只读）</h3>
          <p class="page-sub">{{ viewing.qualificationType }} · {{ viewing.guideName }} · {{ viewing.version }} · {{ viewing.status }}</p>
        </div>
        <button class="ghost-button" type="button" @click="viewing = null">关闭</button>
      </div>

      <h4 class="detail-subtitle">章节结构（{{ sections.length }}）</h4>
      <article v-for="(section, index) in sections" :key="section.key || index" class="section-card">
        <h5>{{ index + 1 }}. {{ section.title || section.name || '未命名章节' }}</h5>
        <p v-for="(block, bIndex) in section.blocks || []" :key="bIndex">{{ block.text || '（占位章节，由编制任务填充内容）' }}</p>
        <span v-if="section.required" class="required-mark">必填</span>
      </article>

      <h4 class="detail-subtitle">材料清单（{{ checklist.length }}）</h4>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>材料名称</th>
              <th>要求</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(item, index) in checklist" :key="index">
              <td>{{ index + 1 }}</td>
              <td>{{ item.name || item.materialName || '-' }}</td>
              <td>
                <span :class="['status-pill', { online: !item.optional }]">
                  <span></span>{{ item.optional ? '可选' : '必需' }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { fetchQualGuides, uploadQualGuide } from '../../api';

const guides = ref([]);
const file = ref(null);
const showUpload = ref(false);
const loading = ref(false);
const errorMessage = ref('');
const viewing = ref(null);
const form = reactive({
  qualificationType: '',
  guideName: '',
  version: '2026-v1',
  sourceUrl: '',
});

const sections = computed(() => viewing.value?.schema?.sections || []);
const checklist = computed(() => viewing.value?.materialChecklist || []);

function formatDate(value) {
  return value ? new Date(value).toLocaleString('zh-CN') : '-';
}

async function loadGuides() {
  try {
    const data = await fetchQualGuides();
    guides.value = data?.data ?? data ?? [];
  } catch (error) {
    errorMessage.value = error.message;
  }
}

async function upload() {
  loading.value = true;
  errorMessage.value = '';
  try {
    const guide = await uploadQualGuide(file.value, form);
    guides.value = [guide, ...guides.value];
    file.value = null;
    showUpload.value = false;
    Object.assign(form, { qualificationType: '', guideName: '', version: '2026-v1', sourceUrl: '' });
  } catch (error) {
    errorMessage.value = error.message;
  } finally {
    loading.value = false;
  }
}

onMounted(loadGuides);
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
  min-width: 170px;
}

.upload-panel {
  display: grid;
  gap: 16px;
}

.guide-form-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.field {
  display: grid;
  gap: 7px;
  color: #263a37;
  font-size: 13px;
  font-weight: 700;
}

.field input {
  width: 100%;
  border: 1px solid #d6dce6;
  border-radius: 7px;
  padding: 9px 10px;
  color: #17233a;
}

.file-picker {
  display: block;
  padding: 16px;
  border: 1px dashed #9fb9b3;
  border-radius: 8px;
  color: #36524f;
  background: #f5fbf9;
  cursor: pointer;
  font-size: 13px;
}

.file-picker input {
  display: none;
}

.empty-state {
  padding: 28px 12px;
  color: #64748b;
  text-align: center;
}

.muted {
  color: #64748b;
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

.guide-detail {
  display: grid;
  gap: 14px;
}

.detail-subtitle {
  margin: 8px 0 0;
  padding-top: 12px;
  border-top: 1px solid #e2e8f0;
  font-size: 14px;
  color: #17233a;
}

.section-card {
  position: relative;
  padding: 10px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}

.section-card h5 {
  margin: 0 0 6px;
  color: #17233a;
}

.section-card p {
  margin: 4px 0;
  color: #475569;
  font-size: 13px;
  line-height: 1.7;
}

.required-mark {
  position: absolute;
  top: 10px;
  right: 12px;
  color: #94a3b8;
  font-size: 11px;
}

@media (max-width: 900px) {
  .guide-form-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 600px) {
  .guide-form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
