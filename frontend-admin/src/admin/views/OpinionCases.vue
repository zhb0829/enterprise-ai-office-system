<template>
  <div class="page-shell opinion-cases-page">
    <div class="page-head">
      <div>
        <h2>历史应对案例</h2>
        <p class="page-sub">维护历史舆情处置案例，供 RAG 检索与应对建议生成引用。新建/修改后请重建向量索引。</p>
      </div>
      <div class="head-actions">
        <button class="apply-button head-button" type="button" :disabled="reindexing" @click="reindex">{{ reindexing ? '重建索引中...' : '重建 RAG 索引' }}</button>
      </div>
    </div>

    <section class="panel">
      <div class="panel-head"><h3>新增案例</h3></div>
      <form class="case-form" @submit.prevent="createCase">
        <input v-model="form.title" required placeholder="案例标题" aria-label="案例标题" />
        <input v-model="form.eventType" placeholder="事件类型" aria-label="事件类型" />
        <select v-model="form.riskLevel" aria-label="风险等级"><option value="关注">关注</option><option value="预警">预警</option><option value="危机">危机</option></select>
        <input v-model="form.tags" placeholder="标签，逗号分隔" aria-label="标签" />
        <input v-model="form.source" placeholder="来源" aria-label="来源" />
        <textarea v-model="form.strategy" rows="2" placeholder="应对策略" aria-label="应对策略"></textarea>
        <textarea v-model="form.content" rows="2" placeholder="处置过程" aria-label="处置过程"></textarea>
        <textarea v-model="form.effect" rows="1" placeholder="处置效果" aria-label="处置效果"></textarea>
        <button class="apply-button primary-outline" type="submit" :disabled="saving">{{ saving ? '保存中...' : '添加案例' }}</button>
      </form>
      <p v-if="message" class="page-sub feedback">{{ message }}</p>
    </section>

    <section class="panel">
      <div class="panel-head"><h3>案例列表</h3><span class="count">{{ cases.length }} 条</span></div>
      <div class="table-wrap"><table>
        <thead><tr><th>标题</th><th>类型</th><th>等级</th><th>来源</th><th>标签</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="item in cases" :key="item.id">
            <td class="strong">{{ item.title }}</td>
            <td>{{ item.eventType || '-' }}</td>
            <td><span :class="['check-badge', riskClass(item.riskLevel)]">{{ item.riskLevel }}</span></td>
            <td>{{ item.source || '-' }}</td>
            <td><small class="table-note">{{ (item.tags || []).join('、') || '-' }}</small></td>
            <td class="row-actions"><button class="apply-button" type="button" @click="removeCase(item)">删除</button></td>
          </tr>
          <tr v-if="!cases.length"><td colspan="6" class="empty-cell">暂无历史案例</td></tr>
        </tbody>
      </table></div>
    </section>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue';
import { createOpinionCase, deleteOpinionCase, fetchOpinionCases } from '../../api';

const cases = ref([]);
const saving = ref(false);
const reindexing = ref(false);
const message = ref('');
const form = reactive({ title: '', eventType: '', riskLevel: '关注', tags: '', source: '', strategy: '', content: '', effect: '' });

const riskClass = (value) => ({ 危机: 'danger', 预警: 'warn', 关注: 'ok' }[value] || 'warn');
async function loadCases() { cases.value = await fetchOpinionCases(); }
async function loadAll() { try { await loadCases(); } catch (e) { message.value = `加载失败：${e.message}`; } }
async function createCase() {
  saving.value = true; message.value = '';
  try {
    await createOpinionCase({
      ...form,
      tags: String(form.tags).split(/[,，]/).map((s) => s.trim()).filter(Boolean),
    });
    Object.assign(form, { title: '', eventType: '', tags: '', source: '', strategy: '', content: '', effect: '' });
    message.value = '案例已添加，请重建 RAG 索引。';
    await loadCases();
  } catch (e) { message.value = `保存失败：${e.message}`; } finally { saving.value = false; }
}
async function removeCase(item) { if (!window.confirm(`确定删除案例「${item.title}」？`)) return; try { await deleteOpinionCase(item.id); await loadCases(); } catch (e) { message.value = `删除失败：${e.message}`; } }
async function reindex() {
  reindexing.value = true; message.value = '';
  try {
    const response = await fetch('/api/opinion/cases/reindex', { method: 'POST' });
    const data = await response.json();
    message.value = `索引重建完成：${data?.chunks ?? '已执行'} 个切片。`;
  } catch (e) {
    message.value = `重建失败：${e.message}`;
  } finally {
    reindexing.value = false;
  }
}
onMounted(loadAll);
</script>

<style scoped>
.opinion-cases-page { max-width: 1280px; }
.case-form { display: grid; grid-template-columns: 1.3fr 1fr 90px 1fr 1fr auto; gap: 8px; padding: 14px; }
.case-form input, .case-form select { min-height: 34px; font-size: 12px; }
.case-form textarea { grid-column: span 2; min-height: 44px; border: 1px solid #cbd5e1; border-radius: 6px; padding: 7px; font-size: 12px; }
.case-form button { grid-column: span 2; }
.primary-outline { min-height: 34px; white-space: nowrap; }
.feedback { color: #1d4ed8; }
@media (max-width: 1000px) { .case-form { grid-template-columns: repeat(2, minmax(0, 1fr)); } .case-form textarea, .case-form button { grid-column: span 2; } }
@media (max-width: 700px) { .page-head { flex-direction: column; align-items: flex-start; } .head-button { width: auto; } .case-form { grid-template-columns: 1fr; } }
</style>