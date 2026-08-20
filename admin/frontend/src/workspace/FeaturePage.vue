<template>
  <div class="feature-page">
    <div class="page-breadcrumb">
      <router-link to="/workspace"><AppIcon name="arrow-left" :size="16" /> 工作台</router-link>
      <span>/</span>
      <span>{{ feature.title }}</span>
    </div>

    <section class="feature-hero" :class="feature.tone">
      <div class="feature-hero-copy">
        <div class="feature-icon large"><AppIcon :name="feature.icon" :size="27" /></div>
        <p class="eyebrow">AI WORKSPACE · {{ feature.category }}</p>
        <h1>{{ feature.title }}</h1>
        <p>{{ feature.description }}</p>
      </div>
      <div class="hero-stat">
        <span>本场景已服务</span>
        <strong>{{ feature.usage }}</strong>
        <small>次企业任务</small>
      </div>
    </section>

    <div class="feature-workspace">
      <section class="input-panel">
        <div class="panel-heading">
          <div><p class="eyebrow">STEP 01</p><h2>{{ feature.inputTitle }}</h2></div>
          <span class="panel-count">预计 1-2 分钟</span>
        </div>

        <label class="field">
          <span>{{ feature.primaryLabel }}</span>
          <textarea v-model="inputText" rows="7" :placeholder="feature.placeholder"></textarea>
        </label>
        <div class="field-row">
          <label class="field">
            <span>{{ feature.optionLabel }}</span>
            <select v-model="selectedOption">
              <option v-for="option in feature.options" :key="option" :value="option">{{ option }}</option>
            </select>
          </label>
          <label class="field">
            <span>输出语言</span>
            <select v-model="language"><option>简体中文</option><option>中英双语</option></select>
          </label>
        </div>
        <div class="source-box">
          <div class="source-head"><span><AppIcon name="file" :size="16" /> 参考材料</span><button type="button" class="text-button">添加材料</button></div>
          <div class="source-chips"><span v-for="source in feature.sources" :key="source"><AppIcon name="check" :size="13" /> {{ source }}</span></div>
        </div>
        <button class="run-button" type="button" :disabled="running" @click="runTask">
          <AppIcon :name="running ? 'clock' : 'sparkles'" :size="18" />
          {{ running ? 'AI 正在处理…' : feature.cta }}
        </button>
        <p v-if="validationMessage" class="validation-message">{{ validationMessage }}</p>
      </section>

      <section class="result-panel">
        <div class="panel-heading result-heading">
          <div><p class="eyebrow">STEP 02</p><h2>{{ feature.resultTitle }}</h2></div>
          <div class="result-actions">
            <button class="icon-action" type="button" title="复制结果" aria-label="复制结果" @click="copyResult"><AppIcon name="file" :size="17" /></button>
            <button class="icon-action" type="button" title="更多操作" aria-label="更多操作"><AppIcon name="more" :size="18" /></button>
          </div>
        </div>
        <div v-if="running" class="result-loading">
          <span class="loading-orbit"><AppIcon name="sparkles" :size="18" /></span>
          <strong>正在分析你的输入</strong>
          <p>AI 正在理解内容、匹配知识与组织结果</p>
          <div class="loading-lines"><i></i><i></i><i></i></div>
        </div>
        <article v-else class="result-content">
          <div class="result-meta"><span class="ready-dot"></span> 已生成 · {{ generatedAt }}</div>
          <h3>{{ resultTitle }}</h3>
          <p v-for="paragraph in resultParagraphs" :key="paragraph">{{ paragraph }}</p>
          <div class="result-tags"><span v-for="tag in feature.resultTags" :key="tag">{{ tag }}</span></div>
          <div class="confidence-row"><span>结果可信度</span><strong>{{ feature.confidence }}%</strong><div class="confidence-bar"><i :style="{ width: `${feature.confidence}%` }"></i></div></div>
        </article>
        <div class="result-foot"><span><AppIcon name="book" :size="14" /> 结果由企业知识库与公开信息共同生成</span><button type="button" class="text-button">查看依据 <AppIcon name="arrow-right" :size="15" /></button></div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import AppIcon from '../components/AppIcon.vue';
import { createDraftStream } from '../api';

