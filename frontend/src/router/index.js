import { createRouter, createWebHistory } from 'vue-router';
import { getToken } from '../api';

const UserLayout = () => import('../workspace/UserLayout.vue');
const Home = () => import('../workspace/Home.vue');
const Workspace = () => import('../workspace/Workspace.vue');
const PolicyQa = () => import('../workspace/PolicyQa.vue');
const Qualification = () => import('../workspace/Qualification.vue');
const Intelligence = () => import('../workspace/Intelligence.vue');
const OpinionHub = () => import('../workspace/OpinionHub.vue');
const Meeting = () => import('../workspace/Meeting.vue');
const Login = () => import('../workspace/Login.vue');
const ChangePassword = () => import('../workspace/ChangePassword.vue');

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      redirect: '/workspace',
    },
    {
      path: '/login',
      name: 'login',
      component: Login,
      meta: { title: '登录', public: true },
    },
    {
      path: '/change-password',
      name: 'change-password',
      component: ChangePassword,
      meta: { title: '修改密码' },
    },
    {
      path: '/workspace',
      component: UserLayout,
      children: [
        { path: '', name: 'home', component: Home, meta: { title: '工作台' } },
        { path: 'compose', name: 'workspace', component: Workspace, meta: { title: '公告/新闻稿撰写' } },
        { path: 'policy', name: 'policy', component: PolicyQa, meta: { title: '行业政策法规智能问答' } },
        { path: 'qualification', name: 'qualification', component: Qualification, meta: { title: '资质与服务指南智能编制' } },
        { path: 'intelligence', name: 'intelligence', component: Intelligence, meta: { title: '行业情报' } },
        { path: 'opinion', name: 'opinion', component: OpinionHub, meta: { title: '舆情中心' } },
        { path: 'opinion-alerts', name: 'opinion-alerts', component: OpinionHub, meta: { title: '舆情中心' } },
        { path: 'opinion-reports', name: 'opinion-reports', component: OpinionHub, meta: { title: '舆情中心' } },
        { path: 'meeting', name: 'meeting', component: Meeting, meta: { title: '会议公开信息整理' } },
      ],
    },
  ],
});

// 路由守卫（Q10）：未登录访问任何页面跳登录页
router.beforeEach((to) => {
  if (to.meta.public) {
    return getToken() ? '/workspace' : true;
  }
  if (!getToken()) {
    return { path: '/login', query: { redirect: to.fullPath } };
  }
  return true;
});

export default router;
