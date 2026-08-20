<template>
  <svg
    class="app-icon"
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.8"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path v-if="name === 'home'" d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V10Z" />
    <path v-if="name === 'home'" d="M9 21v-7h6v7M8 10h.01M12 10h.01M16 10h.01" />
    <path v-if="name === 'book'" d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v17H6.5A2.5 2.5 0 0 0 4 22V5.5ZM4 5.5v14A2.5 2.5 0 0 1 6.5 17H20" />
    <path v-if="name === 'pen'" d="m4 20 4.5-1 10.9-10.9a2.1 2.1 0 0 0-3-3L5.5 16 4 20Z" />
    <path v-if="name === 'pen'" d="m14.5 6.5 3 3M4 20h4" />
    <path v-if="name === 'pulse'" d="M3 12h4l2-7 4 14 2-7h6" />
    <path v-if="name === 'chart'" d="M4 19V5M4 19h16M8 16v-4M12 16V8M16 16v-6M20 16V4" />
    <path v-if="name === 'file'" d="M6 3h8l4 4v14H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z" />
    <path v-if="name === 'file'" d="M14 3v5h5M8 13h8M8 17h5" />
    <path v-if="name === 'calendar'" d="M5 4h14a1 1 0 0 1 1 1v15H4V5a1 1 0 0 1 1-1ZM8 2v4M16 2v4M4 9h16" />
    <path v-if="name === 'search'" d="m20 20-4.5-4.5M10.5 18a7.5 7.5 0 1 1 0-15 7.5 7.5 0 0 1 0 15Z" />
    <path v-if="name === 'bell'" d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4" />
    <path v-if="name === 'arrow-right'" d="M5 12h14M13 6l6 6-6 6" />
    <path v-if="name === 'arrow-left'" d="M19 12H5M11 18l-6-6 6-6" />
    <path v-if="name === 'sparkles'" d="m12 3-1.2 4.8L6 9l4.8 1.2L12 15l1.2-4.8L18 9l-4.8-1.2L12 3ZM19 14l-.7 2.3L16 17l2.3.7L19 20l.7-2.3L22 17l-2.3-.7L19 14ZM5 14l-.6 1.9L2.5 16.5l1.9.6L5 19l.6-1.9 1.9-.6-1.9-.6L5 14Z" />
    <path v-if="name === 'send'" d="m22 2-7 20-4-9-9-4 20-7ZM22 2 11 13" />
    <path v-if="name === 'check'" d="m5 12 4 4L19 6" />
    <path v-if="name === 'clock'" d="M12 7v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
    <path v-if="name === 'more'" d="M5 12h.01M12 12h.01M19 12h.01" stroke-width="3" />
  </svg>
</template>

<script setup>
defineProps({
  name: { type: String, required: true },
  size: { type: [Number, String], default: 20 },
});
</script>
