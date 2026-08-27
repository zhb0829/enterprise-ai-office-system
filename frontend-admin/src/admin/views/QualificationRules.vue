<template>
  <section class="page-shell">
    <header class="page-head">
      <div>
        <h2>资质编制校验规则</h2>
        <p class="page-sub">维护系统级格式、引用与占位符校验规则，规则只影响后续生成任务。</p>
      </div>
      <button class="primary-button" type="button" :disabled="loading" @click="loadRules">
        {{ loading ? '刷新中…' : '刷新规则' }}
      </button>
    </header>

    <p v-if="errorMessage" class="error-text" role="alert">{{ errorMessage }}</p>
    <section class="panel">
      <div v-if="!rules.length && !loading" class="empty-state">
        暂无规则，后端会在首次访问时初始化默认规则。
      </div>
      <div v-else class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>编码</th>
              <th>规则名称</th>
              <th>规则类型</th>
              <th>配置</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="rule in rules" :key="rule.id">
              <td><code>{{ rule.code }}</code></td>
              <td>{{ rule.name }}</td>
              <td>{{ rule.ruleType }}</td>
              <td><pre class="rule-json">{{ JSON.stringify(rule.rule || {}, null, 2) }}</pre></td>
              <td>
                <span :class="['status-pill', { online: rule.enabled }]">
                  <span></span>{{ rule.enabled ? '启用' : '停用' }}
                </span>
              </td>
              <td>
                <button class="ghost-button" type="button" @click="editRule(rule)">编辑</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section v-if="editing" class="panel rule-editor">
      <div class="page-head">
        <div>
          <h3>编辑规则</h3>
          <p class="page-sub">保存前请确认规则不会绕过人工审核或引用要求。</p>
        </div>
        <button class="ghost-button" type="button" @click="editing = null">取消</button>
      </div>
      <div class="rule-form-grid">
        <label class="field">
          <span>编码</span>
          <input v-model.trim="editing.code" disabled />
        </label>
        <label class="field">
          <span>名称</span>
          <input v-model.trim="editing.name" />
        </label>
        <label class="field">
          <span>规则类型</span>
          <input v-model.trim="editing.ruleType" disabled />
        </label>
        <label class="check-inline rule-enabled">
          <input v-model="editing.enabled" type="checkbox" />
          启用
        </label>
      </div>
      <label class="field">
        <span>JSON 配置</span>
        <textarea v-model="ruleJson" rows="6"></textarea>
      </label>
      <div class="modal-actions">
        <button class="primary-button small-primary" type="button" :disabled="saving" @click="saveRule">
          {{ saving ? '保存中…' : '保存规则' }}
        </button>
      </div>
    </section>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { fetchQualValidationRules, saveQualValidationRule } from '../../api';

const rules = ref([]);
const editing = ref(null);
const loading = ref(false);
const saving = ref(false);
const errorMessage = ref('');

const ruleJson = computed({
  get: () => JSON.stringify(editing.value?.rule || {}, null, 2),
  set: (value) => {
    if (!editing.value) return;
    try {
      editing.value.rule = JSON.parse(value || '{}');
      errorMessage.value = '';
    } catch {
      errorMessage.value = 'JSON 配置格式不正确。';
    }
  },
});

async function loadRules() {
  loading.value = true;
  errorMessage.value = '';
  try {
    const data = await fetchQualValidationRules();
    rules.value = data?.data ?? data ?? [];
  } catch (error) {
    errorMessage.value = error.message;
  } finally {
    loading.value = false;
  }
}

function editRule(rule) {
  editing.value = { ...rule, rule: { ...(rule.rule || {}) } };
  errorMessage.value = '';
}

async function saveRule() {
  if (!editing.value) return;
  saving.value = true;
  try {
    const saved = await saveQualValidationRule({
      code: editing.value.code,
      name: editing.value.name,
      ruleType: editing.value.ruleType,
      rule: editing.value.rule,
      enabled: editing.value.enabled,
    });
    const index = rules.value.findIndex((rule) => rule.id === saved.id);
    if (index >= 0) rules.value[index] = saved;
    editing.value = null;
  } catch (error) {
    errorMessage.value = error.message;
  } finally {
    saving.value = false;
  }
}

onMounted(loadRules);
</script>

<style scoped>
.primary-button {
  width: auto;
  min-height: 38px;
  padding: 8px 14px;
  border: 0;
  border-radius: 8px;
  background: #1f6feb;
  color: #fff;
  font-weight: 700;
}

.small-primary {
  min-width: 110px;
}

.ghost-button {
  min-height: 36px;
  padding: 7px 11px;
  border: 1px solid #cfd6e3;
  border-radius: 8px;
  background: #fff;
  color: #1f4f9f;
  font-weight: 700;
}

.empty-state {
  padding: 28px 12px;
  color: #64748b;
  text-align: center;
}

.rule-json {
  max-width: 220px;
  margin: 0;
  color: #475569;
  font-family: inherit;
  font-size: 11px;
  white-space: pre-wrap;
  word-break: break-word;
}

.rule-editor {
  display: grid;
  gap: 16px;
}

.rule-form-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr)) auto;
  gap: 12px;
}

.field {
  display: grid;
  gap: 7px;
  color: #263a37;
  font-size: 13px;
  font-weight: 700;
}

.field input,
.field textarea {
  width: 100%;
  border: 1px solid #d6dce6;
  border-radius: 7px;
  padding: 9px 10px;
  color: #17233a;
}

.field textarea {
  resize: vertical;
  font-family: Consolas, monospace;
}

.rule-enabled {
  align-self: end;
  min-height: 38px;
}

@media (max-width: 800px) {
  .rule-form-grid {
    grid-template-columns: 1fr;
  }

  .rule-enabled {
    align-self: start;
  }
}
</style>
