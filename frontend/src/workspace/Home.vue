<template>
  <main ref="homeRoot" class="home-page">
    <section class="home-hero" aria-labelledby="home-title">
      <div class="home-hero-inner">
        <p class="home-greeting">{{ greeting }}</p>
        <h2 id="home-title" class="home-title">今天从一份高质量文稿开始</h2>
        <p class="home-subtitle">公告撰写、政策问答、行业情报、资质编制、舆情中心、会议信息，一个工作台完成</p>
      </div>
    </section>

    <section class="home-modules" aria-labelledby="home-modules-title">
      <div class="home-section-head">
        <h2 id="home-modules-title">功能模块</h2>
        <p>选择一个模块，继续你的工作</p>
      </div>
      <div class="home-module-grid">
        <router-link
          v-for="module in modules"
          :key="module.name"
          :class="['home-module-card', { active: module.active }]"
          :to="module.to"
        >
          <component :is="module.icon" class="home-module-icon" :size="28" weight="light" aria-hidden="true" />
          <h3>{{ module.name }}</h3>
          <p>{{ module.description }}</p>
        </router-link>
      </div>
    </section>

    <section id="home-activity" class="home-activity" aria-labelledby="home-activity-title">
      <div class="home-section-head">
        <h2 id="home-activity-title">最近动态</h2>
        <p>来自素材、导出、情报与会议的最新记录</p>
      </div>
      <ol v-if="activities.length" class="home-activity-list">
        <li v-for="item in activities" :key="item.key">
          <button type="button" class="home-activity-item" @click="openActivity(item)">
            <span :class="['home-activity-tag', `tag-${item.type}`]">{{ typeLabel[item.type] }}</span>
            <strong class="home-activity-title">{{ item.title }}</strong>
            <time class="home-activity-time">{{ relativeTime(item.time) }}</time>
          </button>
        </li>
      </ol>
      <div v-else class="home-activity-empty">
        <p>暂无动态，从撰写第一份公告开始</p>
        <router-link class="primary-button" to="/workspace/compose">开始撰写</router-link>
      </div>
    </section>
  </main>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import {
  PhBinoculars,
  PhChatCircleText,
  PhPenNib,
  PhPulse,
  PhSealCheck,
  PhUsersThree,
} from '@phosphor-icons/vue';
import {
  fetchExportHistory,
  fetchIntelligenceReports,
  fetchMaterials,
  fetchMeetingNotifications,
} from '../api';

gsap.registerPlugin(ScrollTrigger);

const router = useRouter();
const homeRoot = ref(null);
const activities = ref([]);

const typeLabel = { material: '素材', export: '导出', intelligence: '情报', meeting: '会议' };

const modules = [
  {
    name: '公告撰写',
    description: '按模板、文风、素材生成可编辑的正式稿件。',
    to: '/workspace/compose',
    icon: PhPenNib,
    active: false,
  },
  {
    name: '政策问答',
    description: '围绕政策条文与业务场景提供可追溯问答。',
    to: '/workspace/policy',
    icon: PhChatCircleText,
    active: false,
  },
  {
    name: '行业情报',
    description: '聚合资讯与竞品动态，形成研判素材。',
    to: '/workspace/intelligence',
    icon: PhBinoculars,
    active: false,
  },
  {
    name: '资质编制',
    description: '沉淀资质说明与办事流程，快速成稿。',
    to: '/workspace/qualification',
    icon: PhSealCheck,
    active: false,
  },
  {
    name: '舆情中心',
    description: '实时监控企业舆情，预警风险并沉淀报告。',
    to: '/workspace/opinion',
    icon: PhPulse,
    active: false,
  },
  {
    name: '会议信息',
    description: '整理会议公开资料，生成纪要要点。',
    to: '/workspace/meeting',
    icon: PhUsersThree,
    active: false,
  },
];

