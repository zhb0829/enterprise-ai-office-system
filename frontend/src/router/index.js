import { createRouter, createWebHistory } from 'vue-router';

const UserLayout = () => import('../workspace/UserLayout.vue');
const Workspace = () => import('../workspace/Workspace.vue');
const PolicyQa = () => import('../workspace/PolicyQa.vue');

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
      ],
    },
  ],
});

export default router;
