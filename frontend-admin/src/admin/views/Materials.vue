<template>
  <div class="page-shell">
    <div class="page-head">
      <div>
        <h2>素材管理</h2>
        <p class="page-sub">上传参考素材（md/txt/docx/pdf），生成时注入上下文</p>
      </div>
      <label class="upload-button">
        {{ uploading ? '上传中...' : '上传素材' }}
        <input type="file" :disabled="uploading" @change="handleUpload" />
      </label>
    </div>

    <section class="panel">
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>文件名</th><th>类型</th><th>状态</th><th>字数</th><th>上传时间</th><th>操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="m in materials" :key="m.id">
              <td class="strong">{{ m.filename }}</td>
              <td>{{ m.content_type || '—' }}</td>
              <td>
                <span :class="['check-badge', m.status === '已入库' ? 'ok' : 'warn']">{{ m.status }}</span>
              </td>
              <td>{{ m.text_length ?? 0 }}</td>
              <td>{{ formatDate(m.created_at) }}</td>
              <td class="row-actions">
                <button class="apply-button" type="button" @click="preview(m)">预览</button>
                <button class="apply-button danger" type="button" @click="remove(m)">删除</button>
              </td>
            </tr>
            <tr v-if="!materials.length"><td colspan="6" class="empty-cell">暂无素材，点击右上角上传</td></tr>
          </tbody>
        </table>
      </div>
    </section>

    <div v-if="previewItem" class="modal-mask" @click.self="previewItem = null">
      <div class="modal wide">
        <div class="modal-head">
          <h3>{{ previewItem.filename }}</h3>
          <button class="icon-button danger" type="button" @click="previewItem = null">×</button>
        </div>
        <pre class="preview-body">{{ previewText }}</pre>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue';
import { deleteMaterial, fetchMaterial, fetchMaterials, uploadMaterial } from '../../api';
import { demoMaterials } from '../../demoData';

const materials = ref(demoMaterials);
const uploading = ref(false);
const previewItem = ref(null);
const previewText = ref('');

async function loadMaterials() {
  try {
    const rows = await fetchMaterials();
    materials.value = rows.length ? rows : demoMaterials;
  } catch {
    // 保留演示数据
  }
}

async function handleUpload(event) {
  const [file] = event.target.files || [];
  if (!file) return;
  uploading.value = true;
  try {
    const material = await uploadMaterial(file);
    await loadMaterials();
    alert(`上传成功：${material.filename}`);
  } catch (error) {
    alert(`上传失败：${error.message}`);
  } finally {
    uploading.value = false;
    event.target.value = '';
  }
}

async function preview(m) {
  try {
    const detail = await fetchMaterial(m.id);
    previewText.value = detail.text_content || '（无文本内容）';
    previewItem.value = m;
  } catch (error) {
    alert(`加载失败：${error.message}`);
  }
}

async function remove(m) {
  if (!window.confirm(`确定删除素材「${m.filename}」？`)) return;
  try {
    await deleteMaterial(m.id);
    await loadMaterials();
  } catch (error) {
    alert(`删除失败：${error.message}`);
  }
}

function formatDate(value) {
  if (!value) return '';
  let text = String(value);
  if (!/(Z|[+-]\d{2}:?\d{2})$/.test(text)) text += 'Z';
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  }).format(new Date(text));
}

onMounted(loadMaterials);
</script>