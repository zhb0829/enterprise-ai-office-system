<template>
  <div class="page-shell users-page">
    <div class="page-head">
      <div>
        <h2>用户管理</h2>
        <p class="page-sub">账号生命周期管理：创建用户、分配角色、启用/禁用、重置密码。重置后用户首登需修改密码。</p>
      </div>
      <div class="head-actions">
        <input v-model="keyword" class="search-input" placeholder="搜索用户名/昵称" aria-label="搜索用户" @keyup.enter="load(1)" />
        <button class="apply-button head-button" type="button" @click="openCreate">新建用户</button>
      </div>
    </div>

    <p v-if="message" class="page-sub feedback">{{ message }}</p>

    <section class="panel">
      <div class="panel-head"><h3>用户列表</h3><span class="count">{{ total }} 个</span></div>
      <div class="table-wrap"><table>
        <thead><tr><th>ID</th><th>用户名</th><th>昵称</th><th>角色</th><th>状态</th><th>创建时间</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="user in users" :key="user.id">
            <td>{{ user.id }}</td>
            <td class="strong">{{ user.username }}</td>
            <td>{{ user.nickname || '-' }}</td>
            <td>
              <select :value="user.role" aria-label="角色" :disabled="user.username === 'admin'" @change="updateUser(user, { role: $event.target.value })">
                <option value="ADMIN">ADMIN</option>
                <option value="USER">USER</option>
              </select>
            </td>
            <td>
              <span :class="['check-badge', user.enabled ? 'ok' : 'danger']">{{ user.enabled ? '启用' : '禁用' }}</span>
            </td>
            <td><small class="table-note">{{ formatDate(user.createdAt) }}</small></td>
            <td class="row-actions">
              <button class="apply-button" type="button" :disabled="user.username === 'admin'" @click="toggleEnabled(user)">
                {{ user.enabled ? '禁用' : '启用' }}
              </button>
              <button class="apply-button" type="button" @click="openReset(user)">重置密码</button>
              <button class="apply-button danger" type="button" :disabled="user.username === 'admin'" @click="removeUser(user)">删除</button>
            </td>
          </tr>
          <tr v-if="!users.length"><td colspan="7" class="empty-cell">暂无用户</td></tr>
        </tbody>
      </table></div>
      <div class="pager">
        <button class="ghost-button" type="button" :disabled="page <= 1" @click="load(page - 1)">上一页</button>
        <span>第 {{ page }} / {{ totalPages }} 页</span>
        <button class="ghost-button" type="button" :disabled="page >= totalPages" @click="load(page + 1)">下一页</button>
      </div>
    </section>

    <!-- 新建用户 -->
    <div v-if="creating" class="modal-mask" @click.self="creating = false">
      <form class="modal-card" @submit.prevent="createUser">
        <h3>新建用户</h3>
        <div class="field"><label>用户名</label><input v-model="createForm.username" required /></div>
        <div class="field"><label>昵称</label><input v-model="createForm.nickname" /></div>
        <div class="field"><label>初始密码（≥6 位，含大小写与数字）</label><input v-model="createForm.password" type="text" required /></div>
        <div class="field"><label>角色</label>
          <select v-model="createForm.role"><option value="USER">USER（普通用户）</option><option value="ADMIN">ADMIN（管理员）</option></select>
        </div>
        <div class="modal-actions">
          <button class="ghost-button" type="button" @click="creating = false">取消</button>
          <button class="apply-button" type="submit" :disabled="saving">{{ saving ? '创建中…' : '创建' }}</button>
        </div>
      </form>
    </div>

    <!-- 重置密码 -->
    <div v-if="resetTarget" class="modal-mask" @click.self="resetTarget = null">
      <form class="modal-card" @submit.prevent="resetPassword">
        <h3>重置密码：{{ resetTarget.username }}</h3>
        <div class="field"><label>新密码（≥6 位，含大小写与数字）</label><input v-model="newPassword" type="text" required /></div>
        <p class="page-sub">重置成功后该用户下次登录将被要求修改密码。</p>
        <div class="modal-actions">
          <button class="ghost-button" type="button" @click="resetTarget = null">取消</button>
          <button class="apply-button" type="submit" :disabled="saving">{{ saving ? '提交中…' : '重置' }}</button>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { createUserRequest, deleteUser, fetchUsers, resetUserPassword, updateUser as updateUserApi } from '../../api';

