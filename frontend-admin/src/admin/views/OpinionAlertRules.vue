<template>
  <div class="page-shell opinion-rules-page">
    <div class="page-head">
      <div>
        <h2>告警规则</h2>
        <p class="page-sub">为监控任务配置告警条件（数量/比例/增长率/来源/传播速度），命中即触发并合并告警事件。</p>
      </div>
      <div class="head-actions">
        <button class="apply-button head-button" type="button" @click="loadAll">刷新数据</button>
      </div>
    </div>

    <section class="panel">
      <div class="panel-head"><h3>新增规则</h3><p class="page-sub">选择监控任务并配置触发条件。</p></div>
      <form class="rule-form" @submit.prevent="createRule">
        <select v-model="form.monitorId" required aria-label="监控任务">
          <option value="" disabled>选择监控任务</option>
          <option v-for="monitor in monitors" :key="monitor.id" :value="monitor.id">{{ monitor.name }}</option>
        </select>
        <input v-model="form.name" required placeholder="规则名称" aria-label="规则名称" />
        <select v-model="form.riskLevel" aria-label="风险等级"><option value="关注">关注</option><option value="预警">预警</option><option value="危机">危机</option></select>
        <input v-model.number="trigger.negativeCount" type="number" min="0" placeholder="负面数量≥" aria-label="负面数量" />
        <input v-model.number="trigger.negativeRatio" type="number" min="0" max="1" step="0.05" placeholder="负面比例≥" aria-label="负面比例" />
        <input v-model.number="trigger.growthRate" type="number" min="0" step="0.1" placeholder="增长率≥" aria-label="增长率" />
        <input v-model.number="trigger.sourceCount" type="number" min="0" placeholder="来源数≥" aria-label="来源数" />
        <input v-model.number="trigger.spreadSpeed" type="number" min="0" placeholder="传播速度≥" aria-label="传播速度" />
        <input v-model.number="trigger.windowHours" type="number" min="1" placeholder="窗口(小时)" aria-label="时间窗口" />
        <input v-model.number="form.cooldownMinutes" type="number" min="1" placeholder="冷却(分钟)" aria-label="冷却时间" />
        <button class="apply-button primary-outline" type="submit" :disabled="saving">{{ saving ? '保存中...' : '添加规则' }}</button>
      </form>
      <p v-if="message" class="page-sub feedback">{{ message }}</p>
    </section>

    <section class="panel">
      <div class="panel-head"><h3>规则列表</h3><span class="count">{{ rules.length }} 条</span></div>
      <div class="table-wrap"><table>
        <thead><tr><th>规则</th><th>监控任务</th><th>等级</th><th>触发条件</th><th>冷却</th><th>状态</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="rule in rules" :key="rule.id">
            <td class="strong">{{ rule.name }}</td>
            <td>{{ monitorName(rule.monitorId) }}</td>
            <td><span :class="['check-badge', riskClass(rule.riskLevel)]">{{ rule.riskLevel }}</span></td>
            <td><small class="table-note">{{ triggerLabel(rule.trigger) }}</small></td>
            <td>{{ rule.cooldownMinutes }} 分钟</td>
            <td><span :class="['check-badge', rule.status === 'enabled' ? 'ok' : 'warn']">{{ rule.status }}</span></td>
            <td class="row-actions">
              <button class="apply-button" type="button" @click="toggleRule(rule)">{{ rule.status === 'enabled' ? '停用' : '启用' }}</button>
              <button class="apply-button" type="button" @click="removeRule(rule)">删除</button>
            </td>
          </tr>
          <tr v-if="!rules.length"><td colspan="7" class="empty-cell">暂无告警规则</td></tr>
        </tbody>
      </table></div>
    </section>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue';
import { createOpinionAlertRule, deleteOpinionAlertRule, fetchOpinionAlertRules, fetchOpinionMonitors, toggleOpinionAlertRule } from '../../api';

const rules = ref([]);
const monitors = ref([]);
const saving = ref(false);
const message = ref('');
const trigger = reactive({ negativeCount: 3, negativeRatio: 0.3, growthRate: 0.5, sourceCount: 2, spreadSpeed: 3, windowHours: 24 });
const form = reactive({ monitorId: '', name: '', riskLevel: '关注', cooldownMinutes: 60 });

function formatTime() { return ''; }
const riskClass = (value) => ({ 危机: 'danger', 预警: 'warn', 关注: 'ok' }[value] || 'warn');
function monitorName(id) { return monitors.value.find((m) => m.id === id)?.name || id; }
function triggerLabel(value) {
  if (!value) return '-';
  const parts = [];
  if (value.negativeCount) parts.push(`负面≥${value.negativeCount}`);
  if (value.negativeRatio) parts.push(`比例≥${value.negativeRatio}`);
  if (value.growthRate) parts.push(`增速≥${value.growthRate}`);
  if (value.sourceCount) parts.push(`来源≥${value.sourceCount}`);
  if (value.spreadSpeed) parts.push(`传播≥${value.spreadSpeed}`);
  if (value.windowHours) parts.push(`${value.windowHours}h`);
  return parts.join('，') || '-';
}
async function loadAll() { try { const [r, m] = await Promise.all([fetchOpinionAlertRules(), fetchOpinionMonitors()]); rules.value = r; monitors.value = m; } catch (e) { message.value = `加载失败：${e.message}`; } }
async function createRule() {
  saving.value = true; message.value = '';
  try {
    const cleaned = {};
    Object.entries(trigger).forEach(([key, value]) => { if (value !== null && value !== '' && value !== undefined) cleaned[key] = value; });
    await createOpinionAlertRule({ ...form, monitorId: Number(form.monitorId), trigger: cleaned });
    Object.assign(form, { name: '', monitorId: '' });
    message.value = '告警规则已添加。';
    await loadAll();
  } catch (e) { message.value = `保存失败：${e.message}`; } finally { saving.value = false; }
}
async function toggleRule(rule) { try { await toggleOpinionAlertRule(rule.id); await loadAll(); } catch (e) { message.value = `状态更新失败：${e.message}`; } }
async function removeRule(rule) { if (!window.confirm(`确定删除规则「${rule.name}」？`)) return; try { await deleteOpinionAlertRule(rule.id); await loadAll(); } catch (e) { message.value = `删除失败：${e.message}`; } }
onMounted(loadAll);
</script>

<style scoped>
.opinion-rules-page { max-width: 1280px; }
.rule-form { display: grid; grid-template-columns: 1.4fr 1.2fr 100px repeat(5, 90px) 110px auto; gap: 8px; align-items: center; padding: 14px; }
.rule-form input, .rule-form select { min-height: 36px; font-size: 12px; }
.primary-outline { min-height: 36px; white-space: nowrap; }
.feedback { color: #1d4ed8; }
.table-note { color: #64748b; font-size: 11px; }
@media (max-width: 1100px) { .rule-form { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 700px) { .page-head { flex-direction: column; align-items: flex-start; } .head-button { width: auto; } .rule-form { grid-template-columns: 1fr; } }
</style>