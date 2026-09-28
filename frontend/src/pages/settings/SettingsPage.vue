<template>
  <div class="page">
    <AppHeader title="Settings" />

    <main class="page-content">
      <div v-if="isDev" class="card">
        <div class="card__title">Backend</div>
        <p class="lead">
          Where this dev server sends its requests. Pick <b>Local bench</b> to test code that isn't
          deployed to erp.pranera.in yet, without touching live data.
        </p>
        <BackendSwitch />
        <p class="note">
          Switching signs you out of the current backend and takes you to the login page — the two
          sites have separate users and sessions. Takes effect immediately; no restart of <code>yarn dev</code>.
        </p>
      </div>

      <div class="card">
        <div class="card__title">Connection</div>
        <dl class="facts">
          <dt>Backend</dt>
          <dd>
            {{ backendLabel() }}
            <span v-if="isDev" class="badge" :class="mode === 'live' ? 'badge-danger' : 'badge-success'">{{ mode === 'live' ? 'LIVE DATA' : 'LOCAL' }}</span>
          </dd>

          <dt>Reachable</dt>
          <dd>
            <span v-if="busy" class="muted">Checking…</span>
            <span v-else-if="reach.ok" class="badge badge-success">Yes · {{ reach.ms }} ms</span>
            <span v-else class="badge badge-danger">{{ reach.error }}</span>
          </dd>

          <template v-if="!busy && reach.ok">
            <dt>Signed in as</dt>
            <dd>{{ info?.user || auth.frappeUser }}</dd>
          </template>

          <template v-if="!busy && info">
            <dt>Site</dt><dd>{{ info.site }}</dd>
            <dt>pranera_planning</dt><dd>v{{ info.app_version }}</dd>
            <dt>Project Stock Reservation</dt>
            <dd><span class="badge" :class="info.reservation_doctype ? 'badge-success' : 'badge-danger'">{{ info.reservation_doctype ? 'Installed' : 'Not installed — run bench migrate' }}</span></dd>
            <dt>Stock Entry check</dt>
            <dd><span class="badge" :class="info.stock_entry_check_registered ? 'badge-success' : 'badge-danger'">{{ info.stock_entry_check_registered ? 'Registered' : 'Not registered' }}</span></dd>
            <dt>Enforcement</dt>
            <dd><span class="badge" :class="info.enforcement_enabled ? 'badge-success' : 'badge-warning'">{{ info.enforcement_enabled ? 'On' : 'Off (site_config kill switch)' }}</span></dd>
          </template>
        </dl>

        <div v-if="!busy && reach.ok && !info" class="alert alert-warning">
          pranera_planning is not deployed on this backend, so the reservation pages will not work here.
          <template v-if="isDev && mode === 'live'"> Switch to <b>Local bench</b> to test them.</template>
          <div v-if="infoError" class="detail">{{ infoError }}</div>
        </div>

        <button class="btn btn-outline" :disabled="busy" @click="check">Check again</button>
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import AppHeader from '@/components/AppHeader.vue'
import BackendSwitch from '@/components/BackendSwitch.vue'
import { useAuthStore } from '@/stores/auth'
import { callMessage } from '@/api/frappe'
import { isDev, currentBackend, backendLabel } from '@/config/backend'

const auth = useAuthStore()
const mode = currentBackend()

const busy = ref(true)
const reach = reactive({ ok: false, ms: 0, error: '' })
const info = ref(null)
const infoError = ref('')

async function check() {
  busy.value = true
  info.value = null
  infoError.value = ''
  reach.ok = false

  // 1. Is the backend there at all? `ping` needs no login, so this also works when the
  //    session is the problem.
  const t0 = performance.now()
  try {
    const r = await fetch('/api/method/ping', { credentials: 'include' })
    const data = await r.json().catch(() => null)
    if (!r.ok) {
      reach.error = data?.exception?.split(': ').slice(1).join(': ') || `HTTP ${r.status}`
    } else if (data?.message !== 'pong') {
      reach.error = 'Answered, but not like a Frappe site — check the proxy target'
    } else {
      reach.ok = true
      reach.ms = Math.round(performance.now() - t0)
    }
  } catch (e) {
    reach.error = e.message || 'Network error'
  }

  // 2. Is this app actually deployed there?
  if (reach.ok) {
    try {
      info.value = await callMessage('pranera_planning.api.common.get_app_info')
    } catch (e) {
      infoError.value = e.message
    }
  }
  busy.value = false
}

onMounted(check)
</script>

<style scoped>
.lead { font-size: 14px; color: var(--slate-700); margin-bottom: 14px; line-height: 1.5; }
.note { font-size: 12px; color: var(--slate-500); margin-top: 12px; line-height: 1.5; }
.facts { display: grid; grid-template-columns: max-content 1fr; gap: 8px 20px; margin-bottom: 16px; font-size: 14px; align-items: center; }
dt { color: var(--slate-500); }
.muted { color: var(--slate-500); }
.detail { font-weight: 400; font-size: 12px; margin-top: 6px; opacity: 0.85; }
code { background: var(--slate-100); padding: 1px 6px; border-radius: 4px; font-size: 12px; }
.badge { margin-left: 6px; }
dd .badge:first-child { margin-left: 0; }
</style>
