import { createRouter, createWebHistory } from 'vue-router';

const UserLayout = () => import('../workspace/UserLayout.vue');
const Workspace = () => import('../workspace/Workspace.vue');

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
      ],
    },
  ],
});

export default router;