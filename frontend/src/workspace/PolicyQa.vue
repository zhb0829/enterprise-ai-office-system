<template>
  <main class="policy-page">
    <section class="policy-header">
      <div>
        <p class="eyebrow">行业政策法规智能问答</p>
        <h2>先找到依据，再理解要求。</h2>
        <p class="policy-lead">
          只基于公开文件与已入库材料检索。每条回答都保留原文出处，检索不到明确依据时不会生成结论。
        </p>
      </div>
      <div class="policy-signal" aria-label="当前能力状态">
        <span class="signal-dot"></span>
        <span>公开来源溯源已开启</span>
      </div>
    </section>

    <section class="policy-layout">
      <aside class="policy-query-panel" aria-label="政策问答输入">
        <div class="mode-tabs" role="tablist" aria-label="政策能力模式">
          <button
            v-for="item in modes"
            :key="item.key"
            type="button"
            :class="{ active: mode === item.key }"
            :aria-selected="mode === item.key"
            role="tab"
            @click="mode = item.key"
          >
            {{ item.label }}
          </button>
        </div>

        <form v-if="mode === 'qa'" class="query-form" @submit.prevent="submitQuestion">
          <label class="policy-field">
            <span>自然语言问题</span>
            <textarea
              v-model="question"
              rows="7"
              placeholder="例如：高新技术企业认定对研发费用占比有什么要求？"
            ></textarea>
          </label>
          <div class="filter-grid">
            <label class="policy-field">
              <span>行业</span>
              <input v-model="filters.industry" placeholder="例如：科技" />
            </label>
            <label class="policy-field">
              <span>效力级别</span>
              <select v-model="filters.level">
                <option value="">全部级别</option>
                <option value="法律">法律</option>
                <option value="行政法规">行政法规</option>
                <option value="部门规章">部门规章</option>
                <option value="地方性法规">地方性法规</option>
                <option value="标准">标准</option>
                <option value="其他">其他</option>
              </select>
            </label>
          </div>
          <button class="policy-primary" type="submit" :disabled="loading || question.trim().length < 2">
            {{ loading ? '检索与核验中...' : '检索政策依据' }}
          </button>
          <p v-if="errorMessage" class="policy-error" role="alert">{{ errorMessage }}</p>
        </form>

        <form v-else class="query-form" @submit.prevent="submitCompliance">
          <label class="policy-field">
            <span>企业公开业务描述</span>
            <textarea
              v-model="businessDesc"
              rows="10"
              placeholder="描述公开经营活动、服务对象、资质证照或可能涉及的数据、用工、宣传行为。"
            ></textarea>
          </label>
          <label class="policy-field">
            <span>所属行业</span>
            <input v-model="filters.industry" placeholder="例如：互联网信息服务" />
          </label>
          <button class="policy-primary" type="submit" :disabled="loading || businessDesc.trim().length < 10">
            {{ loading ? '比对与整理中...' : '开始初步比对' }}
          </button>
          <p class="policy-disclaimer">仅做风险提示，不出具法律意见；信息不足时会标记为“待人工核实”。</p>
          <p v-if="errorMessage" class="policy-error" role="alert">{{ errorMessage }}</p>
        </form>
      </aside>

      <section class="policy-result-panel" aria-live="polite" :aria-busy="loading">
        <div v-if="mode === 'qa'" class="result-content">
          <div class="result-heading">
            <div>
              <p class="eyebrow">检索结果</p>
              <h3>{{ answer?.confidence === 'none' ? '暂未找到明确依据' : '结构化政策回答' }}</h3>
            </div>
            <span v-if="answer" class="confidence-badge" :class="answer.confidence">{{ confidenceLabel }}</span>
          </div>
          <div v-if="answer" class="answer-block">
            <p v-for="(paragraph, index) in answer.answer.split('\n')" :key="index">{{ paragraph }}</p>
            <div class="answer-meta">
              <span>意图：{{ answer.intent }}</span>
              <span>模型：{{ answer.model }}</span>
              <span>关键词：{{ answer.queryTerms.join('、') || '无' }}</span>
            </div>
          </div>
          <div v-else class="empty-result">
            <strong>输入一个政策问题开始检索</strong>
            <span>结果会显示条款原文、文件状态和可验证来源。</span>
          </div>
          <div v-if="answer?.riskFlags?.length" class="risk-strip">
            <strong>核验提示</strong>
            <span v-for="flag in answer.riskFlags" :key="flag">{{ flag }}</span>
          </div>
          <section v-if="answer?.clauses?.length" class="clause-section" aria-labelledby="clause-title">
            <div class="subhead-row">
              <div>
                <p class="eyebrow">证据链</p>
                <h4 id="clause-title">相关条款（{{ answer.clauses.length }}）</h4>
              </div>
              <span class="subhead-note">默认仅展示现行有效文件</span>
            </div>
            <article v-for="(clause, index) in answer.clauses" :key="clause.id || index" class="clause-card">
              <div class="clause-topline">
                <span class="citation-index">{{ index + 1 }}</span>
                <div class="clause-title">
                  <strong>{{ clause.docTitle }}</strong>
                  <span>{{ clause.articleNo || '语义片段' }} · {{ clause.status }}</span>
                </div>
                <button
                  class="small-action"
                  type="button"
                  :disabled="interpretingClauseId === clause.id"
                  @click="interpret(clause)"
                >
                  {{ interpretingClauseId === clause.id ? '解读中...' : '解读' }}
                </button>
              </div>
              <p class="clause-excerpt">{{ clause.excerpt }}</p>
              <div class="clause-source">
                <span>出处{{ clause.page ? ` · 第 ${clause.page} 页` : '' }}</span>
                <a v-if="clause.sourceUrl" :href="clause.sourceUrl" target="_blank" rel="noreferrer">打开原文</a>
                <span v-else>上传文件出处</span>
              </div>
            </article>
          </section>
        </div>

        <div v-else class="result-content">
          <div class="result-heading">
            <div>
              <p class="eyebrow">合规初步比对</p>
              <h3>把公开描述拆成待核实清单</h3>
            </div>
            <span class="confidence-badge medium">仅供参考</span>
          </div>
          <div v-if="compliance" class="compliance-list">
            <article v-for="(item, index) in compliance.items" :key="index" class="compliance-item">
              <div class="compliance-topline">
                <span class="citation-index">{{ index + 1 }}</span>
                <strong>{{ item.riskLevel }}</strong>
              </div>
              <p>{{ item.requirement }}</p>
              <dl>
                <div><dt>企业现状匹配</dt><dd>{{ item.enterpriseMatch }}</dd></div>
                <div><dt>建议动作</dt><dd>{{ item.suggestion }}</dd></div>
              </dl>
              <button v-if="item.citation" class="source-link" type="button" @click="openCitation(item.citation)">
                查看条款出处：{{ item.citation.docTitle }} {{ item.citation.articleNo }}
              </button>
            </article>
            <div v-if="!compliance.items.length" class="empty-result">
              <strong>没有可用于比对的现行有效条款</strong>
              <span>请补充行业信息或先让管理员导入公开政策文件。</span>
            </div>
            <p class="policy-disclaimer strong">{{ compliance.disclaimer }}</p>
          </div>
          <div v-else class="empty-result">
            <strong>输入企业公开业务描述开始比对</strong>
            <span>系统只会提示潜在合规点，不会替代专业法律判断。</span>
          </div>
        </div>
      </section>
    </section>

    <aside v-if="selectedCitation" class="citation-drawer" aria-label="原文出处">
      <div class="drawer-head">
        <div>
          <p class="eyebrow">原文出处</p>
          <h3>{{ selectedCitation.docTitle }}</h3>
        </div>
        <button class="drawer-close" type="button" aria-label="关闭原文出处" @click="selectedCitation = null">关闭</button>
      </div>
      <p class="drawer-article">{{ selectedCitation.articleNo || '相关语义片段' }}</p>
      <blockquote>{{ selectedCitation.excerpt }}</blockquote>
      <a v-if="selectedCitation.sourceUrl" :href="selectedCitation.sourceUrl" target="_blank" rel="noreferrer">在公开网页中查看</a>
      <span v-else class="muted-source">该条款来自用户上传的公开文件。</span>
    </aside>

    <aside v-if="interpretation" class="interpret-drawer" aria-label="条款解读">
      <div class="drawer-head">
        <div>
          <p class="eyebrow">条款解读</p>
          <h3>{{ interpretation.citations?.[0]?.docTitle || '用户提供条文' }}</h3>
        </div>
        <button class="drawer-close" type="button" aria-label="关闭条款解读" @click="interpretation = null">关闭</button>
      </div>
      <p class="interpret-summary">{{ interpretation.plainSummary }}</p>
      <div class="interpret-grid">
        <section><span>适用对象</span><p>{{ interpretation.applicableObjects.join('；') || '未明确' }}</p></section>
        <section><span>关键义务</span><p>{{ interpretation.obligations.join('；') || '未明确' }}</p></section>
        <section><span>禁止事项</span><p>{{ interpretation.prohibitions.join('；') || '未明确' }}</p></section>
        <section><span>违反后果</span><p>{{ interpretation.consequences.join('；') || '原文未明确' }}</p></section>
      </div>
      <p class="policy-disclaimer strong">{{ interpretation.disclaimer }}</p>
    </aside>
  </main>
