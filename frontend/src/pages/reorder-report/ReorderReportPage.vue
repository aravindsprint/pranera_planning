<template>
  <div class="page">
    <AppHeader subtitle="Where each item stands against its re-order level, and what to plan" />

    <main class="page-content">
      <div class="page-toolbar">
        <div class="field">
          <label class="form-label" for="rr-group">Item group</label>
          <LinkField id="rr-group" v-model="filters.item_group" doctype="Item Group" placeholder="All groups" @change="load" />
        </div>
        <div class="field">
          <label class="form-label" for="rr-obtained">Made or bought</label>
          <select id="rr-obtained" v-model="filters.obtained" class="form-input" @change="load">
            <option value="">Both</option>
            <option value="Made">Made</option>
            <option value="Bought">Bought</option>
          </select>
        </div>
        <div class="field grow">
          <label class="form-label" for="rr-search">Item, name or family</label>
          <input id="rr-search" v-model.trim="filters.search" class="form-input" placeholder="e.g. 2TF ECO 220" @keyup.enter="load" />
        </div>
        <button class="btn btn-outline" :disabled="loading" @click="load"><i class="pi pi-refresh"></i> Refresh</button>
        <button class="btn btn-outline" :disabled="recalculating" @click="recalculateAll">Recalculate all</button>
      </div>

      <div v-if="data" class="chips" role="group" aria-label="Filter by status">
        <button class="chip" :class="{ on: !filters.status }" @click="setStatus('')">All <b>{{ fmt(data.total) }}</b></button>
        <button
          v-for="s in STATUSES" :key="s" class="chip" :class="[{ on: filters.status === s }, `chip--${slug(s)}`]"
          @click="setStatus(s)"
        >{{ s }} <b>{{ fmt(data.counts[s] || 0) }}</b></button>
      </div>

      <p v-if="data" class="note">
        <template v-if="data.settings.last_run">
          Calculated {{ when(data.settings.last_run) }} for {{ fmt(data.settings.last_run_items) }} items, from the last
          {{ data.settings.history_days }} days of sales and consumption.
        </template>
        <template v-else>Not calculated yet — use Recalculate all, or wait for tonight's run.</template>
        <a href="/app/re-order-settings" target="_blank">Re-order settings</a>
      </p>
      <div v-if="data && data.settings.stages_without_days.length" class="alert alert-warning" role="status">
        No lead days set for: <b>{{ data.settings.stages_without_days.join(', ') }}</b>. Items made by these stages get no
        lead time for them, so their re-order levels are too low — set <i>Days used</i> in Re-order settings.
      </div>

      <div v-if="error" class="alert alert-error" role="alert">{{ error }}</div>
      <div v-if="message" class="alert alert-info" role="status">{{ message }}</div>

      <div v-if="loading && !data" class="loading-center"><div class="spinner"></div></div>

      <div v-else-if="data && !data.rows.length" class="card">
        <div class="empty-state">
          <div class="empty-state__title">No items match</div>
          <div class="empty-state__sub">Only items with sales or consumption in the history window are calculated.</div>
        </div>
      </div>

      <div v-else-if="data" class="table-wrap">
        <table class="data-table rr">
          <thead>
            <tr>
              <th class="exp"></th>
              <th>Item</th>
              <th class="num">Avg / day</th>
              <th class="num">Lead days</th>
              <th class="num">Safety</th>
              <th class="num">Re-order level</th>
              <th class="num">Re-order qty</th>
              <th class="num">Max</th>
              <th class="num">In stores</th>
              <th class="num">Reserved</th>
              <th class="num">Free</th>
              <th class="num">WIP</th>
              <th class="num">On order</th>
              <th class="num">Position</th>
              <th>Status</th>
              <th class="num">Suggest</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <template v-for="r in data.rows" :key="r.item_code">
              <tr :class="{ open: open[r.item_code] }">
                <td class="exp">
                  <button class="icon-btn" :aria-expanded="!!open[r.item_code]" :aria-label="`Workings for ${r.item_code}`" @click="toggle(r.item_code)">
                    <i :class="open[r.item_code] ? 'pi pi-chevron-down' : 'pi pi-chevron-right'"></i>
                  </button>
                </td>
                <td>
                  <div class="item">{{ r.item_code }}</div>
                  <div class="sub">
                    {{ r.family || '—' }} · {{ r.obtained === 'Made' ? (r.stage || 'Made') : 'Bought' }}
                    <span v-if="r.item_name && r.item_name !== r.item_code"> · {{ r.item_name }}</span>
                  </div>
                </td>
                <td class="num">{{ fmt(r.avg_daily, 2) }}</td>
                <td class="num">
                  <span v-if="r.lead_missing" class="badge badge-warning" title="No lead days set for this item's stage">0</span>
                  <span v-else>{{ fmt(r.lead_days) }}</span>
                </td>
                <td class="num">{{ fmt(r.safety_qty) }}</td>
                <td class="num"><b>{{ fmt(r.reorder_level) }}</b></td>
                <td class="num">{{ fmt(r.reorder_qty) }}</td>
                <td class="num">{{ fmt(r.max_level) }}</td>
                <td class="num">{{ fmt(r.in_stores) }}</td>
                <td class="num">{{ fmt(r.reserved) }}</td>
                <td class="num">{{ fmt(r.free) }}</td>
                <td class="num">{{ fmt(r.wip) }}</td>
                <td class="num">{{ fmt(r.on_order) }}</td>
                <td class="num"><b>{{ fmt(r.position) }}</b></td>
                <td><span class="badge" :class="badge(r.status)">{{ r.status }}</span></td>
                <td class="num"><b v-if="r.suggest_qty">{{ fmt(r.suggest_qty) }}</b><span v-else class="muted">—</span></td>
                <td class="act">
                  <a
                    v-if="r.suggest_qty" class="link-btn primary"
                    :href="`${APP_BASE}/plan?item=${encodeURIComponent(r.item_code)}&qty=${r.suggest_qty}&mode=make`"
                    title="Start a made-to-stock plan for the suggested quantity"
                  >Plan</a>
                </td>
              </tr>
              <tr v-if="open[r.item_code]" class="detail-row">
                <td></td>
                <td colspan="16">
                  <div class="workings">
                    <div class="workings__col">
                      <div class="workings__h">How the level is worked out</div>
                      <div class="wl"><span>Demand in the last {{ data.settings.history_days }} days ({{ r.demand_basis }})</span><b>{{ fmt(r.demand_qty) }}</b></div>
                      <div class="wl"><span>Avg / day = {{ fmt(r.demand_qty) }} ÷ {{ data.settings.history_days }}</span><b>{{ fmt(r.avg_daily, 2) }}</b></div>
                      <div class="wl"><span>Lead days{{ r.obtained === 'Made' ? ' (this stage + the stages below it)' : ' (supplier)' }}</span><b>{{ fmt(r.lead_days) }}</b></div>
                      <div class="wl"><span>Safety = {{ fmt(r.avg_daily, 2) }} × {{ fmt(r.safety_days) }} safety days</span><b>{{ fmt(r.safety_qty) }}</b></div>
                      <div class="wl"><span>Re-order level = {{ fmt(r.avg_daily, 2) }} × {{ fmt(r.lead_days) }} + {{ fmt(r.safety_qty) }}</span><b>{{ fmt(r.reorder_level) }}</b></div>
                      <div class="wl"><span>Re-order qty = {{ fmt(r.avg_daily, 2) }} × {{ fmt(r.cover_days) }} cover days</span><b>{{ fmt(r.reorder_qty) }}</b></div>
                      <div class="wl"><span>Max = {{ fmt(r.reorder_level) }} + {{ fmt(r.reorder_qty) }}</span><b>{{ fmt(r.max_level) }}</b></div>
                    </div>
                    <div class="workings__col">
                      <div class="workings__h">Where it stands</div>
                      <div class="wl"><span>Free = {{ fmt(r.in_stores) }} in stores − {{ fmt(r.reserved) }} reserved for orders</span><b>{{ fmt(r.free) }}</b></div>
                      <div class="wl"><span>+ WIP (what open orders will still deliver)</span><b>{{ fmt(r.wip) }}</b></div>
                      <div class="wl"><span>+ On order (open Purchase Orders + Material Requests)</span><b>{{ fmt(r.on_order) }}</b></div>
                      <div class="wl"><span>Position</span><b>{{ fmt(r.position) }}</b></div>
                      <div v-if="r.suggest_qty" class="wl"><span>Suggest = {{ fmt(r.max_level) }} − {{ fmt(r.position) }}, rounded up to {{ fmt(r.round_to) }}</span><b>{{ fmt(r.suggest_qty) }}</b></div>
                      <div class="wl muted"><span>Calculated {{ when(r.calculated_on) }}</span>
                        <button class="link-btn primary" :disabled="refreshing[r.item_code]" @click="refresh(r.item_code)">
                          {{ refreshing[r.item_code] ? 'Refreshing…' : 'Refresh now' }}
                        </button>
                      </div>
                    </div>
                  </div>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
      <p v-if="data && data.rows.length >= 500" class="note">Showing the first 500 — narrow the filters to see the rest.</p>
    </main>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import AppHeader from '@/components/AppHeader.vue'
