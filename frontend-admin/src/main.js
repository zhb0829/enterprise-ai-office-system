import { createApp } from 'vue';
import './styles.css';
import App from './App.vue';
import router from './router';

createApp(App).use(router).mount('#app');

// 401/登录失效时统一跳转登录页
window.addEventListener('eaos-unauthorized', () => {
  if (router.currentRoute.value.path !== '/admin/login') {
    router.push({ path: '/admin/login', query: { redirect: router.currentRoute.value.fullPath } });
  }
});
