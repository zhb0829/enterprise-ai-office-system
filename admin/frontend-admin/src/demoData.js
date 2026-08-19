export const demoTemplates = [
  { id: 1, name: 'news_release', category: '新闻稿', is_builtin: true, is_active: true },
  { id: 2, name: 'formal_announcement', category: '公告', is_builtin: true, is_active: true },
  { id: 3, name: 'meeting_brief', category: '会议纪要', is_builtin: true, is_active: true },
];

export const demoStyles = [
  { key: 'formal', name: '正式', description: '规范、庄重的公文语体，适用于公告和正式发布。' },
  { key: 'rigorous', name: '严谨', description: '措辞审慎，适用于合规、风险提示和声明。' },
  { key: 'neutral', name: '中性', description: '客观平实，适用于媒体通稿和业绩快报。' },
  { key: 'lively', name: '活泼', description: '轻快有感染力，适用于公众号和活动传播。' },
];

export const demoMaterials = [
  { id: 101, filename: '董事会决议摘要.docx', content_type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', status: '已入库', text_length: 1842 },
  { id: 102, filename: '活动日程.pdf', content_type: 'application/pdf', status: '已入库', text_length: 936 },
];

export const demoDraft = {
  id: 'demo-v2',
  title: '关于智能办公平台试运行的通知',
  template_name: 'formal_announcement',
  style: '正式',
  content: `各部门：\n\n为提升企业办公协同效率，规范公告、新闻稿及内部通知的起草流程，公司将于 2026 年 8 月 20 日起启动智能办公平台试运行。\n\n试运行期间，平台将提供要素采集、素材解析、草稿生成、事实核查、版本回溯及导出等功能。请各部门指定专人参与体验，并于试运行结束前反馈使用问题和改进建议。\n\n特此通知。`,
  version: 2,
  parent_id: 'demo-v1',
  root_id: 'demo-v1',
  status: '待审核',
  model: 'deepseek-chat',
  created_at: '2026-08-18T03:35:00Z',
  elements: [
    { id: 1, name: '上线时间', value: '2026 年 8 月 20 日', verified_status: '一致', source_ref: '活动日程.pdf' },
    { id: 2, name: '试运行范围', value: '要素采集、素材解析、草稿生成、事实核查、版本回溯及导出', verified_status: '一致', source_ref: '产品说明' },
  ],
  fact_checks: [
    { claim: '平台将于 2026 年 8 月 20 日启动试运行', status: '一致', basis: '与活动日程中的启动日期一致', suggestion: '' },
    { claim: '试运行覆盖全部部门', status: '无法核实', basis: '素材未提供明确部门名单', suggestion: '发布前确认参与部门范围。' },
  ],
};

export const demoSuggestions = [
  '建议补充试运行结束日期，便于各部门安排反馈节奏。',
  '建议明确反馈渠道，例如联系人、邮箱或工单入口。',
  '对外发布前需确认“全部部门”是否有正式依据。',
];

export const demoVersions = {
  id: 'demo-v1',
  version: 1,
  parent_id: null,
  title: '关于智能办公平台试运行的通知',
  status: '已生成',
  revision_instruction: '初始生成',
  created_at: '2026-08-18T03:20:00Z',
  children: [
    {
      id: 'demo-v2',
      version: 2,
      parent_id: 'demo-v1',
      title: '关于智能办公平台试运行的通知',
      status: '待审核',
      revision_instruction: '强化公文语气，增加反馈要求',
      created_at: '2026-08-18T03:35:00Z',
      children: [],
    },
  ],
};
