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
        <div class="topbar-right">
          <div class="status-pill" :class="{ online: apiReady }">
            <span></span>{{ apiReady ? '后端已连接' : '演示模式' }}
          </div>
          <button class="ghost-button" type="button" @click="handleLogout">退出登录</button>
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
import { useRoute, useRouter } from 'vue-router';
import { fetchStyles, fetchTemplates, getToken, logout } from '../api';

const route = useRoute();
const router = useRouter();
const apiReady = ref(false);

const menuItems = [
  { path: '/admin/templates', title: '模板管理', group: '内容管理' },
  { path: '/admin/materials', title: '素材管理', group: '内容管理' },
  { path: '/admin/policy-documents', title: '政策法规知识库', group: '知识库管理' },
  { path: '/admin/qualification-guides', title: '资质指南库', group: '知识库管理' },
  { path: '/admin/qualification-tasks', title: '资质编制任务', group: '知识库管理' },
  { path: '/admin/qualification-rules', title: '资质编制校验规则', group: '知识库管理' },
  { path: '/admin/intelligence', title: '行业与竞品情报', group: '情报聚合' },
  { path: '/admin/opinion-sources', title: '舆情采集源治理', group: '舆情分析' },
  { path: '/admin/opinion-alert-rules', title: '告警规则', group: '舆情分析' },
  { path: '/admin/opinion-cases', title: '历史应对案例', group: '舆情分析' },
  { path: '/admin/meetings', title: '会议资料整理', group: '会议知识' },
  { path: '/admin/users', title: '用户管理', group: '系统管理' },
  { path: '/admin/notification-channels', title: '通知渠道', group: '系统管理' },
];

const groups = ['内容管理', '知识库管理', '情报聚合', '舆情分析', '会议知识', '系统管理'];

const currentTitle = computed(() => route.meta.title || '后台管理');

async function checkApi() {
  try {
    const [templates, styles] = await Promise.all([fetchTemplates(), fetchStyles()]);
    apiReady.value = Array.isArray(templates) && templates.length > 0 && styles?.styles?.length > 0;
  } catch {
    apiReady.value = false;
  }
}

async function handleLogout() {
  await logout();
  router.replace('/admin/login');
}

onMounted(() => {
  if (!getToken()) {
    router.replace('/admin/login');
    return;
  }
  checkApi();
});
</script>