const route = useRoute();
const inputText = ref('');
const selectedOption = ref('');
const language = ref('简体中文');
const running = ref(false);
const validationMessage = ref('');
const generatedAt = ref('刚刚');
const customResult = ref('');

const featureMap = {
  'policy-qa': {
    title: '行业政策法规智能问答', category: '知识问答', icon: 'book', tone: 'tone-blue', usage: '1,286', inputTitle: '描述你的问题', primaryLabel: '问题内容', optionLabel: '关注领域', cta: '开始智能问答', resultTitle: '政策解读结果', resultTitleDefault: '关于制造业数字化转型的政策要点', placeholder: '例如：2026 年制造业数字化转型有哪些支持政策？我们需要满足什么申报条件？', options: ['制造业数字化', '科技创新', '人力资源', '市场监管'], sources: ['国家政策法规库', '企业内部政策库'], resultTags: ['政策原文', '适用条件', '办理建议'], confidence: 96, result: ['根据当前政策库，制造业数字化转型支持主要集中在设备更新、智能工厂建设与工业软件应用三个方向。', '建议优先核对企业所属行业、营收规模及项目投资额等申报条件，再根据属地政策确认申报窗口。'],
  },
  'news-drafting': {
    title: '企业公告与新闻稿智能撰写', category: '内容创作', icon: 'pen', tone: 'tone-cyan', usage: '846', inputTitle: '提供写作素材', primaryLabel: '事实与核心信息', optionLabel: '文稿类型', cta: '生成文稿', resultTitle: '智能成稿预览', resultTitleDefault: '关于智能办公平台试运行的通知', placeholder: '粘贴事件背景、发布时间、面向对象、关键动作等素材，AI 将自动组织成正式文稿。', options: ['正式公告', '新闻稿', '媒体通稿', '内部通知'], sources: ['公告模板库', '企业品牌语料'], resultTags: ['正式文风', '事实核查', '可导出'], confidence: 94, result: ['为提升企业信息协同效率，公司将于 2026 年 8 月 20 日起启动智能办公平台试运行。', '试运行期间，平台将提供素材解析、文稿生成、事实核查与版本回溯等能力，请各部门安排专人参与体验并反馈使用建议。'],
  },
  'industry-news': {
    title: '行业动态与竞品信息智能聚合', category: '信息聚合', icon: 'pulse', tone: 'tone-violet', usage: '532', inputTitle: '配置聚合范围', primaryLabel: '关注主题与关键词', optionLabel: '简报周期', cta: '生成行业简报', resultTitle: '今日行业简报', resultTitleDefault: '制造业数字化 · 8 月 20 日动态', placeholder: '例如：关注工业软件、智能工厂，以及主要竞品在华东区域的市场动作。', options: ['每日简报', '每周简报', '月度趋势'], sources: ['行业媒体 128 家', '竞品公开信息', '政策公告源'], resultTags: ['32 条更新', '4 条重点', '已去重'], confidence: 91, result: ['今日共发现 32 条相关动态，其中 4 条被识别为高价值信号：两家头部厂商发布区域合作计划，三项地方扶持政策进入申报期。', '建议关注竞品在渠道合作与行业解决方案上的动作，可能影响 Q3 华东区域的市场节奏。'],
  },
  'public-opinion': {
    title: '企业舆情分析', category: '风险洞察', icon: 'chart', tone: 'tone-amber', usage: '214', inputTitle: '选择分析对象', primaryLabel: '企业 / 品牌 / 事件', optionLabel: '分析周期', cta: '开始舆情分析', resultTitle: '舆情分析摘要', resultTitleDefault: '本周品牌舆情健康度', placeholder: '输入企业名称、品牌关键词或指定事件，系统将分析声量、情感和传播节点。', options: ['近 24 小时', '近 7 天', '近 30 天'], sources: ['新闻媒体', '社交平台', '行业论坛'], resultTags: ['声量平稳', '正向为主', '2 个风险点'], confidence: 89, result: ['本周期全网相关声量 1,842 条，较上周期上升 8.4%，整体情感倾向以正向和中性为主。', '当前有 2 个风险点值得关注：一条负面反馈正在区域性扩散，另一个议题与服务响应时效有关，建议在 24 小时内完成回应。'],
  },
  'qualification-guide': {
    title: '企业资质与服务指南智能编制', category: '指南编制', icon: 'file', tone: 'tone-green', usage: '168', inputTitle: '选择编制主题', primaryLabel: '服务事项与材料说明', optionLabel: '指南类型', cta: '生成服务指南', resultTitle: '指南内容预览', resultTitleDefault: '企业高新技术企业认定服务指南', placeholder: '描述需要编制的资质办理、服务事项或材料清单，AI 将生成结构化指南。', options: ['资质办理指南', '企业服务手册', '对外办事指南', '材料清单'], sources: ['资质知识库', '办事流程库'], resultTags: ['办理流程', '材料清单', '注意事项'], confidence: 95, result: ['本指南适用于计划申报高新技术企业认定的企业，内容覆盖申报条件、准备材料、办理流程与常见问题。', '建议按“企业基本情况—研发项目—知识产权—财务数据”四个部分准备材料，并在提交前完成材料有效期与盖章要求核验。'],
  },
  'meeting-brief': {
    title: '会议公开信息整理', category: '会议助手', icon: 'calendar', tone: 'tone-rose', usage: '406', inputTitle: '上传或粘贴会议内容', primaryLabel: '会议记录 / 议程 / 公开信息', optionLabel: '整理格式', cta: '生成会议简报', resultTitle: '会议整理结果', resultTitleDefault: '经营分析会 · 重点信息摘要', placeholder: '粘贴会议记录、议程、演讲稿或公开信息，AI 将提取议题、结论与待办事项。', options: ['会议纪要', '领导简报', '决策摘要', '行动清单'], sources: ['会议材料 3 份', '公开信息源'], resultTags: ['3 项结论', '5 项待办', '已提取责任人'], confidence: 93, result: ['本次会议围绕经营目标、重点项目推进与客户服务三个议题展开，形成 3 项明确结论。', '已提取 5 项后续行动：明确项目负责人、补充区域数据、更新客户响应机制，并于下周一前完成复盘材料。'],
  },
};

