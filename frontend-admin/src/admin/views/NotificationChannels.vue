<template>
  <div class="page-shell channels-page">
    <div class="page-head">
      <div>
        <h2>通知渠道管理</h2>
        <p class="page-sub">配置告警与任务通知的投递渠道（Webhook / 邮件）。禁用的渠道不会被投递。</p>
      </div>
      <div class="head-actions">
        <button class="apply-button head-button" type="button" @click="openCreate">新建渠道</button>
      </div>
    </div>

    <p v-if="message" class="page-sub feedback">{{ message }}</p>

    <section class="panel">
      <div class="panel-head"><h3>渠道列表</h3><span class="count">{{ channels.length }} 个</span></div>
      <div class="table-wrap"><table>
        <thead><tr><th>名称</th><th>类型</th><th>配置</th><th>状态</th><th>更新时间</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="channel in channels" :key="channel.id">
            <td class="strong">{{ channel.name }}</td>
            <td>{{ channel.type }}</td>
            <td><code class="config-code">{{ channel.config || '-' }}</code></td>
            <td><span :class="['check-badge', channel.enabled ? 'ok' : 'danger']">{{ channel.enabled ? '启用' : '禁用' }}</span></td>
            <td><small class="table-note">{{ formatDate(channel.updatedAt || channel.createdAt) }}</small></td>
            <td class="row-actions">
              <button class="apply-button" type="button" @click="toggleEnabled(channel)">{{ channel.enabled ? '禁用' : '启用' }}</button>
              <button class="apply-button" type="button" @click="openEdit(channel)">编辑</button>
              <button class="apply-button danger" type="button" @click="removeChannel(channel)">删除</button>
            </td>
          </tr>
          <tr v-if="!channels.length"><td colspan="6" class="empty-cell">暂无通知渠道</td></tr>
        </tbody>
      </table></div>
    </section>

    <div v-if="editing" class="modal-mask" @click.self="editing = false">
      <form class="modal-card" @submit.prevent="save">
        <h3>{{ form.id ? '编辑渠道' : '新建渠道' }}</h3>
        <div class="field"><label>渠道名称</label><input v-model="form.name" required /></div>
        <div class="field"><label>类型</label>
          <select v-model="form.type"><option value="webhook">Webhook</option><option value="email">邮件</option></select>
        </div>
        <div class="field">
          <label>配置（JSON，如 {"url": "https://example.com/hook"} 或 {"to": "ops@example.com"}）</label>
          <textarea v-model="form.config" rows="3" required></textarea>
        </div>
        <div class="modal-actions">
          <button class="ghost-button" type="button" @click="editing = false">取消</button>
          <button class="apply-button" type="submit" :disabled="saving">{{ saving ? '保存中…' : '保存' }}</button>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue';
import { createNotificationChannel, deleteNotificationChannel, fetchNotificationChannels, updateNotificationChannel } from '../../api';

const channels = ref([]);
const message = ref('');
const saving = ref(false);
const editing = ref(false);
const form = reactive({ id: null, name: '', type: 'webhook', config: '', enabled: true });

function formatDate(value) {
  return value ? String(value).replace('T', ' ').slice(0, 19) : '-';
}

async function load() {
  message.value = '';
  try {
    channels.value = await fetchNotificationChannels();
  } catch (e) {
    message.value = `加载失败：${e.message}`;
  }
}

function openCreate() {
  Object.assign(form, { id: null, name: '', type: 'webhook', config: '{"url": ""}', enabled: true });
  editing.value = true;
}

function openEdit(channel) {
  Object.assign(form, { id: channel.id, name: channel.name, type: channel.type, config: channel.config || '{}', enabled: !!channel.enabled });
  editing.value = true;
}

async function save() {
  saving.value = true; message.value = '';
  try {
    JSON.parse(form.config);
  } catch {
    message.value = '配置必须是合法 JSON';
    saving.value = false;
    return;
  }
  try {
    if (form.id) {
      await updateNotificationChannel(form.id, { ...form });
    } else {
      await createNotificationChannel({ ...form });
    }
    editing.value = false;
    await load();
  } catch (e) {
    message.value = `保存失败：${e.message}`;
  } finally { saving.value = false; }
}

async function toggleEnabled(channel) {
  message.value = '';
  try {
    await updateNotificationChannel(channel.id, { enabled: !channel.enabled });
    await load();
  } catch (e) {
    message.value = `操作失败：${e.message}`;
  }
}

async function removeChannel(channel) {
  if (!window.confirm(`确定删除渠道「${channel.name}」？`)) return;
  try {
    await deleteNotificationChannel(channel.id);
    await load();
  } catch (e) {
    message.value = `删除失败：${e.message}`;
  }
}

onMounted(load);
</script>

<style scoped>
.channels-page { max-width: 1180px; }
.feedback { color: #1d4ed8; }
.config-code { font-size: 12px; color: #334155; word-break: break-all; }
.row-actions { display: flex; gap: 6px; white-space: nowrap; }
.row-actions .apply-button { min-height: 30px; padding: 4px 10px; font-size: 12px; }
.modal-mask { position: fixed; inset: 0; z-index: 50; display: grid; place-items: center; background: rgba(15, 23, 42, 0.35); }
.modal-card { width: min(460px, calc(100vw - 32px)); display: grid; gap: 12px; padding: 24px; border-radius: 12px; background: #fff; box-shadow: 0 18px 48px rgba(15, 23, 42, 0.25); }
.modal-card h3 { margin: 0; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; }
</style>
