import { createRouter, createWebHistory } from 'vue-router';

const AdminLayout = () => import('../admin/Layout.vue');
const Templates = () => import('../admin/views/Templates.vue');
const Materials = () => import('../admin/views/Materials.vue');
const PolicyDocuments = () => import('../admin/views/PolicyDocuments.vue');
const QualificationRules = () => import('../admin/views/QualificationRules.vue');
const QualificationGuides = () => import('../admin/views/QualificationGuides.vue');
const Intelligence = () => import('../admin/views/Intelligence.vue');
const OpinionSources = () => import('../admin/views/OpinionSources.vue');
const OpinionAlertRules = () => import('../admin/views/OpinionAlertRules.vue');
const OpinionCases = () => import('../admin/views/OpinionCases.vue');

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      redirect: '/admin/templates',
    },
    {
      path: '/admin',
      component: AdminLayout,
      redirect: '/admin/templates',
      children: [
        { path: 'templates', name: 'admin-templates', component: Templates, meta: { title: '模板管理', group: '内容管理' } },
        { path: 'materials', name: 'admin-materials', component: Materials, meta: { title: '素材管理', group: '内容管理' } },
        { path: 'policy-documents', name: 'admin-policy-documents', component: PolicyDocuments, meta: { title: '政策法规知识库', group: '知识库管理' } },
        { path: 'qualification-rules', name: 'admin-qualification-rules', component: QualificationRules, meta: { title: '资质编制校验规则', group: '知识库管理' } },
        { path: 'qualification-guides', name: 'admin-qualification-guides', component: QualificationGuides, meta: { title: '资质指南库', group: '知识库管理' } },
        { path: 'intelligence', name: 'admin-intelligence', component: Intelligence, meta: { title: '行业与竞品情报', group: '情报聚合' } },
        { path: 'opinion-sources', name: 'admin-opinion-sources', component: OpinionSources, meta: { title: '舆情采集源治理', group: '舆情分析' } },
        { path: 'opinion-alert-rules', name: 'admin-opinion-alert-rules', component: OpinionAlertRules, meta: { title: '告警规则', group: '舆情分析' } },
        { path: 'opinion-cases', name: 'admin-opinion-cases', component: OpinionCases, meta: { title: '历史应对案例', group: '舆情分析' } },
      ],
    },
  ],
});

export default router;
