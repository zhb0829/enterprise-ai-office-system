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
        <router-link class="module-nav-item" exact-active-class="active" to="/workspace">首页</router-link>
        <router-link class="module-nav-item" active-class="active" to="/workspace/compose">公告撰写</router-link>
        <router-link class="module-nav-item" active-class="active" to="/workspace/policy">政策问答</router-link>
        <router-link class="module-nav-item" active-class="active" to="/workspace/intelligence">行业情报</router-link>
        <router-link class="module-nav-item" active-class="active" to="/workspace/qualification">资质编制</router-link>
        <router-link
          class="module-nav-item"
          :class="{ active: isOpinionRoute }"
          to="/workspace/opinion"
        >舆情中心</router-link>
        <router-link class="module-nav-item" active-class="active" to="/workspace/meeting">会议信息</router-link>
      </nav>
      <div class="notification-wrap">
        <button
          class="notification-button"
          type="button"
          aria-label="站内通知"
          :aria-expanded="notificationOpen"
          @click="toggleNotifications"
        >
          通知
          <span v-if="unreadCount" class="notification-count">{{ unreadCount > 99 ? '99+' : unreadCount }}</span>
        </button>
        <section v-if="notificationOpen" class="notification-popover" aria-label="站内通知列表">
          <header>
            <strong>站内通知</strong>
            <button v-if="unreadCount" type="button" @click="readAll">全部已读</button>
          </header>
          <button
            v-for="item in notifications"
            :key="item.id"
            type="button"
            :class="['notification-item', { unread: !item.isRead }]"
            @click="openNotification(item)"
          >
            <strong>{{ item.title }}</strong>
            <span>{{ item.content }}</span>
            <time>{{ formatTime(item.createdAt) }}</time>
          </button>
          <p v-if="!notifications.length" class="notification-empty">暂无通知</p>
        </section>
      </div>
    </header>
    <main id="workspace-main" class="user-content" tabindex="-1">
      <router-view />
    </main>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import {
  fetchMeetingNotifications,
  fetchMeetingUnreadCount,
  markAllMeetingNotificationsRead,
  markMeetingNotificationRead,
} from '../api';

const route = useRoute();
const router = useRouter();
const isOpinionRoute = computed(() => route.path.startsWith('/workspace/opinion'));
const notificationOpen = ref(false);
const unreadCount = ref(0);
const notifications = ref([]);
let timer = null;

function formatTime(value) {
  return value ? new Date(value).toLocaleString('zh-CN', { dateStyle: 'short', timeStyle: 'short' }) : '';
}

async function refreshUnread() {
  try {
    unreadCount.value = Number((await fetchMeetingUnreadCount())?.count || 0);
  } catch {
    unreadCount.value = 0;
  }
}

async function toggleNotifications() {
  notificationOpen.value = !notificationOpen.value;
  if (!notificationOpen.value) return;
  try {
    notifications.value = (await fetchMeetingNotifications(1, 12))?.items || [];
  } catch {
    notifications.value = [];
  }
}

async function openNotification(item) {
  if (!item.isRead) {
    await markMeetingNotificationRead(item.id).catch(() => {});
  }
  notificationOpen.value = false;
  await refreshUnread();
  if (item.refId) router.push({ path: '/workspace/meeting', query: { id: item.refId } });
}

async function readAll() {
  await markAllMeetingNotificationsRead().catch(() => {});
  notifications.value = notifications.value.map((item) => ({ ...item, isRead: true }));
  unreadCount.value = 0;
}

onMounted(() => {
  refreshUnread();
  timer = window.setInterval(refreshUnread, 30000);
});

onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer);
});
</script>

<style scoped>
.notification-wrap {
  position: relative;
  flex: 0 0 auto;
}

.notification-button {
  min-height: 40px;
  padding: 8px 12px;
  border: 1px solid rgba(15, 118, 110, 0.25);
  border-radius: 8px;
  background: #fff;
  color: #0b4f4a;
  font-weight: 700;
}

.notification-count {
  display: inline-grid;
  min-width: 20px;
  height: 20px;
  place-items: center;
  margin-left: 5px;
  padding: 0 5px;
  border-radius: 10px;
  background: #c2410c;
  color: #fff;
  font-size: 11px;
}

.notification-popover {
  position: absolute;
  z-index: 30;
  top: calc(100% + 8px);
  right: 0;
  width: min(380px, calc(100vw - 24px));
  max-height: 460px;
  overflow: auto;
  border: 1px solid #d9e5e1;
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 18px 48px rgba(18, 43, 40, 0.18);
}

.notification-popover header {
  position: sticky;
  top: 0;
  display: flex;
  justify-content: space-between;
  padding: 12px 14px;
  border-bottom: 1px solid #e4ece9;
  background: #fff;
}

.notification-popover header button {
  border: 0;
  background: transparent;
  color: #0f766e;
  font-weight: 700;
}

.notification-item {
  width: 100%;
  display: grid;
  gap: 4px;
  padding: 12px 14px;
  border: 0;
  border-bottom: 1px solid #edf2f0;
  background: #fff;
  color: #263a37;
  text-align: left;
}

.notification-item.unread {
  box-shadow: inset 3px 0 #c2410c;
  background: #fffaf7;
}

.notification-item span,
.notification-item time {
  color: #60706d;
  font-size: 12px;
  line-height: 1.5;
}

.notification-empty {
  margin: 0;
  padding: 28px 14px;
  color: #71807d;
  text-align: center;
}
</style>