</template>

<script setup>
import { computed, ref } from 'vue';
import { askPolicy, checkPolicyCompliance, interpretPolicyClause } from '../api';

const modes = [
  { key: 'qa', label: '政策问答' },
  { key: 'compliance', label: '合规比对' },
];
const mode = ref('qa');
const question = ref('');
const businessDesc = ref('');
const loading = ref(false);
const errorMessage = ref('');
const answer = ref(null);
const compliance = ref(null);
const selectedCitation = ref(null);
const interpretation = ref(null);
const interpretingClauseId = ref(null);
const filters = ref({ industry: '', level: '' });

const confidenceLabel = computed(() => ({ high: '高相关', medium: '中相关', none: '无命中' }[answer.value?.confidence] || '待核验'));

async function submitQuestion() {
  loading.value = true;
  errorMessage.value = '';
  selectedCitation.value = null;
  interpretation.value = null;
  try {
    answer.value = await askPolicy({
      question: question.value,
      industry: filters.value.industry,
      level: filters.value.level,
      sessionId: `policy-${Date.now()}`,
    });
  } catch (error) {
    errorMessage.value = error.message;
  } finally {
    loading.value = false;
  }
}

async function submitCompliance() {
  loading.value = true;
  errorMessage.value = '';
  selectedCitation.value = null;
  try {
    compliance.value = await checkPolicyCompliance({
      businessDesc: businessDesc.value,
      industry: filters.value.industry,
      sessionId: `compliance-${Date.now()}`,
    });
  } catch (error) {
    errorMessage.value = error.message;
  } finally {
    loading.value = false;
  }
}

