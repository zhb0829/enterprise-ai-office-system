<template>
  <div class="layout-shell">
    <aside class="sidebar">
      <div class="brand">
        <p class="eyebrow">后台管理</p>
        <strong>企业 AI 办公助手</strong>
      </div>
      <nav class="side-nav">
        <div v-for="group in groups" :key="group" class="menu-group">
          <p class="menu-group-title">{{ group }}</p>
          <router-link
            v-for="item in menuItems.filter((i) => i.group === group)"
            :key="item.path"
            :to="item.path"
            class="menu-item"
            active-class="active"
          >
            {{ item.title }}
          </router-link>
        </div>
      </nav>
    </aside>
    <div class="layout-main">
      <header class="layout-topbar">
        <h1>{{ currentTitle }}</h1>
        <div class="status-pill" :class="{ online: apiReady }">
          <span></span>{{ apiReady ? '后端已连接' : '演示模式' }}
        </div>
      </header>
      <main class="layout-content">
        <router-view />
      </main>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import { fetchStyles, fetchTemplates } from '../api';

const route = useRoute();
const apiReady = ref(false);

const menuItems = [
  { path: '/admin/templates', title: '模板管理', group: '内容管理' },
  { path: '/admin/materials', title: '素材管理', group: '内容管理' },
  { path: '/admin/policy-documents', title: '政策法规知识库', group: '知识库管理' },
];

const groups = ['内容管理', '知识库管理'];

const currentTitle = computed(() => route.meta.title || '后台管理');

async function checkApi() {
  try {
    const [templates, styles] = await Promise.all([fetchTemplates(), fetchStyles()]);
    apiReady.value = Array.isArray(templates) && templates.length > 0 && styles?.styles?.length > 0;
  } catch {
    apiReady.value = false;
  }
}

onMounted(() => {
  checkApi();
  window.addEventListener('eaos-unauthorized', () => {
    localStorage.removeItem('eaos-token');
  });
});
</script>
