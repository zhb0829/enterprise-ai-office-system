import { createRouter, createWebHistory } from 'vue-router';

const UserLayout = () => import('../workspace/UserLayout.vue');
const Home = () => import('../workspace/Home.vue');
const FeaturePage = () => import('../workspace/FeaturePage.vue');
const NewsDrafting = () => import('../workspace/NewsDrafting.vue');

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/workspace' },
    {
      path: '/workspace',
      component: UserLayout,
      children: [
        { path: '', name: 'workspace', component: Home, meta: { title: '工作台首页' } },
        { path: 'feature/news-drafting', name: 'news-drafting', component: NewsDrafting, meta: { title: '公告新闻撰写' } },
        { path: 'feature/:slug', name: 'feature', component: FeaturePage, meta: { title: '智能工作空间' } },
      ],
    },
  ],
});

export default router;