const users = ref([]);
const total = ref(0);
const page = ref(1);
const pageSize = 20;
const keyword = ref('');
const message = ref('');
const saving = ref(false);
const creating = ref(false);
const resetTarget = ref(null);
const newPassword = ref('');
const createForm = reactive({ username: '', nickname: '', password: '', role: 'USER' });

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)));

function formatDate(value) {
  return value ? String(value).replace('T', ' ').slice(0, 19) : '-';
}

async function load(target = page.value) {
  message.value = '';
  try {
    const data = await fetchUsers(target, pageSize, keyword.value.trim());
    users.value = data.items || [];
    total.value = Number(data.total || 0);
    page.value = target;
  } catch (e) {
    message.value = `加载失败：${e.message}`;
  }
}

function openCreate() {
  Object.assign(createForm, { username: '', nickname: '', password: '', role: 'USER' });
  creating.value = true;
}

async function createUser() {
  if (!/^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{6,}$/.test(createForm.password)) {
    message.value = '初始密码需至少 6 位，且包含大小写字母与数字';
    return;
  }
  saving.value = true; message.value = '';
  try {
    await createUserRequest({ ...createForm });
    creating.value = false;
    message.value = `用户 ${createForm.username} 已创建`;
    await load(1);
  } catch (e) {
    message.value = `创建失败：${e.message}`;
  } finally { saving.value = false; }
}

async function updateUser(user, patch) {
  message.value = '';
  try {
    await updateUserApi(user.id, patch);
    await load(page.value);
  } catch (e) {
    message.value = `保存失败：${e.message}`;
  }
}

function toggleEnabled(user) {
  updateUser(user, { enabled: !user.enabled });
}

function openReset(user) {
  newPassword.value = '';
  resetTarget.value = user;
}

async function resetPassword() {
  if (!/^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{6,}$/.test(newPassword.value)) {
    message.value = '新密码需至少 6 位，且包含大小写字母与数字';
    return;
  }
  saving.value = true; message.value = '';
  try {
    await resetUserPassword(resetTarget.value.id, newPassword.value);
    resetTarget.value = null;
    message.value = '密码已重置，用户下次登录需修改密码';
  } catch (e) {
    message.value = `重置失败：${e.message}`;
  } finally { saving.value = false; }
}

async function removeUser(user) {
  if (!window.confirm(`确定删除用户「${user.username}」？`)) return;
  message.value = '';
  try {
    await deleteUser(user.id);
    await load(page.value);
  } catch (e) {
    message.value = `删除失败：${e.message}`;
  }
}

onMounted(() => load(1));
</script>

<style scoped>
.users-page { max-width: 1280px; }
.search-input { min-height: 34px; min-width: 220px; border: 1px solid #cbd5e1; border-radius: 6px; padding: 7px 10px; font-size: 13px; }
.feedback { color: #1d4ed8; }
.pager { display: flex; gap: 12px; align-items: center; justify-content: flex-end; padding: 10px 14px; color: #57606a; font-size: 13px; }
.row-actions { display: flex; gap: 6px; white-space: nowrap; }
.row-actions .apply-button { min-height: 30px; padding: 4px 10px; font-size: 12px; }
.modal-mask { position: fixed; inset: 0; z-index: 50; display: grid; place-items: center; background: rgba(15, 23, 42, 0.35); }
.modal-card { width: min(420px, calc(100vw - 32px)); display: grid; gap: 12px; padding: 24px; border-radius: 12px; background: #fff; box-shadow: 0 18px 48px rgba(15, 23, 42, 0.25); }
.modal-card h3 { margin: 0; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; }
</style>
