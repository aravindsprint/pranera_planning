<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-brand">
        <svg class="login-logo" viewBox="0 0 64 64" aria-hidden="true">
          <rect width="64" height="64" rx="14" fill="#1e3a5f" />
          <g fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round">
            <path d="M16 22h20" /><path d="M24 32h24" /><path d="M16 42h14" />
          </g>
          <circle cx="46" cy="22" r="4" fill="#f5b942" />
        </svg>
        <h1>Planning</h1>
        <p>Sign in with your ERPNext account</p>
      </div>

      <form @submit.prevent="handleLogin">
        <div class="form-group">
          <label class="form-label" for="email">Email</label>
          <input id="email" v-model="email" type="email" class="form-input" autocomplete="username" required />
        </div>
        <div class="form-group">
          <label class="form-label" for="password">Password</label>
          <input id="password" v-model="password" type="password" class="form-input" autocomplete="current-password" required />
        </div>

        <div v-if="errorMsg" class="alert alert-error" role="alert">{{ errorMsg }}</div>

        <button type="submit" class="btn btn-primary btn-full" :disabled="loading">
          {{ loading ? 'Signing in…' : 'Sign in' }}
        </button>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { APP_BASE } from '@/config/app'

const route = useRoute()
const auth = useAuthStore()

const email = ref('')
const password = ref('')
const loading = ref(false)
const errorMsg = ref('')

async function handleLogin() {
  errorMsg.value = ''
  loading.value = true
  try {
    await auth.login(email.value, password.value)
    // Only follow same-app redirects.
    const wanted = typeof route.query.redirect === 'string' ? route.query.redirect : ''
    const dest = wanted.startsWith(APP_BASE + '/') ? wanted : `${APP_BASE}/home`
    // Full page load on purpose: re-runs main.js against the new session cookie.
    window.location.href = dest
  } catch (err) {
    errorMsg.value = err.message || 'Sign-in failed'
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 24px;
  background: var(--primary-soft);
}
.login-card {
  width: 100%; max-width: 380px; background: #fff; border-radius: var(--radius-lg);
  padding: 32px 24px; box-shadow: var(--shadow-lg);
}
.login-brand { text-align: center; margin-bottom: 24px; }
.login-logo { width: 56px; height: 56px; display: block; margin: 0 auto 12px; }
.login-brand h1 { font-size: 22px; font-weight: 700; }
.login-brand p { font-size: 14px; color: var(--slate-500); margin-top: 4px; }
</style>
