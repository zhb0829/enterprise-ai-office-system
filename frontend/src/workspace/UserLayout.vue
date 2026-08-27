<template>
  <div class="user-shell">
    <header class="topbar">
      <a class="skip-link" href="#workspace-main">跳到主要内容</a>
      <div class="brand-lockup" aria-label="企业 AI 办公助手">
        <span class="brand-mark" aria-hidden="true">AI</span>
        <div>
          <p class="eyebrow">企业 AI 办公助手</p>
          <h1>智能办公工作台</h1>
        </div>
      </div>
      <nav class="module-nav" aria-label="用户端功能导航">
        <router-link class="module-nav-item" exact-active-class="active" to="/workspace">公告撰写</router-link>
        <router-link class="module-nav-item" active-class="active" to="/workspace/policy">政策问答</router-link>
        <router-link class="module-nav-item" active-class="active" to="/workspace/intelligence">行业情报</router-link>
        <router-link class="module-nav-item" active-class="active" to="/workspace/qualification">资质编制</router-link>
        <router-link
          class="module-nav-item"
          :class="{ active: isOpinionRoute }"
          to="/workspace/opinion"
        >舆情中心</router-link>
      </nav>
    </header>
    <main id="workspace-main" class="user-content" tabindex="-1">
      <router-view />
    </main>
  </div>
</template>

<script setup>
import { computed } from 'vue';
import { useRoute } from 'vue-router';

const route = useRoute();
const isOpinionRoute = computed(() => route.path.startsWith('/workspace/opinion'));
</script>
