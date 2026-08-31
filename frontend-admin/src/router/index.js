import { createRouter, createWebHistory } from 'vue-router';
import { getToken } from '../api';

const AdminLayout = () => import('../admin/Layout.vue');
const Templates = () => import('../admin/views/Templates.vue');
const Materials = () => import('../admin/views/Materials.vue');
const PolicyDocuments = () => import('../admin/views/PolicyDocuments.vue');
const QualificationRules = () => import('../admin/views/QualificationRules.vue');
const QualificationGuides = () => import('../admin/views/QualificationGuides.vue');
const QualificationTasks = () => import('../admin/views/QualificationTasks.vue');
const Intelligence = () => import('../admin/views/Intelligence.vue');
const OpinionSources = () => import('../admin/views/OpinionSources.vue');
const OpinionAlertRules = () => import('../admin/views/OpinionAlertRules.vue');
const OpinionCases = () => import('../admin/views/OpinionCases.vue');
const Meetings = () => import('../admin/views/Meetings.vue');
const Login = () => import('../admin/Login.vue');
const ChangePassword = () => import('../admin/ChangePassword.vue');
const Users = () => import('../admin/views/Users.vue');
const NotificationChannels = () => import('../admin/views/NotificationChannels.vue');

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      redirect: '/admin/templates',
    },
    {
      path: '/admin/login',
      name: 'admin-login',
      component: Login,
      meta: { title: '登录', public: true },
    },
    {
      path: '/admin/change-password',
      name: 'admin-change-password',
      component: ChangePassword,
      meta: { title: '修改密码' },
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
        { path: 'qualification-tasks', name: 'admin-qualification-tasks', component: QualificationTasks, meta: { title: '资质编制任务', group: '知识库管理' } },
        { path: 'intelligence', name: 'admin-intelligence', component: Intelligence, meta: { title: '行业与竞品情报', group: '情报聚合' } },
        { path: 'opinion-sources', name: 'admin-opinion-sources', component: OpinionSources, meta: { title: '舆情采集源治理', group: '舆情分析' } },
        { path: 'opinion-alert-rules', name: 'admin-opinion-alert-rules', component: OpinionAlertRules, meta: { title: '告警规则', group: '舆情分析' } },
        { path: 'opinion-cases', name: 'admin-opinion-cases', component: OpinionCases, meta: { title: '历史应对案例', group: '舆情分析' } },
        { path: 'meetings', name: 'admin-meetings', component: Meetings, meta: { title: '会议公开信息整理', group: '会议知识' } },
        { path: 'users', name: 'admin-users', component: Users, meta: { title: '用户管理', group: '系统管理' } },
        { path: 'notification-channels', name: 'admin-notification-channels', component: NotificationChannels, meta: { title: '通知渠道', group: '系统管理' } },
      ],
    },
  ],
});

// 路由守卫（Q10）：未登录访问任何页面跳登录页
router.beforeEach((to) => {
  if (to.meta.public) {
    return getToken() ? '/admin/templates' : true;
  }
  if (!getToken()) {
    return { path: '/admin/login', query: { redirect: to.fullPath } };
  }
  return true;
});

export default router;