async function interpret(clause) {
  errorMessage.value = '';
  interpretation.value = null;
  interpretingClauseId.value = clause.id;
  try {
    interpretation.value = await interpretPolicyClause({ clauseId: clause.id });
  } catch (error) {
    errorMessage.value = `条款解读失败：${error.message}`;
  } finally {
    interpretingClauseId.value = null;
  }
}

function openCitation(citation) {
  selectedCitation.value = citation;
}
</script>

<style scoped>
.policy-page {
  position: relative;
  max-width: 1480px;
  margin: 0 auto;
  padding: clamp(24px, 4vw, 56px) clamp(16px, 4vw, 52px) 80px;
  color: #17233a;
}

.policy-header {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 28px;
  padding: 22px 0 34px;
  border-bottom: 1px solid #dfe5ed;
}

.policy-header h2 {
  max-width: 800px;
  margin: 0;
  font-size: clamp(2rem, 4vw, 4.8rem);
  line-height: 1.06;
  letter-spacing: 0;
}

.policy-lead {
  max-width: 720px;
  margin: 16px 0 0;
  color: #64748b;
  font-size: 1rem;
  line-height: 1.75;
}

.policy-signal {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex: 0 0 auto;
  padding: 10px 12px;
  border: 1px solid #cfe7dd;
  border-radius: 999px;
  color: #166534;
  background: #f1fbf6;
  font-size: 13px;
  font-weight: 700;
}

.signal-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #16a34a;
}

.policy-layout {
  display: grid;
  grid-template-columns: minmax(300px, 370px) minmax(0, 1fr);
  gap: 18px;
  align-items: start;
  padding-top: 24px;
}

.policy-query-panel,
.policy-result-panel {
  border: 1px solid #dfe5ed;
  border-radius: 8px;
  background: #ffffff;
  box-shadow: 0 12px 32px rgba(25, 44, 72, 0.06);
}