const feature = computed(() => featureMap[route.params.slug] || featureMap['policy-qa']);
const resultTitle = computed(() => customResult.value ? '已根据你的输入生成新结果' : feature.value.resultTitleDefault);
const resultParagraphs = computed(() => customResult.value ? [customResult.value, '系统已完成重点提取、结构化整理与风险提示，你可以继续补充信息并重新生成。'] : feature.value.result);

selectedOption.value = feature.value.options[0];

watch(
  () => route.params.slug,
  () => {
    selectedOption.value = feature.value.options[0];
    inputText.value = '';
    customResult.value = '';
    validationMessage.value = '';
  }
);

async function runTask() {
  validationMessage.value = '';
  if (!inputText.value.trim()) {
    validationMessage.value = '请先输入一些内容，AI 才能开始工作。';
    return;
  }
  running.value = true;
  customResult.value = '';
  try {
    if (route.params.slug === 'news-drafting') {
      let streamed = '';
      await createDraftStream({ title: '', eventDesc: inputText.value, audience: '企业相关人员', style: '正式', template: selectedOption.value === '新闻稿' ? 'news_release' : 'formal_announcement', keyFacts: [], people: [], referenceMaterials: [] }, (event) => {
        if (event.type === 'delta') streamed += event.text;
        if (event.type === 'done' && !streamed) streamed = '已完成文稿生成，请在右侧预览并继续编辑。';
      });
      customResult.value = streamed;
    } else {
      await new Promise((resolve) => window.setTimeout(resolve, 900));
      customResult.value = `围绕“${inputText.value.slice(0, 42)}${inputText.value.length > 42 ? '…' : ''}”，系统已完成多源信息分析，并提炼出与${selectedOption.value}相关的关键结果。`;
    }
    generatedAt.value = '刚刚';
  } catch {
    customResult.value = '演示模式已生成结果。连接后端服务后，将自动替换为基于企业知识库的实时分析内容。';
  } finally {
    running.value = false;
  }
}

async function copyResult() {
  await navigator.clipboard?.writeText([resultTitle.value, ...resultParagraphs.value].join('\n\n'));
}
</script>
