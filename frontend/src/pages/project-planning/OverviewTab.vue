<template>
  <div>
    <div v-if="error" class="alert alert-error" role="alert">{{ error }}</div>
    <div v-if="loading && !data" class="loading-center"><div class="spinner"></div></div>

    <template v-else-if="data">
      <section class="stats">
        <div class="stat"><div class="stat__v">{{ fmt(data.totals.held) }}</div><div class="stat__l">held for this project</div></div>
        <div class="stat" :class="{ warn: data.totals.drafts }"><div class="stat__v">{{ data.totals.drafts }}</div><div class="stat__l">draft requests waiting to be submitted</div></div>
        <template v-if="mto">
          <div class="stat"><div class="stat__v">{{ fmt(data.totals.delivered) }}</div><div class="stat__l">delivered so far</div></div>
          <div class="stat"><div class="stat__v">{{ fmt(data.totals.not_planned) }}</div><div class="stat__l">not yet planned</div></div>
        </template>
        <template v-else>
          <div class="stat"><div class="stat__v">{{ data.project.family || '—' }}</div><div class="stat__l">stock family</div></div>
          <div class="stat"><div class="stat__v">{{ data.project.period || '—' }}</div><div class="stat__l">period</div></div>
        </template>
      </section>

      <!-- made to order: the order -->
      <section v-if="mto" class="card flush">
        <div class="card__head"><h2 class="h2">Order</h2><span class="sub">everything under this project belongs to this order</span></div>
        <p v-if="!data.rows.length" class="empty">No Sales Order linked and no plan saved yet — plan it in the Plan tab.</p>
        <table v-else class="data-table">
          <thead><tr><th>Ordered item</th><th class="num">Ordered</th><th class="num">Ready</th><th class="num">In production</th><th class="num">Delivered</th><th class="num">Not planned</th></tr></thead>
          <tbody>
            <tr v-for="r in data.rows" :key="r.item + r.label">
              <td><div class="item">{{ r.item }}</div><div class="sub">{{ r.item_name !== r.item ? r.item_name : '' }} · {{ r.label }}</div></td>
              <td class="num">{{ fmt(r.ordered) }} <span class="sub">{{ r.uom }}</span></td>
              <td class="num" :class="{ good: r.ready }">{{ fmt(r.ready) }}</td>
              <td class="num" :class="{ blue: r.in_production }">{{ fmt(r.in_production) }}</td>
              <td class="num">{{ fmt(r.delivered) }}</td>
              <td class="num" :class="{ bad: r.not_planned }">{{ fmt(r.not_planned) }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="data.project.sales_order" class="foot">Ready stock ships only against {{ data.project.sales_order }}: a Sales Invoice or Delivery Note for another order is refused.</div>
      </section>

      <!-- made to stock: the programme -->
      <section v-else class="card flush">
        <div class="card__head"><h2 class="h2">Stock programme</h2><span class="sub">free for any order to reserve</span></div>
        <p v-if="!data.rows.length" class="empty">No plan saved yet — plan it in the Plan tab.</p>
        <table v-else class="data-table">
          <thead><tr><th>Item</th><th class="num">Target</th><th class="num">Held</th><th class="num">Reserved by orders</th><th class="num">Free now</th><th class="num">In production</th><th class="num">Free after plan</th></tr></thead>
          <tbody>
            <tr v-for="r in data.rows" :key="r.item">
              <td><div class="item">{{ r.item }}</div><div class="sub">{{ r.item_name !== r.item ? r.item_name : '' }}</div></td>
              <td class="num">{{ r.mode === 'make' ? `make ${fmt(r.target)}` : fmt(r.target) }}</td>
              <td class="num">{{ fmt(r.held) }}</td>
              <td class="num" :class="{ orange: r.reserved_by_orders }">{{ fmt(r.reserved_by_orders) }}</td>
              <td class="num"><b>{{ fmt(r.free_now) }}</b></td>
              <td class="num" :class="{ blue: r.in_production }">{{ fmt(r.in_production) }}</td>
              <td class="num"><b>{{ fmt(r.free_after_plan) }}</b></td>
            </tr>
          </tbody>
        </table>
      </section>

      <section class="card flush">
        <div class="card__head"><h2 class="h2">Requests</h2><span class="sub">{{ data.requests.length }} open</span></div>
        <p v-if="!data.requests.length" class="empty">No open Material Requests for this project.</p>
        <table v-else class="data-table">
          <thead><tr><th>Request</th><th>Lines</th><th>Kind</th><th>Status</th></tr></thead>
          <tbody>
            <tr v-for="m in data.requests" :key="m.name">
              <td><a :href="deskUrl(`/app/material-request/${m.name}`)" target="_blank">{{ m.name }}</a></td>
              <td>{{ m.lines.map((l) => `${l.item} ${fmt(l.qty)}`).join(' · ') }}</td>
              <td>{{ m.kind }}</td>
              <td><span class="badge" :class="m.status === 'Draft' ? 'badge-warning' : 'badge-info'">{{ m.status }}</span></td>
            </tr>
          </tbody>
        </table>
      </section>

      <section v-if="data.stages.length" class="card flush">
        <div class="card__head"><h2 class="h2">Stages</h2><span class="sub">Planned = what open requests and orders will still add</span></div>
        <table class="data-table">
          <thead><tr><th>Stage</th><th class="num">Input</th><th class="num">In process</th><th class="num">Produced</th><th class="num">Loss</th><th class="num">In stores</th><th class="num">Planned</th></tr></thead>
          <tbody>
            <tr v-for="s in data.stages" :key="s.stage">
              <td><div class="item">{{ s.stage }}</div><div class="sub">{{ s.orders }} order{{ s.orders === 1 ? '' : 's' }} · {{ s.batches }} batch{{ s.batches === 1 ? '' : 'es' }}</div></td>
              <td class="num">{{ s.input_qty == null ? '—' : fmt(s.input_qty) }}</td>
              <td class="num">{{ fmt(s.in_process_qty) }}</td>
              <td class="num"><b>{{ fmt(s.produced_qty) }}</b></td>
              <td class="num">{{ s.loss_qty == null ? '—' : fmt(s.loss_qty) }}</td>
              <td class="num">{{ fmt(s.in_stores_qty) }}</td>
              <td class="num" :class="{ blue: s.planned_qty }">{{ fmt(s.planned_qty) }}</td>
            </tr>
          </tbody>
        </table>
      </section>

      <div class="actions">
        <button class="btn btn-outline" @click="$emit('go', 'stock')">Hold or release stock</button>
        <button class="btn btn-primary" @click="$emit('go', 'plan')">Plan again</button>
      </div>
    </template>
  </div>
</template>

<script setup>
import { deskUrl } from '@/config/backend'
import { ref, computed, watch } from 'vue'
import { callMessage } from '@/api/frappe'

const props = defineProps({ project: { type: String, required: true } })
const emit = defineEmits(['go', 'loaded'])
const data = ref(null)
const loading = ref(false)
const error = ref('')
const mto = computed(() => data.value?.project.order_type !== 'Made to stock')
const fmt = (n) => Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await callMessage('pranera_planning.api.project_planning.get_overview', { project: props.project })
    emit('loaded', data.value.project)
  } catch (e) {
    error.value = e.message
    data.value = null
  } finally {
    loading.value = false
  }
}

watch(() => props.project, (p) => { data.value = null; if (p) load() }, { immediate: true })
defineExpose({ load })
</script>

<style scoped>
.stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 16px; }
.stat.warn { background: #fff7ed; border-color: #f3c79a; }
.card.flush { padding: 0; margin-bottom: 16px; overflow: hidden; }
.card__head { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 14px 18px; border-bottom: 1px solid var(--slate-200); }
.h2 { margin: 0; font-size: 16px; font-weight: 650; }
.sub { font-size: 12px; color: var(--slate-500); }
.item { font-weight: 600; }
.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.empty { padding: 16px 18px; margin: 0; font-size: 14px; color: var(--slate-500); }
.foot { padding: 10px 18px; background: var(--slate-50, #f8fafc); border-top: 1px solid var(--slate-200); font-size: 13px; color: var(--slate-500); }
.good { color: #166534; font-weight: 600; }
.blue { color: #1d4ed8; font-weight: 600; }
.bad { color: #b91c1c; font-weight: 600; }
.orange { color: #9a3412; font-weight: 600; }
.actions { display: flex; gap: 12px; justify-content: flex-end; }
</style>
