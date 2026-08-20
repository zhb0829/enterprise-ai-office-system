<template>
  <div class="user-shell">
    <header class="topbar">
      <a class="skip-link" href="#workspace-main">跳到主要内容</a>
      <div class="brand-lockup" aria-label="企业 AI 办公助手">
        <span class="brand-mark" aria-hidden="true">AI</span>
        <div>
          <p class="eyebrow">企业 AI 办公助手</p>
          <h1>智能办公工作台</h1>
        </div>
      </div>
      <nav class="module-nav" aria-label="用户端功能导航">
        <router-link class="module-nav-item" exact-active-class="active" to="/workspace">公告撰写</router-link>
        <router-link class="module-nav-item" active-class="active" to="/workspace/policy">政策问答</router-link>
        <span class="module-nav-item disabled" aria-disabled="true">动态聚合</span>
        <span class="module-nav-item disabled" aria-disabled="true">舆情分析</span>
      </nav>
    </header>
    <main id="workspace-main" class="user-content" tabindex="-1">
      <router-view />
    </main>
  </div>
</template>

<script setup>
</script>
