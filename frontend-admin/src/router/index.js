import { createRouter, createWebHistory } from 'vue-router';

const AdminLayout = () => import('../admin/Layout.vue');
const Templates = () => import('../admin/views/Templates.vue');
const Materials = () => import('../admin/views/Materials.vue');
const PolicyDocuments = () => import('../admin/views/PolicyDocuments.vue');

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
      ],
    },
  ],
});

export default router;