.policy-query-panel {
  position: sticky;
  top: 88px;
  overflow: hidden;
}

.mode-tabs {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  border-bottom: 1px solid #e6ebf1;
}

.mode-tabs button {
  min-height: 48px;
  border: 0;
  border-bottom: 3px solid transparent;
  background: #fbfcfe;
  color: #64748b;
  font-weight: 700;
  cursor: pointer;
}

.mode-tabs button.active {
  border-color: #2563eb;
  color: #1d4ed8;
  background: #ffffff;
}

.query-form {
  display: grid;
  gap: 16px;
  padding: 20px;
}

.policy-field {
  display: grid;
  gap: 7px;
  color: #334155;
  font-size: 13px;
  font-weight: 700;
}

.policy-field textarea,
.policy-field input,
.policy-field select {
  box-sizing: border-box;
  min-height: 44px;
  border: 1px solid #cfd8e3;
  border-radius: 6px;
  padding: 10px 11px;
  color: #17233a;
  background: #ffffff;
  font: inherit;
  font-weight: 400;
  resize: vertical;
}

.policy-field textarea:focus,
.policy-field input:focus,
.policy-field select:focus,
.mode-tabs button:focus-visible,
.small-action:focus-visible,
.source-link:focus-visible,
.drawer-close:focus-visible {
  outline: 3px solid rgba(37, 99, 235, 0.2);
  outline-offset: 2px;
}

.filter-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.policy-primary {
  min-height: 46px;
  border: 0;
  border-radius: 6px;
  padding: 10px 14px;
  color: #ffffff;
  background: #1d4ed8;
  font-weight: 800;
  cursor: pointer;
  transition: background 180ms ease, transform 180ms ease;
}

.policy-primary:hover:not(:disabled) {
  background: #1e40af;
  transform: translateY(-1px);
}

.policy-primary:disabled {
  cursor: not-allowed;
  opacity: 0.52;
}

.policy-error {
  margin: 0;
  color: #b42318;
  font-size: 13px;
  line-height: 1.5;
}

.policy-disclaimer {
  margin: 0;
  color: #8a5a0a;
  font-size: 12px;
  line-height: 1.6;
}

.policy-disclaimer.strong {
  margin-top: 18px;
  color: #7c4a03;
  font-weight: 700;
}

.result-content {
  min-height: 650px;
  padding: 24px clamp(18px, 3vw, 36px) 36px;
}

.result-heading,
.subhead-row,
.clause-topline,
.compliance-topline,
.drawer-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
}

.result-heading h3,
.drawer-head h3 {
  margin: 0;
  font-size: 22px;
  line-height: 1.3;
}

.confidence-badge {
  flex: 0 0 auto;
  border-radius: 999px;
  padding: 7px 10px;
  color: #166534;
  background: #dcfce7;
  font-size: 12px;
  font-weight: 800;
}

.confidence-badge.medium {
  color: #92400e;
  background: #fef3c7;
}

.confidence-badge.none {
  color: #64748b;
  background: #eef2f7;
}

.answer-block {
  margin-top: 24px;
  padding: 18px 20px;
  border-left: 4px solid #2563eb;
  background: #f7faff;
}

.answer-block p {
  margin: 0 0 12px;
  color: #24344f;
  line-height: 1.85;
  white-space: pre-wrap;
}

.answer-block p:last-child {
  margin-bottom: 0;
}

.answer-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
  margin-top: 16px;
  color: #64748b;
  font-size: 12px;
}

.empty-result {
  display: grid;
  gap: 8px;
  place-content: center;
  min-height: 250px;
  color: #64748b;
  text-align: center;
}

.empty-result strong {
  color: #334155;
  font-size: 16px;
}

.risk-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 18px 0;
  padding: 12px 14px;
  border: 1px solid #f3d7a0;
  background: #fffaf0;
  color: #8a5a0a;
  font-size: 12px;
  line-height: 1.5;
}

.clause-section {
  margin-top: 28px;
}

.subhead-row {
  align-items: end;
  margin-bottom: 12px;
}

.subhead-row h4 {
  margin: 0;
  font-size: 17px;
}

.subhead-note {
  color: #64748b;
  font-size: 12px;
}

