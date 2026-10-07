<template>
  <div class="page">
    <AppHeader subtitle="Time and Action across all orders and stock programmes" />
    <main class="page-content">
      <nav class="tabs" aria-label="Report">
        <button v-for="t in TABS" :key="t.key" class="tab" :class="{ on: tab === t.key }" :aria-current="tab === t.key ? 'page' : undefined"
                @click="tab = t.key; load()">{{ t.label }}</button>
      </nav>
      <div v-if="error" class="alert alert-error" role="alert">{{ error }}</div>

      <!-- dashboard -->
      <template v-if="tab === 'dash'">
        <section class="card controls">
          <div class="field"><label class="form-label" for="r-stage">Stage</label>
            <select id="r-stage" v-model="stage" class="form-input" @change="load"><option value="">All</option>
              <option v-for="s in dash?.stages || []" :key="s" :value="s">{{ s }}</option></select></div>
          <div class="field"><label class="form-label" for="r-cust">Customer</label>
            <select id="r-cust" v-model="customer" class="form-input" @change="load"><option value="">All</option>
              <option v-for="c in dash?.customers || []" :key="c" :value="c">{{ c }}</option></select></div>
          <button class="btn btn-outline" :disabled="loading" @click="load">{{ loading ? 'Loading…' : 'Refresh' }}</button>
        </section>
        <div v-if="loading && !dash" class="loading-center"><div class="spinner"></div></div>
        <template v-else-if="dash">
          <section class="stats">
            <div class="stat bad"><div class="stat__v">{{ dash.totals.late || 0 }}</div><div class="stat__l">late or starting late</div></div>
            <div class="stat warn"><div class="stat__v">{{ dash.totals.due || 0 }}</div><div class="stat__l">due in the next 7 days</div></div>
            <div class="stat"><div class="stat__v">{{ dash.totals.in_progress || 0 }}</div><div class="stat__l">in progress, on time</div></div>
            <div class="stat ok"><div class="stat__v">{{ dash.totals.done || 0 }}</div><div class="stat__l">done</div></div>
          </section>
          <div class="two">
            <section v-for="pv in [['By stage', dash.by_stage], ['By customer', dash.by_customer]]" :key="pv[0]" class="card flush">
              <div class="card__head"><h2 class="h2">{{ pv[0] }}</h2></div>
              <table class="data-table compact">
                <thead><tr><th></th><th class="num">Late</th><th class="num">Due 7 d</th><th class="num">In progress</th><th class="num">Later</th><th class="num">Done</th></tr></thead>
                <tbody><tr v-for="r in pv[1]" :key="r.name">
                  <td>{{ r.name }}</td><td class="num" :class="{ bad: r.late }">{{ r.late || '' }}</td><td class="num" :class="{ warnc: r.due }">{{ r.due || '' }}</td>
                  <td class="num">{{ r.in_progress || '' }}</td><td class="num sub">{{ r.later || '' }}</td><td class="num sub">{{ r.done || '' }}</td></tr></tbody>
              </table>
            </section>
          </div>
          <section class="card flush">
            <div class="card__head"><h2 class="h2">To act on</h2><span class="sub">late first, then due this week, then in progress</span></div>
            <p v-if="!dash.activities.length" class="empty">Nothing late, due this week or in progress.</p>
            <div v-else class="scroll"><table class="data-table">
              <thead><tr><th>Project</th><th>Customer</th><th>Stage</th><th>Item</th><th>By</th><th class="num">Done / qty</th><th>Planned</th><th>Status</th><th class="num">Delay</th><th>Remarks</th></tr></thead>
              <tbody><tr v-for="a in dash.activities" :key="a.project + a.activity + a.item_code" :class="{ late: a.late }">
                <td><a :href="ta(a.project)">{{ a.project }}</a><div class="sub">deliver {{ dd(a.deliver_on) }}</div></td>
                <td>{{ a.customer }}</td><td>{{ a.stage }}</td><td>{{ a.item_code }}</td><td class="sub">{{ a.by }}</td>
                <td class="num">{{ fmt(a.done_qty) }} / {{ fmt(a.qty) }} <span class="sub">{{ a.uom }}</span></td>
                <td>{{ dd(a.planned_start) }} → {{ dd(a.planned_end) }}</td>
                <td><span class="badge" :class="a.late ? 'b-bad' : a.bucket === 'due' ? 'b-warn' : 'b-info'">{{ a.late ? (a.late_start ? 'Start late' : 'Late') : a.bucket === 'due' ? 'Due' : 'In progress' }}</span></td>
                <td class="num" :class="{ bad: a.delay_days > 0 }">{{ a.delay_days > 0 ? `+${a.delay_days} d` : '—' }}</td>
                <td class="sub">{{ a.remarks }}</td></tr></tbody>
            </table></div>
          </section>
        </template>
      </template>

      <!-- utilisation -->
      <template v-if="tab === 'util'">
        <section class="card controls">
          <div class="field"><label class="form-label" for="u-stage">Stage</label>
            <select id="u-stage" v-model="ustage" class="form-input" @change="load"><option value="">All machines</option>
              <option v-for="s in stagesList" :key="s" :value="s">{{ s }}</option></select></div>
          <div class="field"><label class="form-label" for="u-start">From week of</label>
            <input id="u-start" v-model="ustart" type="date" class="form-input" @change="load" /></div>
          <div class="field"><label class="form-label" for="u-weeks">Weeks</label>
            <select id="u-weeks" v-model.number="uweeks" class="form-input" @change="load"><option :value="4">4</option><option :value="8">8</option><option :value="13">13</option></select></div>
          <button class="btn btn-outline" :disabled="loading" @click="load">{{ loading ? 'Loading…' : 'Refresh' }}</button>
        </section>
        <section v-if="util" class="card flush">
          <div class="card__head"><h2 class="h2">Booked against capacity, by week</h2><span class="sub">capacity = Kg per hour × Working Hours × Production Capacity, without holidays</span></div>
          <p v-if="!util.machines.length" class="empty">No workstation with a Planning stage{{ ustage ? ` “${ustage}”` : '' }}.</p>
          <div v-else class="scroll"><table class="data-table util">
            <thead><tr><th>Machine</th><th v-for="w in util.weeks" :key="w" class="num">wk {{ dd(w) }}</th><th class="num">All</th></tr></thead>
            <tbody><tr v-for="m in util.machines" :key="m.workstation">
              <td><div class="item">{{ m.label }}</div><div class="sub">{{ m.stage }}</div></td>
              <td v-for="c in m.cells" :key="c.week" class="num" :class="heat(c.pct)" :title="`${fmt(c.booked)} of ${fmt(c.capacity)} kg`">{{ c.pct == null ? '—' : `${c.pct}%` }}</td>
              <td class="num"><b>{{ m.total_pct == null ? '—' : `${m.total_pct}%` }}</b></td></tr></tbody>
          </table></div>
        </section>
      </template>

      <!-- delays -->
      <template v-if="tab === 'delay'">
        <section class="card controls">
          <div class="field"><label class="form-label" for="d-from">Finished from</label><input id="d-from" v-model="dfrom" type="date" class="form-input" @change="load" /></div>
          <div class="field"><label class="form-label" for="d-to">to</label><input id="d-to" v-model="dto" type="date" class="form-input" @change="load" /></div>
          <button class="btn btn-outline" :disabled="loading" @click="load">{{ loading ? 'Loading…' : 'Refresh' }}</button>
          <span v-if="del" class="big">On time: <b>{{ del.on_time_pct == null ? '—' : `${del.on_time_pct}%` }}</b> <span class="sub">of {{ del.finished }} finished</span></span>
        </section>
        <template v-if="del">
          <section class="card flush">
            <div class="card__head"><h2 class="h2">By stage</h2><span class="sub">days from planned start to planned end, and from actual start to actual end</span></div>
            <table class="data-table">
              <thead><tr><th>Stage</th><th class="num">Finished</th><th class="num">On time</th><th class="num">Planned days</th><th class="num">Actual days</th><th class="num">Avg delay</th><th class="num">Late, still open</th></tr></thead>
              <tbody><tr v-for="s in del.stages" :key="s.stage">
                <td>{{ s.stage }}</td><td class="num">{{ s.finished }}</td>
                <td class="num" :class="{ bad: s.on_time_pct != null && s.on_time_pct < 80, good: s.on_time_pct >= 80 }">{{ s.on_time_pct == null ? '—' : `${s.on_time_pct}%` }}</td>
                <td class="num">{{ s.avg_planned_days ?? '—' }}</td><td class="num">{{ s.avg_actual_days ?? '—' }}</td>
                <td class="num" :class="{ bad: s.avg_delay_days > 0 }">{{ s.avg_delay_days == null ? '—' : `${s.avg_delay_days > 0 ? '+' : ''}${s.avg_delay_days} d` }}</td>
                <td class="num" :class="{ bad: s.late_open }">{{ s.late_open || '' }}</td></tr></tbody>
            </table>
          </section>
          <section class="card flush">
            <div class="card__head"><h2 class="h2">Activities</h2><span class="sub">largest delay first · the remarks are the reasons given on the Time &amp; Action tab</span></div>
            <p v-if="!del.rows.length" class="empty">Nothing finished in this period, and nothing late.</p>
            <div v-else class="scroll"><table class="data-table">
              <thead><tr><th>Project</th><th>Stage</th><th>Item</th><th>By</th><th>Planned</th><th>Actual</th><th class="num">Delay</th><th class="num">Slip vs first plan</th><th>Reason</th></tr></thead>
              <tbody><tr v-for="r in del.rows" :key="r.project + r.stage + r.item_code">
                <td><a :href="ta(r.project)">{{ r.project }}</a><div class="sub">{{ r.customer }}</div></td>
                <td>{{ r.stage }}</td><td>{{ r.item_code }}</td><td class="sub">{{ r.by }}</td>
                <td>{{ dd(r.planned_start) }} → {{ dd(r.planned_end) }}</td>
                <td>{{ r.actual_start ? `${dd(r.actual_start)} → ${r.actual_end ? dd(r.actual_end) : '…'}` : '—' }}</td>
                <td class="num" :class="{ bad: r.delay_days > 0, good: r.delay_days <= 0 && r.status === 'Done' }">{{ r.delay_days ? `${r.delay_days > 0 ? '+' : ''}${r.delay_days} d` : '0' }}</td>
                <td class="num sub">{{ r.slip_days ? `${r.slip_days > 0 ? '+' : ''}${r.slip_days} d` : '—' }}</td>
                <td class="sub">{{ r.remarks || '—' }}</td></tr></tbody>
            </table></div>
          </section>
        </template>
      </template>
    </main>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import AppHeader from '@/components/AppHeader.vue'
