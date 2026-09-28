<template>
  <div class="page">
    <AppHeader title="Planning" />

    <main class="page-content">
      <div class="card">
        <div class="card__title">Connection</div>
        <dl class="facts">
          <dt>Signed in as</dt>
          <dd>{{ auth.displayName }}<span v-if="auth.designation" class="muted"> · {{ auth.designation }}</span></dd>

          <dt>Backend</dt>
          <dd>{{ backend }}</dd>

          <dt>API check</dt>
          <dd>
            <span v-if="check.state === 'loading'" class="muted">Checking…</span>
            <span v-else-if="check.state === 'ok'" class="badge badge-success">Connected as {{ check.user }}</span>
            <span v-else class="badge badge-danger">{{ check.error }}</span>
          </dd>
        </dl>
        <button class="btn btn-outline" :disabled="check.state === 'loading'" @click="runCheck">Check again</button>
      </div>

      <div class="card">
        <div class="empty-state">
          <div class="empty-state__title">No planning pages yet</div>
          <div class="empty-state__sub">
            Pages registered in <code>src/config/pages.js</code> appear in the menu.
            Copy <code>src/pages/_template/TemplatePage.vue</code> to start one.
          </div>
        </div>
      </div>
    </main>
  </div>
</template>

<script setup>
import { reactive, onMounted } from 'vue'
import AppHeader from '@/components/AppHeader.vue'
import { useAuthStore } from '@/stores/auth'
import { getCurrentUser } from '@/api/frappe'
import { backendLabel } from '@/config/backend'

const auth = useAuthStore()

const backend = backendLabel()

const check = reactive({ state: 'loading', user: '', error: '' })

async function runCheck() {
  check.state = 'loading'
  try {
    check.user = await getCurrentUser()
    check.state = 'ok'
  } catch (err) {
    check.error = err.message
    check.state = 'error'
  }
}

onMounted(runCheck)
</script>

<style scoped>
.facts { display: grid; grid-template-columns: max-content 1fr; gap: 8px 20px; margin-bottom: 16px; font-size: 14px; }
dt { color: var(--slate-500); }
.muted { color: var(--slate-500); }
code { background: var(--slate-100); padding: 1px 6px; border-radius: 4px; font-size: 12px; }
</style>
