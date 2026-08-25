import { createRouter, createWebHistory } from 'vue-router';

const UserLayout = () => import('../workspace/UserLayout.vue');
const Workspace = () => import('../workspace/Workspace.vue');
const PolicyQa = () => import('../workspace/PolicyQa.vue');
const Intelligence = () => import('../workspace/Intelligence.vue');
const Opinion = () => import('../workspace/Opinion.vue');
const OpinionAlerts = () => import('../workspace/OpinionAlerts.vue');
const OpinionReports = () => import('../workspace/OpinionReports.vue');

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
        { path: '', name: 'workspace', component: Workspace, meta: { title: '公告/新闻稿撰写' } },
        { path: 'policy', name: 'policy', component: PolicyQa, meta: { title: '行业政策法规智能问答' } },
        { path: 'intelligence', name: 'intelligence', component: Intelligence, meta: { title: '行业情报' } },
        { path: 'opinion', name: 'opinion', component: Opinion, meta: { title: '舆情分析' } },
        { path: 'opinion-alerts', name: 'opinion-alerts', component: OpinionAlerts, meta: { title: '舆情告警' } },
        { path: 'opinion-reports', name: 'opinion-reports', component: OpinionReports, meta: { title: '舆情报告' } },
      ],
    },
  ],
});

export default router;
