<template>
  <div class="msg-page">
    <div>
      <i class="pi pi-lock msg-icon"></i>
      <h1>You don't have access to Planning</h1>
      <p>Ask your ERPNext administrator to give your account one of these roles: {{ ALLOWED_ROLES.join(', ') }}.</p>
      <a href="/app" class="btn btn-outline">Back to ERPNext</a>
    </div>
  </div>
</template>

<script setup>
import { ALLOWED_ROLES } from '@/config/app'
</script>

<style scoped>
.msg-page { min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 24px; text-align: center; }
.msg-icon { font-size: 40px; color: var(--slate-400); margin-bottom: 14px; }
h1 { font-size: 20px; font-weight: 700; margin-bottom: 8px; }
p { color: var(--slate-500); margin: 0 auto 20px; max-width: 46ch; font-size: 14px; }
</style>
