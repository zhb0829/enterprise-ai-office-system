<template>
  <div class="login-shell">
    <form class="login-card" @submit.prevent="submit">
      <h1>企业AI智能办公系统</h1>
      <p class="login-sub">请使用企业分配的账号登录工作台</p>
      <p v-if="error" class="error-text">{{ error }}</p>
      <div class="field">
        <label for="login-username">用户名</label>
        <input id="login-username" v-model="username" autocomplete="username" required />
      </div>
      <div class="field">
        <label for="login-password">密码</label>
        <input id="login-password" v-model="password" type="password" autocomplete="current-password" required />
      </div>
      <button class="apply-button" type="submit" :disabled="loading">
        {{ loading ? '登录中…' : '登录' }}
      </button>
    </form>
  </div>
</template>

<script setup>
import { ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { login } from '../api';

const router = useRouter();
const route = useRoute();
const username = ref('');
const password = ref('');
const error = ref('');
const loading = ref(false);

async function submit() {
  if (loading.value) return;
  error.value = '';
  loading.value = true;
  try {
    const payload = await login(username.value.trim(), password.value);
    if (payload?.mustChangePassword) {
      router.replace('/change-password');
      return;
    }
    router.replace(typeof route.query.redirect === 'string' ? route.query.redirect : '/workspace');
  } catch (ex) {
    error.value = ex.message || '登录失败，请稍后重试';
  } finally {
    loading.value = false;
  }
}
</script>
