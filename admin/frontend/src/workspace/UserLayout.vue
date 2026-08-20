<template>
  <div class="app-shell">
    <aside class="app-sidebar" :class="{ open: mobileMenuOpen }">
      <div class="brand-lockup">
        <div class="brand-symbol"><span></span><span></span><span></span></div>
        <div>
          <strong>智办工作台</strong>
          <span>Enterprise AI Office</span>
        </div>
      </div>

      <nav class="main-nav" aria-label="主导航">
        <p class="nav-label">工作空间</p>
        <router-link to="/workspace" class="nav-item" exact-active-class="active" @click="mobileMenuOpen = false">
          <AppIcon name="home" :size="18" /><span>工作台首页</span>
        </router-link>
        <p class="nav-label nav-label-spaced">智能能力</p>
        <router-link
          v-for="item in navItems"
          :key="item.slug"
          :to="`/workspace/feature/${item.slug}`"
          class="nav-item"
          active-class="active"
          @click="mobileMenuOpen = false"
        >
          <AppIcon :name="item.icon" :size="18" /><span>{{ item.title }}</span>
          <span v-if="item.badge" class="nav-badge">{{ item.badge }}</span>
        </router-link>
      </nav>

      <div class="sidebar-bottom">
        <div class="help-box">
          <div class="help-icon"><AppIcon name="sparkles" :size="17" /></div>
          <div><strong>需要帮助？</strong><span>查看使用指南</span></div>
          <AppIcon name="arrow-right" :size="15" />
        </div>
        <div class="profile-row">
          <div class="avatar">张</div>
          <div><strong>张明</strong><span>办公室主任</span></div>
          <AppIcon name="more" :size="18" class="more-icon" />
        </div>
      </div>
    </aside>

    <div v-if="mobileMenuOpen" class="sidebar-scrim" @click="mobileMenuOpen = false"></div>
    <div class="app-main">
      <header class="topbar">
        <button class="mobile-menu-button" type="button" aria-label="打开导航" @click="mobileMenuOpen = true"><AppIcon name="more" :size="22" /></button>
        <div class="topbar-context">
          <span class="context-line"></span>
          <span>{{ route.meta.title || '工作台首页' }}</span>
        </div>
        <div class="topbar-actions">
          <button class="search-trigger" type="button" aria-label="搜索"><AppIcon name="search" :size="17" /><span>搜索工作内容</span><kbd>⌘ K</kbd></button>
          <button class="topbar-icon" type="button" aria-label="通知"><AppIcon name="bell" :size="19" /><span class="notification-dot"></span></button>
          <div class="topbar-divider"></div>
          <div class="topbar-user"><div class="avatar small">张</div><span>张明</span><AppIcon name="more" :size="16" /></div>
        </div>
      </header>
      <main class="user-content"><router-view /></main>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue';
import { useRoute } from 'vue-router';
import AppIcon from '../components/AppIcon.vue';

const route = useRoute();
const mobileMenuOpen = ref(false);
const navItems = [
  { slug: 'policy-qa', title: '政策法规问答', icon: 'book' },
  { slug: 'news-drafting', title: '公告新闻撰写', icon: 'pen' },
  { slug: 'industry-news', title: '行业动态聚合', icon: 'pulse', badge: '3' },
  { slug: 'public-opinion', title: '企业舆情分析', icon: 'chart' },
  { slug: 'qualification-guide', title: '资质服务指南', icon: 'file' },
  { slug: 'meeting-brief', title: '会议公开整理', icon: 'calendar' },
];
</script>