import LinkField from '@/components/LinkField.vue'
import { callMessage } from '@/api/frappe'
import { APP_BASE } from '@/config/app'

const STATUSES = ['Order now', 'Near', 'OK', 'Over max', 'No demand']
const filters = reactive({ status: '', item_group: '', obtained: '', search: '' })
const data = ref(null)
const loading = ref(false)
const error = ref('')
const message = ref('')
const recalculating = ref(false)
const open = reactive({})
const refreshing = reactive({})

const fmt = (n, d = 0) => Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: d })
const slug = (s) => s.toLowerCase().replace(/\s+/g, '-')
const when = (t) => (t ? new Date(String(t).replace(' ', 'T')).toLocaleString() : '—')
const badge = (s) => ({
  'Order now': 'badge-danger', Near: 'badge-warning', OK: 'badge-success', 'Over max': 'badge-info',
}[s] || 'badge-muted')

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await callMessage('pranera_planning.api.reorder.get_reorder_report', { ...filters })
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

function setStatus(s) {
  filters.status = s
  load()
}

function toggle(code) {
  open[code] = !open[code]
}

async function refresh(code) {
  refreshing[code] = true
  try {
    await callMessage('pranera_planning.api.reorder.recalculate_items', { items: [code] })
    await load()
    open[code] = true
  } catch (e) {
    error.value = e.message
  } finally {
    refreshing[code] = false
  }
}

