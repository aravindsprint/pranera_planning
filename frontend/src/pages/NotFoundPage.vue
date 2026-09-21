<template>
  <div class="msg-page">
    <div>
      <h1>Page not found</h1>
      <p>There is no page at <code>{{ $route.fullPath }}</code>.</p>
      <router-link :to="`${APP_BASE}/home`" class="btn btn-primary">Go to Home</router-link>
    </div>
  </div>
</template>

<script setup>
import { APP_BASE } from '@/config/app'
</script>

<style scoped>
.msg-page { min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 24px; text-align: center; }
h1 { font-size: 20px; font-weight: 700; margin-bottom: 8px; }
p { color: var(--slate-500); margin-bottom: 20px; font-size: 14px; }
code { background: var(--slate-100); padding: 1px 6px; border-radius: 4px; }
</style>