.clause-card,
.compliance-item {
  margin-top: 10px;
  padding: 16px;
  border: 1px solid #e0e7ef;
  border-radius: 7px;
  background: #fbfcfe;
}

.citation-index {
  display: inline-grid;
  place-items: center;
  width: 28px;
  height: 28px;
  flex: 0 0 28px;
  border-radius: 50%;
  color: #1d4ed8;
  background: #e8f0ff;
  font-size: 12px;
  font-weight: 800;
}

.clause-title {
  display: grid;
  gap: 4px;
  min-width: 0;
  flex: 1;
}

.clause-title strong {
  overflow: hidden;
  color: #263752;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.clause-title span,
.clause-source,
.muted-source {
  color: #64748b;
  font-size: 12px;
}

.small-action,
.drawer-close {
  min-height: 34px;
  border: 1px solid #cbd8ee;
  border-radius: 6px;
  padding: 6px 10px;
  color: #1d4ed8;
  background: #ffffff;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}

.small-action:disabled {
  cursor: wait;
  opacity: 0.65;
}

.clause-excerpt {
  margin: 13px 0 12px 42px;
  color: #334155;
  line-height: 1.7;
  white-space: pre-wrap;
}

.clause-source {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  margin-left: 42px;
}

.clause-source a,
.citation-drawer a {
  color: #1d4ed8;
  font-weight: 700;
  text-decoration: none;
}

.compliance-list {
  margin-top: 24px;
}

.compliance-topline {
  align-items: center;
  justify-content: flex-start;
}

.compliance-topline strong {
  color: #92400e;
  font-size: 13px;
}

.compliance-item > p {
  margin: 14px 0;
  color: #334155;
  line-height: 1.7;
}

.compliance-item dl {
  display: grid;
  gap: 10px;
  margin: 0;
}

.compliance-item dl div {
  display: grid;
  grid-template-columns: 100px minmax(0, 1fr);
  gap: 12px;
}

.compliance-item dt {
  color: #64748b;
  font-size: 12px;
}

.compliance-item dd {
  margin: 0;
  color: #475569;
  font-size: 13px;
  line-height: 1.6;
}

.source-link {
  margin-top: 14px;
  border: 0;
  padding: 0;
  color: #1d4ed8;
  background: transparent;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}

.citation-drawer,
.interpret-drawer {
  position: fixed;
  z-index: 20;
  right: 22px;
  bottom: 22px;
  width: min(440px, calc(100vw - 44px));
  padding: 20px;
  border: 1px solid #cad5e2;
  border-radius: 8px;
  background: #ffffff;
  box-shadow: 0 20px 55px rgba(15, 23, 42, 0.2);
}

.interpret-drawer {
  right: auto;
  left: 22px;
  width: min(520px, calc(100vw - 44px));
}

.drawer-head h3 {
  max-width: 330px;
  font-size: 17px;
}

.drawer-article {
  margin: 16px 0 8px;
  color: #1d4ed8;
  font-size: 13px;
  font-weight: 800;
}

.citation-drawer blockquote {
  margin: 0 0 14px;
  padding: 12px 14px;
  border-left: 3px solid #2563eb;
  color: #334155;
  background: #f7faff;
  line-height: 1.7;
  white-space: pre-wrap;
}

.interpret-summary {
  margin: 18px 0;
  color: #334155;
  line-height: 1.75;
}

.interpret-grid {
  display: grid;
  gap: 10px;
}

.interpret-grid section {
  padding: 10px 12px;
  border: 1px solid #e1e7ef;
  background: #fbfcfe;
}

.interpret-grid span {
  color: #64748b;
  font-size: 12px;
  font-weight: 700;
}

.interpret-grid p {
  margin: 6px 0 0;
  color: #334155;
  line-height: 1.6;
}

@media (max-width: 960px) {
  .policy-layout {
    grid-template-columns: 1fr;
  }

  .policy-query-panel {
    position: static;
  }
}

@media (max-width: 620px) {
  .policy-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .filter-grid,
  .compliance-item dl div {
    grid-template-columns: 1fr;
  }

  .clause-excerpt,
  .clause-source {
    margin-left: 0;
  }

  .clause-excerpt {
    margin-top: 14px;
  }

  .citation-drawer,
  .interpret-drawer {
    right: 12px;
    bottom: 12px;
    left: 12px;
    width: auto;
  }
}
</style>
