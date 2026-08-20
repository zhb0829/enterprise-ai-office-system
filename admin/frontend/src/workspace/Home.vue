<template>
  <div class="home-page">
    <section class="welcome-band">
      <div>
        <p class="eyebrow teal">星期四，8 月 20 日</p>
        <h1>早上好，张明</h1>
        <p class="welcome-copy">今天也让信息工作更快一步。选择一个工作场景，开始你的智能协作。</p>
      </div>
      <div class="ai-status">
        <span class="status-dot"></span>
        <div>
          <strong>AI 助手在线</strong>
          <span>知识库已更新至 2026.08</span>
        </div>
        <AppIcon name="sparkles" :size="18" />
      </div>
    </section>

    <section class="overview-grid">
      <div class="overview-card">
        <div class="overview-icon blue"><AppIcon name="file" :size="19" /></div>
        <div><span>本月已处理</span><strong>28 <small>份材料</small></strong></div>
        <span class="trend positive">+18.6%</span>
      </div>
      <div class="overview-card">
        <div class="overview-icon green"><AppIcon name="clock" :size="19" /></div>
        <div><span>累计节省时间</span><strong>16.5 <small>小时</small></strong></div>
        <span class="trend positive">+4.2h</span>
      </div>
      <div class="overview-card">
        <div class="overview-icon amber"><AppIcon name="pulse" :size="19" /></div>
        <div><span>待关注舆情</span><strong>06 <small>条</small></strong></div>
        <span class="trend warning">需关注</span>
      </div>
    </section>

    <section class="section-block">
      <div class="section-heading">
        <div>
          <p class="eyebrow">WORKSPACE</p>
          <h2>智能工作台</h2>
        </div>
        <span class="section-caption">选择场景，立即开始</span>
      </div>
      <div class="feature-grid">
        <router-link
          v-for="feature in features"
          :key="feature.slug"
          :to="`/workspace/feature/${feature.slug}`"
          class="feature-card"
          :class="feature.tone"
        >
          <div class="feature-card-top">
            <div class="feature-icon"><AppIcon :name="feature.icon" :size="22" /></div>
            <span class="feature-arrow"><AppIcon name="arrow-right" :size="18" /></span>
          </div>
          <div class="feature-card-content">
            <h3>{{ feature.title }}</h3>
            <p>{{ feature.description }}</p>
          </div>
          <div class="feature-card-foot">
            <span>{{ feature.meta }}</span>
            <span class="feature-tag">{{ feature.tag }}</span>
          </div>
        </router-link>
      </div>
    </section>

    <section class="bottom-grid">
      <div class="activity-panel">
        <div class="section-heading compact">
          <div><p class="eyebrow">RECENT</p><h2>最近使用</h2></div>
          <button class="text-button" type="button">查看全部 <AppIcon name="arrow-right" :size="15" /></button>
        </div>
        <div class="activity-list">
          <div v-for="item in recentItems" :key="item.title" class="activity-row">
            <div class="activity-mark" :class="item.tone"><AppIcon :name="item.icon" :size="17" /></div>
            <div class="activity-main"><strong>{{ item.title }}</strong><span>{{ item.subtitle }}</span></div>
            <span class="activity-time">{{ item.time }}</span>
            <AppIcon name="more" :size="19" class="more-icon" />
          </div>
        </div>
      </div>
      <div class="insight-panel">
        <div class="insight-label"><AppIcon name="sparkles" :size="16" /> 智能提示</div>
        <h3>你的行业简报已准备好</h3>
        <p>过去 24 小时内，系统聚合了 32 条与你所在行业相关的新动态，包含 4 条重点政策变化。</p>
        <router-link to="/workspace/feature/industry-news" class="insight-link">立即查看 <AppIcon name="arrow-right" :size="16" /></router-link>
      </div>
    </section>
  </div>
</template>

<script setup>
import AppIcon from '../components/AppIcon.vue';

const features = [
  { slug: 'policy-qa', title: '行业政策法规智能问答', description: '快速检索政策原文，获得有依据、可追溯的专业解读。', icon: 'book', tone: 'tone-blue', meta: '政策库 12,680 条', tag: '知识问答' },
  { slug: 'news-drafting', title: '企业公告与新闻稿智能撰写', description: '从事实素材到正式成稿，支持多种发布场景与文风。', icon: 'pen', tone: 'tone-cyan', meta: '7 个常用模板', tag: '内容创作' },
  { slug: 'industry-news', title: '行业动态与竞品信息智能聚合', description: '聚合行业资讯、竞品动作与趋势信号，形成每日简报。', icon: 'pulse', tone: 'tone-violet', meta: '今日 32 条更新', tag: '信息聚合' },
  { slug: 'public-opinion', title: '企业舆情分析', description: '全网声量、情感倾向与风险节点一屏掌握，辅助快速研判。', icon: 'chart', tone: 'tone-amber', meta: '监测中 18 个关键词', tag: '风险洞察' },
  { slug: 'qualification-guide', title: '企业资质与服务指南智能编制', description: '基于企业材料生成清晰、规范、易读的服务与办理指南。', icon: 'file', tone: 'tone-green', meta: '已沉淀 16 份材料', tag: '指南编制' },
  { slug: 'meeting-brief', title: '会议公开信息整理', description: '从会议记录、议程与公开信息中提炼重点，生成结构化纪要。', icon: 'calendar', tone: 'tone-rose', meta: '支持 Word / PDF', tag: '会议助手' },
];

const recentItems = [
  { title: '关于智能办公平台试运行的通知', subtitle: '企业公告与新闻稿智能撰写 · 已保存', icon: 'pen', tone: 'cyan', time: '今天 09:42' },
  { title: '2026 年制造业数字化转型政策速览', subtitle: '行业政策法规智能问答 · 已导出', icon: 'book', tone: 'blue', time: '昨天 16:18' },
  { title: '华东区域重点竞品周报', subtitle: '行业动态与竞品信息智能聚合 · 已完成', icon: 'pulse', tone: 'violet', time: '8 月 18 日', },
];
</script>
