<template>
  <main class="opinion-hub" aria-labelledby="opinion-hub-title">
    <header class="opinion-hub-head">
      <div class="opinion-hub-copy">
        <p class="eyebrow">企业实时舆情工作台</p>
        <h2 id="opinion-hub-title">让每条舆情<span class="inline-image" aria-hidden="true"></span>都有可追溯的处置闭环</h2>
      </div>
      <div class="opinion-hub-status" role="status" aria-live="polite">
        <span aria-hidden="true"></span>
        {{ activeTabLabel }}
      </div>
    </header>

    <nav class="opinion-tabs" aria-label="舆情功能">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        type="button"
        :class="{ active: activeTab === tab.key }"
        :aria-current="activeTab === tab.key ? 'page' : undefined"
        @click="switchTab(tab.key)"
      >
        <span class="tab-index">{{ tab.index }}</span>
        <span>{{ tab.label }}</span>
      </button>
    </nav>

    <section class="opinion-hub-content" aria-live="polite">
      <KeepAlive>
        <component :is="activeComponent" />
      </KeepAlive>
    </section>
  </main>
</template>

<script setup>
import { computed } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import Opinion from './Opinion.vue';
import OpinionAlerts from './OpinionAlerts.vue';
import OpinionReports from './OpinionReports.vue';

const route = useRoute();
const router = useRouter();

const tabs = [
  { key: 'analysis', label: '舆情分析', index: '01', path: '/workspace/opinion' },
  { key: 'alerts', label: '舆情告警', index: '02', path: '/workspace/opinion-alerts' },
  { key: 'reports', label: '舆情报告', index: '03', path: '/workspace/opinion-reports' },
];

const tabMap = Object.fromEntries(tabs.map((tab) => [tab.path, tab]));
const activeTab = computed(() => tabMap[route.path]?.key || 'analysis');
const activeTabLabel = computed(() => tabs.find((tab) => tab.key === activeTab.value)?.label || '舆情分析');
const activeComponent = computed(() => ({
  analysis: Opinion,
  alerts: OpinionAlerts,
  reports: OpinionReports,
}[activeTab.value] || Opinion));

function switchTab(key) {
  const tab = tabs.find((item) => item.key === key);
  if (tab && tab.path !== route.path) router.push(tab.path);
}
</script>

<style scoped>
.opinion-hub {
  box-sizing: border-box;
  width: 100%;
  max-width: 1480px;
  overflow-x: hidden;
  margin: 0 auto;
  padding: clamp(24px, 4vw, 52px) clamp(16px, 4vw, 48px) 72px;
  color: #17233a;
}

.opinion-hub-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  padding: 10px 0 24px;
  border-bottom: 1px solid #d7e4df;
}

.opinion-hub-copy h2 {
  margin: 0;
  color: #112927;
  font-size: clamp(2rem, 4.4vw, 4.2rem);
  line-height: 1.06;
  text-wrap: balance;
}

.opinion-hub-copy > p:last-child {
  max-width: 760px;
  margin: 14px 0 0;
  color: #52615f;
  line-height: 1.75;
}

.opinion-hub-status {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex: 0 0 auto;
  border: 1px solid #b9ddd3;
  border-radius: 999px;
  padding: 8px 11px;
  color: #0f5f59;
  background: #f0fbf7;
  font-size: 13px;
  font-weight: 700;
}

.opinion-hub-status span {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #0f9f6e;
}

.opinion-tabs {
  display: flex;
  align-items: center;
  gap: 8px;
  width: fit-content;
  max-width: 100%;
  margin: 18px 0 20px;
  padding: 4px;
  border: 1px solid rgba(37, 67, 63, 0.14);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.72);
  box-shadow: 0 8px 20px rgba(18, 43, 40, 0.05);
}

.opinion-tabs button {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 38px;
  border: 1px solid transparent;
  border-radius: 999px;
  padding: 7px 13px;
  color: #36524f;
  background: transparent;
  font-size: 13px;
  font-weight: 800;
  white-space: nowrap;
  transition: background 0.18s ease, color 0.18s ease, transform 0.18s ease;
}

.opinion-tabs button:hover {
  background: #edf8f5;
  color: #0f5f59;
  transform: translateY(-1px);
}

.opinion-tabs button.active {
  background: #112927;
  color: #ffffff;
  box-shadow: 0 5px 12px rgba(17, 41, 39, 0.16);
}

.tab-index {
  color: #7a9690;
  font-size: 10px;
  letter-spacing: 0.04em;
}

.opinion-tabs button.active .tab-index {
  color: #a7d8cc;
}

.opinion-hub-content {
  min-width: 0;
}

.opinion-hub-content :deep(.opinion-page) {
  max-width: none;
  margin: 0;
  padding: 0 0 12px;
}

.opinion-hub-content :deep(.opinion-head) {
  display: none;
}

.opinion-hub-content :deep(.monitor-bar) {
  margin-top: 0;
}

@media (max-width: 680px) {
  .opinion-hub-head {
    align-items: flex-start;
    flex-direction: column;
    gap: 16px;
  }

  .opinion-hub-status {
    align-self: flex-start;
  }

  .opinion-tabs {
    width: 100%;
    overflow-x: auto;
    scrollbar-width: thin;
  }

  .opinion-tabs button {
    flex: 1 0 auto;
    justify-content: center;
  }
}

@media (prefers-reduced-motion: reduce) {
  .opinion-tabs button {
    transition: none;
  }
}
</style>