async function recalculateAll() {
  recalculating.value = true
  message.value = ''
  try {
    message.value = await callMessage('pranera_planning.reorder.recalculate_now')
  } catch (e) {
    error.value = e.message
  } finally {
    recalculating.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.page-toolbar { align-items: flex-end; }
.field { display: flex; flex-direction: column; gap: 6px; width: 220px; }
.field.grow { flex: 1; min-width: 220px; width: auto; }
.chips { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
.chip { height: 34px; padding: 0 14px; border: 1px solid var(--slate-200); border-radius: 999px; background: #fff; font: inherit; font-size: 13px; cursor: pointer; }
.chip b { margin-left: 4px; }
.chip.on { background: var(--primary); border-color: var(--primary); color: #fff; }
.note { font-size: 13px; color: var(--slate-500); margin: 0 0 12px; display: flex; gap: 12px; flex-wrap: wrap; }
.alert-warning { background: #fff7ed; border: 1px solid #f3c79a; color: #7c2d12; border-radius: 8px; padding: 10px 14px; margin-bottom: 12px; font-size: 13px; }
.alert-info { background: #eff6ff; border: 1px solid #bfdbfe; color: #1e3a8a; border-radius: 8px; padding: 10px 14px; margin-bottom: 12px; font-size: 13px; }
.rr { font-size: 13px; }
.rr th { white-space: nowrap; font-size: 11px; text-transform: uppercase; letter-spacing: 0.03em; }
.rr .num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.rr .exp { width: 32px; }
.rr .act { text-align: right; white-space: nowrap; }
.item { font-weight: 600; }
.sub { font-size: 12px; color: var(--slate-500); }
.muted { color: var(--slate-400); }
.icon-btn { border: 0; background: transparent; cursor: pointer; color: var(--slate-500); padding: 4px; }
.link-btn { border: 0; background: transparent; font: inherit; font-size: 13px; cursor: pointer; color: var(--slate-700); padding: 0; }
.link-btn.primary { color: var(--primary); font-weight: 600; }
.link-btn:disabled { color: var(--slate-400); cursor: default; }
.badge-muted { background: var(--slate-100); color: var(--slate-500); }
tr.open td { background: var(--slate-50, #f8fafc); }
.detail-row td { background: var(--slate-50, #f8fafc); }
.workings { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 24px; padding: 6px 0 12px; }
.workings__h { font-weight: 650; margin-bottom: 6px; }
.wl { display: flex; justify-content: space-between; gap: 16px; padding: 3px 0; border-bottom: 1px dashed var(--slate-200); }
.wl b { font-variant-numeric: tabular-nums; }
</style>
