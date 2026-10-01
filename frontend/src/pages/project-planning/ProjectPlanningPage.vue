<template>
  <div class="page">
    <AppHeader subtitle="See a project's order or programme, plan it, and hold its stock — in one place" />

    <section class="project-bar">
      <div class="bar-row">
        <template v-if="!isNew">
          <div class="field">
            <label class="form-label" for="pp-project">Project</label>
            <LinkField id="pp-project" v-model="picked" doctype="Project" :search-fn="searchProjects"
                       placeholder="e.g. 26PTIN1710" empty-label="No open Production or Purchase project found" @change="choose" />
          </div>
          <div v-if="info" class="badges">
            <span class="badge badge-info">{{ info.project_type || 'Type not set' }}</span>
            <span class="badge" :class="info.order_type === 'Made to stock' ? 'badge-info' : 'badge-dark'">{{ info.order_type }}</span>
            <span class="sub">
              <template v-if="info.customer">{{ info.customer }} · </template>
              <template v-if="info.sales_order">{{ info.sales_order }} · </template>
              <template v-if="info.delivery_date">{{ info.order_type === 'Made to stock' ? 'needed by' : 'delivery by' }} {{ info.delivery_date }}</template>
            </span>
          </div>
        </template>
        <h1 v-else class="h1">New plan</h1>
        <div class="bar-actions">
          <a class="btn btn-outline" :href="`${APP_BASE}/reorder-report`">Re-order report</a>
          <button v-if="!isNew" class="btn btn-primary" @click="openNew">+ New plan</button>
          <button v-else-if="project" class="btn btn-outline" @click="go('overview')">Back to {{ project }}</button>
        </div>
      </div>
      <nav v-if="!isNew && project" class="tabs" aria-label="Project tabs">
        <button v-for="t in TABS" :key="t.key" class="tab" :class="{ on: tab === t.key }" :aria-current="tab === t.key ? 'page' : undefined"
                @click="go(t.key)">{{ t.label }}</button>
      </nav>
    </section>

    <main class="page-content">
      <PlanPage v-if="isNew" embedded :prefill="prefill" @created="onCreated" />

      <div v-else-if="!project" class="card">
        <div class="empty-state">
          <div class="empty-state__title">Choose a project</div>
          <div class="empty-state__sub">Its order or stock programme, its plan, and the stock held for it — or start a <a href="#" @click.prevent="openNew">new made-to-stock plan</a>.</div>
        </div>
      </div>

      <template v-else>
        <OverviewTab v-if="tab === 'overview'" :project="project" @go="go" @loaded="(p) => (info = p)" />
        <PlanPage v-else-if="tab === 'plan'" embedded :for-project="project" @created="onCreated" />
        <ProjectStockReservationPage v-else embedded :for-project="project" @open-project="(p) => choose(p, 'stock')" />
      </template>
    </main>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppHeader from '@/components/AppHeader.vue'
import LinkField from '@/components/LinkField.vue'
import { callMessage } from '@/api/frappe'
import { APP_BASE } from '@/config/app'
import OverviewTab from './OverviewTab.vue'
import PlanPage from '@/pages/plan/PlanPage.vue'
import ProjectStockReservationPage from '@/pages/project-stock-reservation/ProjectStockReservationPage.vue'

const TABS = [
  { key: 'overview', label: 'Overview' },
  { key: 'plan', label: 'Plan' },
  { key: 'stock', label: 'Stock & reservations' },
]
const route = useRoute()
const router = useRouter()

// The URL is the state: ?project=…&tab=overview|plan|stock, or ?new=1 (with item/qty/mode from the re-order report).
const project = computed(() => (typeof route.query.project === 'string' ? route.query.project : ''))
const tab = computed(() => (TABS.some((t) => t.key === route.query.tab) ? route.query.tab : 'overview'))
const isNew = computed(() => route.query.new === '1')
const prefill = computed(() => (route.query.item ? { item: route.query.item, qty: route.query.qty, mode: route.query.mode, order_type: route.query.order_type } : null))
const picked = ref(project.value)
const info = ref(null)

watch(project, (p) => { picked.value = p; info.value = null })

async function searchProjects(txt) {
  return await callMessage('pranera_planning.api.plan.search_plan_projects', { txt })
}
function choose(p, toTab) {
  const name = typeof p === 'string' ? p : picked.value
  if (!name) return
  router.push({ query: { project: name, tab: toTab || 'overview' } })
}
function go(t) {
  router.push({ query: { project: project.value, tab: t } })
}
function openNew() {
  router.push({ query: { new: '1', ...(project.value ? { project: project.value } : {}) } })
}
function onCreated(results) {
  if (results && results.length) router.push({ query: { project: results[0].project, tab: 'overview' } })
}
</script>

<style scoped>
.project-bar { background: #fff; border-bottom: 1px solid var(--slate-200); padding: 18px 24px 0; }
.bar-row { display: flex; gap: 16px; align-items: flex-end; flex-wrap: wrap; padding-bottom: 12px; }
.field { display: flex; flex-direction: column; gap: 6px; width: 340px; }
.badges { display: flex; gap: 8px; align-items: center; height: 40px; flex-wrap: wrap; }
.badge-dark { background: var(--primary); color: #fff; }
.sub { font-size: 13px; color: var(--slate-500); }
.h1 { margin: 0; font-size: 20px; font-weight: 650; }
.bar-actions { margin-left: auto; display: flex; gap: 10px; }
.tabs { display: flex; gap: 4px; margin-bottom: -1px; }
.tab { border: 0; background: transparent; font: inherit; font-size: 15px; padding: 12px 18px; cursor: pointer; color: var(--slate-500); border-bottom: 3px solid transparent; }
.tab.on { color: var(--primary); font-weight: 600; border-bottom-color: var(--primary); }
.tab:focus-visible { outline: 2px solid var(--primary); outline-offset: -2px; }
</style>
