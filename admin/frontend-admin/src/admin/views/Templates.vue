<template>
  <div class="page-shell">
    <div class="page-head">
      <div>
        <h2>模板与文风管理</h2>
        <p class="page-sub">内置公文/新闻稿模板与文风，支持自定义新增</p>
      </div>
      <div class="head-actions">
        <button class="primary-button" type="button" @click="openCreate">新增模板</button>
        <button class="primary-button" type="button" @click="openStyleCreate">新增文风</button>
      </div>
    </div>

    <div class="grid two">
      <section class="panel">
        <div class="section-title"><h3>模板列表</h3></div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr><th>名称</th><th>分类</th><th>章节</th><th>类型</th><th>状态</th><th>操作</th></tr>
            </thead>
            <tbody>
              <tr v-for="t in templates" :key="t.id">
                <td class="strong">{{ templateTitle(t) }}</td>
                <td>{{ t.category }}</td>
                <td>{{ sectionCount(t) }} 节</td>
                <td>{{ t.is_builtin ? '内置' : '自定义' }}</td>
                <td>
                  <span :class="['check-badge', t.is_active ? 'ok' : 'warn']">
                    {{ t.is_active ? '启用' : '停用' }}
                  </span>
                </td>
                <td>
                  <button class="apply-button" type="button" @click="toggle(t)">{{ t.is_active ? '停用' : '启用' }}</button>
                </td>
              </tr>
              <tr v-if="!templates.length"><td colspan="6" class="empty-cell">暂无模板</td></tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="panel">
        <div class="section-title"><h3>文风与发布渠道</h3></div>
        <div class="style-list">
          <div v-for="style in styles" :key="style.key" class="style-card">
            <strong>{{ style.name }}</strong>
            <p>{{ style.description }}</p>
          </div>
        </div>
        <div class="section-title"><h3>渠道映射</h3></div>
        <div class="channel-list">
          <div v-for="(channels, name) in channelMap" :key="name" class="channel-row">
            <strong>{{ name }}</strong>
            <span v-for="ch in channels" :key="ch" class="check-badge ok">{{ ch }}</span>
          </div>
        </div>
      </section>
    </div>

    <!-- 新增模板弹窗 -->
    <div v-if="showCreate" class="modal-mask" @click.self="showCreate = false">
      <div class="modal">
        <div class="modal-head">
          <h3>新增模板</h3>
          <button class="icon-button danger" type="button" @click="showCreate = false">×</button>
        </div>
        <label class="field"><span>标识（英文，唯一）</span><input v-model="createForm.name" placeholder="如 my_announcement" /></label>
        <label class="field"><span>中文标题</span><input v-model="createForm.title" placeholder="如 我的公告" /></label>
        <label class="field"><span>分类</span><input v-model="createForm.category" placeholder="如 公告 / 新闻稿" /></label>
        <label class="field">
          <span>模板结构（JSON，含 sections 与 placeholders）</span>
          <textarea v-model="createForm.schema" rows="10" spellcheck="false" placeholder='{"name":"my_announcement","title":"我的公告","category":"公告","output_format":"markdown","tone_guidelines":"...","sections":[{"key":"headline","name":"标题","required":true,"hint":"..."}],"placeholders":[{"key":"event","name":"事项","required":true,"source":"eventDesc","hint":"..."}]}'></textarea>
        </label>
        <label class="field check-inline">
          <input v-model="createForm.is_active" type="checkbox" /> 启用
        </label>
        <p v-if="createError" class="error-text">{{ createError }}</p>
        <div class="modal-actions">
          <button class="ghost-button" type="button" @click="showCreate = false">取消</button>
          <button class="primary-button" type="button" :disabled="saving" @click="saveTemplate">
            {{ saving ? '保存中...' : '保存' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 新增文风弹窗 -->
    <div v-if="showStyle" class="modal-mask" @click.self="showStyle = false">
      <div class="modal">
        <div class="modal-head">
          <h3>新增文风</h3>
          <button class="icon-button danger" type="button" @click="showStyle = false">×</button>
        </div>
        <label class="field"><span>标识（英文，唯一）</span><input v-model="styleForm.key" placeholder="如 casual" /></label>
        <label class="field"><span>名称</span><input v-model="styleForm.name" placeholder="如 随性" /></label>
        <label class="field"><span>描述</span><input v-model="styleForm.description" placeholder="适用场景说明" /></label>
        <label class="field"><span>语体要求（tone_guidelines）</span><textarea v-model="styleForm.tone_guidelines" rows="3" placeholder="生成该文风时的语气/句式/用词约束"></textarea></label>
        <label class="field"><span>句式风格</span><input v-model="styleForm.sentence_style" placeholder="如 短句为主，口语化" /></label>
        <label class="field"><span>段落长度</span><input v-model="styleForm.paragraph_length" placeholder="如 短（1-3 句）" /></label>
        <label class="field"><span>标题风格</span><input v-model="styleForm.title_style" placeholder="如 吸睛但不过度" /></label>
        <p v-if="styleError" class="error-text">{{ styleError }}</p>
        <div class="modal-actions">
          <button class="ghost-button" type="button" @click="showStyle = false">取消</button>
          <button class="primary-button" type="button" :disabled="savingStyle" @click="saveStyle">
            {{ savingStyle ? '保存中...' : '保存' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { createTemplate, fetchStyles, fetchTemplates, saveStyles, toggleTemplate } from '../../api';
import { demoTemplates, demoStyles } from '../../demoData';

const templates = ref(demoTemplates);
const styles = ref(demoStyles);
const channelStyleMap = ref({});

const showCreate = ref(false);
const saving = ref(false);
const createError = ref('');
const createForm = reactive({ name: '', title: '', category: '', schema: '', is_active: true });

const showStyle = ref(false);
const savingStyle = ref(false);
const styleError = ref('');
const styleForm = reactive({
  key: '', name: '', description: '', tone_guidelines: '',
  sentence_style: '', paragraph_length: '', title_style: '',
});

const channelMap = computed(() => channelStyleMap.value);

function sectionCount(t) {
  return t.schema?.sections?.length ?? 0;
}

function templateTitle(t) {
  return t.title || t.schema?.title || t.name;
}

function openCreate() {
  createForm.name = '';
  createForm.title = '';
  createForm.category = '';
  createForm.schema = '';
  createForm.is_active = true;
  createError.value = '';
  showCreate.value = true;
}

async function saveTemplate() {
  createError.value = '';
  if (!createForm.name.trim() || !createForm.schema.trim()) {
    createError.value = '标识与模板结构必填。';
    return;
  }
  let schemaObj;
  try {
    schemaObj = JSON.parse(createForm.schema);
  } catch (e) {
    createError.value = `JSON 解析失败：${e.message}`;
    return;
  }
  if (createForm.title.trim() && !schemaObj.title) schemaObj.title = createForm.title.trim();
  if (createForm.category.trim() && !schemaObj.category) schemaObj.category = createForm.category.trim();
  saving.value = true;
  try {
    await createTemplate({
      name: createForm.name.trim(),
      category: schemaObj.category || createForm.category.trim() || '自定义',
      template_schema: schemaObj,
      is_active: createForm.is_active,
    });
    showCreate.value = false;
    await loadTemplates();
  } catch (error) {
    createError.value = `保存失败：${error.message}`;
  } finally {
    saving.value = false;
  }
}

function openStyleCreate() {
  styleForm.key = '';
  styleForm.name = '';
  styleForm.description = '';
  styleForm.tone_guidelines = '';
  styleForm.sentence_style = '';
  styleForm.paragraph_length = '';
  styleForm.title_style = '';
  styleError.value = '';
  showStyle.value = true;
}

async function saveStyle() {
  styleError.value = '';
  if (!styleForm.key.trim() || !styleForm.name.trim()) {
    styleError.value = '标识与名称必填。';
    return;
  }
  if (styles.value.some((s) => s.key === styleForm.key.trim())) {
    styleError.value = '该文风标识已存在。';
    return;
  }
  const newStyle = {
    key: styleForm.key.trim(),
    name: styleForm.name.trim(),
    description: styleForm.description.trim(),
    tone_guidelines: styleForm.tone_guidelines.trim(),
    sentence_style: styleForm.sentence_style.trim(),
    paragraph_length: styleForm.paragraph_length.trim(),
    title_style: styleForm.title_style.trim(),
  };
  savingStyle.value = true;
  try {
    const payload = {
      styles: [...styles.value, newStyle],
      channel_style_map: channelStyleMap.value,
    };
    await saveStyles(payload);
    styles.value = payload.styles;
    showStyle.value = false;
  } catch (error) {
    styleError.value = `保存失败：${error.message}`;
  } finally {
    savingStyle.value = false;
  }
}

async function toggle(t) {
  try {
    await toggleTemplate(t.id);
    await loadTemplates();
  } catch (error) {
    alert(`操作失败：${error.message}`);
  }
}

async function loadTemplates() {
  try {
    const [rows, stylePayload] = await Promise.all([fetchTemplates(), fetchStyles()]);
    templates.value = rows.length ? rows : demoTemplates;
    if (stylePayload?.styles?.length) {
      styles.value = stylePayload.styles;
      channelStyleMap.value = stylePayload.channel_style_map || {};
    } else {
      styles.value = demoStyles;
      channelStyleMap.value = {};
    }
  } catch {
    // 保留演示数据
  }
}

onMounted(loadTemplates);
</script>