const greeting = computed(() => {
  const hour = new Date().getHours();
  if (hour < 12) return '早上好';
  if (hour < 18) return '下午好';
  return '晚上好';
});

function parseTime(value) {
  if (!value) return 0;
  let text = String(value);
  if (!/(Z|[+-]\d{2}:?\d{2})$/.test(text)) text += 'Z';
  const time = new Date(text).getTime();
  return Number.isNaN(time) ? 0 : time;
}

function relativeTime(value) {
  const diff = Date.now() - parseTime(value);
  if (!Number.isFinite(diff) || diff < 0) return '';
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return '刚刚';
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days} 天前`;
  return new Date(parseTime(value)).toLocaleDateString('zh-CN');
}

function openActivity(item) {
  router.push(item.to);
}

async function loadActivities() {
  const results = await Promise.allSettled([
    fetchMaterials(),
    fetchExportHistory(),
    fetchIntelligenceReports(),
    fetchMeetingNotifications(1, 12),
  ]);

  const [materials, exports, reports, meetingPayload] = results.map(
    (result) => (result.status === 'fulfilled' ? result.value : null)
  );

  const items = [];
  if (Array.isArray(materials)) {
    materials.forEach((item, index) => {
      if (item?.created_at) {
        items.push({
          key: `material-${item.id ?? index}`,
          type: 'material',
          title: item.filename || '未命名素材',
          time: item.created_at,
          to: '/workspace/compose',
        });
      }
    });
  }
  if (Array.isArray(exports)) {
    exports.forEach((item, index) => {
      if (item?.created_at) {
        items.push({
          key: `export-${item.id ?? index}`,
          type: 'export',
          title: `${(item.format || 'md').toUpperCase()} 格式导出`,
          time: item.created_at,
          to: '/workspace/compose',
        });
      }
    });
  }
  if (Array.isArray(reports)) {
    reports.forEach((item, index) => {
      const time = item?.generatedAt || item?.generated_at;
      if (time) {
        items.push({
          key: `intelligence-${item.id ?? index}`,
          type: 'intelligence',
          title: item.title || '行业情报简报',
          time,
          to: '/workspace/intelligence',
        });
      }
    });
  }
  if (Array.isArray(meetingPayload?.items)) {
    meetingPayload.items.forEach((item) => {
      if (item?.createdAt) {
        items.push({
          key: `meeting-${item.id}`,
          type: 'meeting',
          title: item.title || '会议通知',
          time: item.createdAt,
          to: item.refId
            ? { path: '/workspace/meeting', query: { id: item.refId } }
            : '/workspace/meeting',
        });
      }
    });
  }

  activities.value = items
    .sort((a, b) => parseTime(b.time) - parseTime(a.time))
    .slice(0, 8);
}

function initHomeMotion() {
  const root = homeRoot.value;
  if (!root || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  const ctx = gsap.context(() => {
    gsap.from('.home-greeting, .home-title, .home-subtitle', {
      y: 28,
      opacity: 0,
      duration: 0.9,
      ease: 'power3.out',
      stagger: 0.08,
    });

    gsap.from('.home-module-card', {
      scrollTrigger: {
        trigger: '.home-modules',
        start: 'top 80%',
      },
      y: 34,
      opacity: 0,
      duration: 0.7,
      ease: 'power3.out',
      stagger: 0.06,
    });

    gsap.from('.home-activity-list li', {
      scrollTrigger: {
        trigger: '.home-activity',
        start: 'top 78%',
      },
      y: 24,
      opacity: 0,
      duration: 0.6,
      ease: 'power3.out',
      stagger: 0.05,
    });
  }, root);

  return () => ctx.revert();
}

let teardownMotion;

onMounted(() => {
  document.title = '工作台 · 企业 AI 办公助手';
  loadActivities();
  teardownMotion = initHomeMotion();
});

onBeforeUnmount(() => {
  document.title = '企业 AI 办公助手';
  if (typeof teardownMotion === 'function') teardownMotion();
});
</script>