import { callMessage } from '@/api/frappe'
import { APP_BASE } from '@/config/app'

const TABS = [{ key: 'dash', label: 'Dashboard' }, { key: 'util', label: 'Workstation utilisation' }, { key: 'delay', label: 'Delays' }]
const tab = ref('dash')
const loading = ref(false)
const error = ref('')
const dash = ref(null), util = ref(null), del = ref(null)
const stage = ref(''), customer = ref('')
const ustage = ref(''), ustart = ref(new Date().toISOString().slice(0, 10)), uweeks = ref(8)
const iso = (d) => d.toISOString().slice(0, 10)
const dfrom = ref(iso(new Date(Date.now() - 90 * 864e5))), dto = ref(iso(new Date()))
const stagesList = computed(() => dash.value?.stages?.filter((s) => s !== 'Buy') || [])

const fmt = (n) => Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })
const dd = (d) => (d ? new Date(`${String(d).slice(0, 10)}T00:00:00`).toLocaleDateString(undefined, { day: 'numeric', month: 'short' }) : '—')
const ta = (p) => `${APP_BASE}/project-planning?project=${encodeURIComponent(p)}&tab=ta`
const heat = (p) => (p == null ? 'hx-off' : p > 100 ? 'hx3' : p >= 80 ? 'hx2' : p > 0 ? 'hx1' : '')

