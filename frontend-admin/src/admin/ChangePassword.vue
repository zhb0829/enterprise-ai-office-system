<template>
  <div class="login-shell">
    <form class="login-card" @submit.prevent="submit">
      <h1>修改初始密码</h1>
      <p class="login-sub">首次登录或密码已重置，请设置新密码。至少 6 位，需同时包含大写字母、小写字母和数字。</p>
      <p v-if="error" class="error-text">{{ error }}</p>
      <div class="field">
        <label for="old-password">原密码</label>
        <input id="old-password" v-model="oldPassword" type="password" autocomplete="current-password" required />
      </div>
      <div class="field">
        <label for="new-password">新密码</label>
        <input id="new-password" v-model="newPassword" type="password" autocomplete="new-password" required />
      </div>
      <div class="field">
        <label for="confirm-password">确认新密码</label>
        <input id="confirm-password" v-model="confirmPassword" type="password" autocomplete="new-password" required />
      </div>
      <button class="apply-button" type="submit" :disabled="loading">
        {{ loading ? '提交中…' : '确认修改' }}
      </button>
      <button class="ghost-button" type="button" @click="goLogin">返回登录</button>
    </form>
  </div>
</template>

<script setup>
import { ref } from 'vue';
import { useRouter } from 'vue-router';
import { changePassword, logout } from '../api';

const router = useRouter();
const oldPassword = ref('');
const newPassword = ref('');
const confirmPassword = ref('');
const error = ref('');
const loading = ref(false);

function validate(value) {
  return value.length >= 6 && /[a-z]/.test(value) && /[A-Z]/.test(value) && /\d/.test(value);
}

async function submit() {
  error.value = '';
  if (newPassword.value !== confirmPassword.value) {
    error.value = '两次输入的新密码不一致';
    return;
  }
  if (!validate(newPassword.value)) {
    error.value = '密码至少 6 位，且需同时包含大写字母、小写字母和数字';
    return;
  }
  loading.value = true;
  try {
    await changePassword(oldPassword.value, newPassword.value);
    await logout();
    router.replace('/admin/login');
  } catch (ex) {
    error.value = ex.message || '修改失败，请稍后重试';
  } finally {
    loading.value = false;
  }
}

function goLogin() {
  logout();
  router.replace('/admin/login');
}
</script>
