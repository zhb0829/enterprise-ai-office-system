import { createRouter, createWebHistory } from 'vue-router';

const UserLayout = () => import('../workspace/UserLayout.vue');
const Home = () => import('../workspace/Home.vue');
const Workspace = () => import('../workspace/Workspace.vue');
const PolicyQa = () => import('../workspace/PolicyQa.vue');
const Qualification = () => import('../workspace/Qualification.vue');
const Intelligence = () => import('../workspace/Intelligence.vue');
const OpinionHub = () => import('../workspace/OpinionHub.vue');
const Meeting = () => import('../workspace/Meeting.vue');

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      redirect: '/workspace',
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

export default router;