async function load() {
  loading.value = true
  error.value = ''
  try {
    if (tab.value === 'dash' || !dash.value) dash.value = await callMessage('pranera_planning.api.ta_reports.dashboard', { stage: stage.value, customer: customer.value })
    if (tab.value === 'util') util.value = await callMessage('pranera_planning.api.ta_reports.utilisation', { stage: ustage.value, start: ustart.value, weeks: uweeks.value })
    if (tab.value === 'delay') del.value = await callMessage('pranera_planning.api.ta_reports.delays', { from_date: dfrom.value, to_date: dto.value })
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}
onMounted(load)
</script>

<style scoped>
.tabs { display: flex; gap: 4px; margin-bottom: 14px; border-bottom: 1px solid var(--slate-200); }
.tab { border: 0; background: none; padding: 10px 14px; font: inherit; font-size: 14px; color: var(--slate-500); cursor: pointer; border-bottom: 2px solid transparent; }
.tab.on { color: var(--slate-900); font-weight: 650; border-bottom-color: var(--primary); }
.controls { display: flex; gap: 14px; align-items: flex-end; flex-wrap: wrap; margin-bottom: 16px; }
.field { display: flex; flex-direction: column; gap: 6px; min-width: 160px; }
.big { margin-left: auto; font-size: 15px; }
.stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 16px; }
.stat.bad { background: #fef2f2; border-color: #fecaca; }
.stat.warn { background: #fff7ed; border-color: #f3c79a; }
.stat.ok { background: #ecfdf3; border-color: #bbe5c8; }
.two { display: grid; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); gap: 16px; }
.card.flush { padding: 0; margin-bottom: 16px; overflow: hidden; }
.card__head { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 14px 18px; border-bottom: 1px solid var(--slate-200); }
.h2 { margin: 0; font-size: 16px; font-weight: 650; }
.sub { font-size: 12px; color: var(--slate-500); }
.item { font-weight: 600; }
.empty { padding: 16px 18px; margin: 0; font-size: 14px; color: var(--slate-500); }
.scroll { overflow-x: auto; }
.num { text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
.bad { color: #b91c1c; font-weight: 600; }
.warnc { color: #9a3412; font-weight: 600; }
.good { color: #166534; font-weight: 600; }
tr.late td { background: #fff7f7; }
.badge.b-bad { background: #fee2e2; color: #b91c1c; }
.badge.b-warn { background: #fef3c7; color: #92400e; }
.badge.b-info { background: #dbeafe; color: #1d4ed8; }
.data-table.compact td, .data-table.compact th { padding-top: 6px; padding-bottom: 6px; }
.util td.num { min-width: 70px; }
.hx1 { background: #dcfce7; color: #166534; }
.hx2 { background: #fef3c7; color: #92400e; }
.hx3 { background: #fee2e2; color: #b91c1c; font-weight: 700; }
.hx-off { color: var(--slate-400); }
@media (max-width: 760px) { .stats { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
