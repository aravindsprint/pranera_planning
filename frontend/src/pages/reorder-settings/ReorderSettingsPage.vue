<template>
  <div class="page">
    <AppHeader subtitle="The levers behind re-order levels, plans and made-to-stock projects" />

    <main class="page-content">
      <div v-if="error" class="alert alert-error" role="alert">{{ error }}</div>
      <div v-if="saved" class="alert alert-success" role="status">{{ saved }}</div>
      <div v-if="loading && !s" class="loading-center"><div class="spinner"></div></div>

      <template v-else-if="s">
        <div class="toolbar">
          <span class="sub">
            <template v-if="s.last_run">Last calculated {{ when(s.last_run) }} for {{ s.last_run_items || 0 }} items.</template>
            <template v-else>Not calculated yet.</template>
            <template v-if="!s.can_write"> · You can view these settings but not change them.</template>
          </span>
          <div class="toolbar__actions">
            <a class="btn btn-outline" :href="deskUrl('/app/re-order-settings')" target="_blank">Open in desk</a>
            <a class="btn btn-outline" :href="`${APP_BASE}/reorder-report`">Open report</a>
            <button class="btn btn-outline" :disabled="busy" @click="recalculate">Recalculate now</button>
            <button class="btn btn-primary" :disabled="busy || !s.can_write || !dirty" @click="save">{{ busy ? 'Saving…' : 'Save' }}</button>
          </div>
        </div>

        <!-- Demand -->
        <section class="card">
          <h2 class="h2">Demand</h2>
          <div class="grid">
            <div class="field"><label class="form-label" for="rs-hist">History (days)</label>
              <input id="rs-hist" v-model.number="s.history_days" type="number" min="1" class="form-input" :disabled="!s.can_write" />
              <span class="hint">Average daily demand = demand in these last days ÷ days.</span></div>
            <div class="field"><label class="form-label" for="rs-near">Near margin (%)</label>
              <input id="rs-near" v-model.number="s.near_margin" type="number" min="0" step="any" class="form-input" :disabled="!s.can_write" />
              <span class="hint">Items within this much above their re-order level show as Near.</span></div>
            <div class="field"><label class="form-label" for="rs-safety">Default safety days</label>
              <input id="rs-safety" v-model.number="s.default_safety_days" type="number" min="0" step="any" class="form-input" :disabled="!s.can_write" /></div>
            <div class="field"><label class="form-label" for="rs-cover">Default cover days</label>
              <input id="rs-cover" v-model.number="s.default_cover_days" type="number" min="0" step="any" class="form-input" :disabled="!s.can_write" /></div>
            <div class="field"><label class="form-label" for="rs-round">Default round up to</label>
              <input id="rs-round" v-model.number="s.default_round_to" type="number" min="0" step="any" class="form-input" :disabled="!s.can_write" />
              <span class="hint">Used where no item-group rule applies.</span></div>
          </div>
        </section>

        <!-- Per item group -->
        <section class="card">
          <div class="card__head"><h2 class="h2">Per item group</h2><span class="sub">The nearest group above an item wins.</span></div>
          <table class="data-table">
            <thead><tr><th>Item group</th><th>Demand from</th><th class="num">Safety days</th><th class="num">Cover days</th><th class="num">Round up to</th><th class="num">Lead days when bought</th><th></th></tr></thead>
            <tbody>
              <tr v-if="!s.group_rules.length"><td colspan="7" class="empty">No rules — every item uses the defaults above.</td></tr>
              <tr v-for="(r, i) in s.group_rules" :key="`g${i}`">
                <td class="wide"><LinkField v-model="r.item_group" doctype="Item Group" placeholder="Item group" :disabled="!s.can_write" /></td>
                <td><select v-model="r.demand_basis" class="form-input" :disabled="!s.can_write">
                  <option v-for="o in DEMAND" :key="o" :value="o">{{ o }}</option></select></td>
                <td class="num"><input v-model.number="r.safety_days" type="number" min="0" step="any" class="form-input n" :disabled="!s.can_write" /></td>
                <td class="num"><input v-model.number="r.cover_days" type="number" min="0" step="any" class="form-input n" :disabled="!s.can_write" /></td>
                <td class="num"><input v-model.number="r.round_to" type="number" min="0" step="any" class="form-input n" :disabled="!s.can_write" /></td>
                <td class="num"><input v-model.number="r.bought_lead_days" type="number" min="0" step="any" class="form-input n" :disabled="!s.can_write" /></td>
                <td class="act"><button v-if="s.can_write" class="icon-btn" :aria-label="`Remove rule ${i + 1}`" @click="s.group_rules.splice(i, 1)"><i class="pi pi-times"></i></button></td>
              </tr>
            </tbody>
          </table>
          <button v-if="s.can_write" class="btn btn-outline add" @click="s.group_rules.push({ item_group: '', demand_basis: 'Sales + Consumption' })">+ Add rule</button>
        </section>

        <!-- Lead days -->
        <section class="card">
          <div class="card__head"><h2 class="h2">Lead days per stage</h2></div>
          <p class="hint">Days used drives the re-order levels. The learned medians beside it are a guide, refreshed nightly: Work Order
            creation to its last Manufacture entry (in-house), Subcontracting Order date to its last Subcontracting Receipt (job work).</p>
          <div class="grid">
            <div class="field"><label class="form-label" for="rs-months">Learn from the last (months)</label>
              <input id="rs-months" v-model.number="s.lead_history_months" type="number" min="1" class="form-input" :disabled="!s.can_write" /></div>
            <label class="check"><input v-model="s.use_learned_lead_days" type="checkbox" :true-value="1" :false-value="0" :disabled="!s.can_write" />
              <span><b>Use learned days where Days used is empty</b><br /><span class="hint">Learned medians include waiting time — check them first.</span></span></label>
            <label class="check"><input v-model="s.include_bought_lead_days" type="checkbox" :true-value="1" :false-value="0" :disabled="!s.can_write" />
              <span><b>Include bought materials' lead days</b><br /><span class="hint">Off: finished fabric = 3 + 7 + 5 = 15 days; on: + the yarn supplier's days.</span></span></label>
          </div>
          <table class="data-table">
            <thead><tr><th>Stage</th><th>Usual route</th><th class="num">In-house (learned)</th><th class="num">Job work (learned)</th><th class="num">Days used</th><th>Job-work services</th><th></th></tr></thead>
            <tbody>
              <tr v-for="(r, i) in s.stage_leads" :key="`s${i}`">
                <td><input v-model.trim="r.stage" class="form-input" placeholder="e.g. Knitting" :disabled="!s.can_write" /></td>
                <td><select v-model="r.route" class="form-input" :disabled="!s.can_write">
                  <option value="In-house">In-house</option><option value="Job work">Job work</option></select></td>
                <td class="num">{{ learned(r.inhouse_days, r.inhouse_orders, 'Work Orders') }}</td>
                <td class="num">{{ learned(r.jobwork_days, r.jobwork_orders, 'SC Orders') }}</td>
                <td class="num"><input v-model.number="r.override_days" type="number" min="0" step="any" class="form-input n"
                                       :class="{ missing: !r.override_days }" :disabled="!s.can_write" /></td>
                <td class="wide"><input v-model.trim="r.job_work_services" class="form-input" placeholder="e.g. STENTER, DRYER" :disabled="!s.can_write" /></td>
                <td class="act"><button v-if="s.can_write" class="icon-btn" :aria-label="`Remove stage ${i + 1}`" @click="s.stage_leads.splice(i, 1)"><i class="pi pi-times"></i></button></td>
              </tr>
            </tbody>
          </table>
          <p v-if="s.stage_leads.some((r) => !r.override_days)" class="warn-line">Stages with no Days used give their items no lead time — set them.</p>
          <button v-if="s.can_write" class="btn btn-outline add" @click="s.stage_leads.push({ stage: '', route: 'In-house' })">+ Add stage</button>
        </section>

        <!-- Plans -->
        <section class="card">
          <h2 class="h2">Plans</h2>
          <div class="field half"><label class="form-label" for="rs-wh">Warehouse for planned requests</label>
            <LinkField id="rs-wh" v-model="s.default_warehouse" doctype="Warehouse" placeholder="e.g. Stores - PSS" :disabled="!s.can_write" />
            <span class="hint">Where Material Requests from a plan expect the goods (each item's default warehouse is used first).</span></div>
        </section>

        <!-- Made-to-stock projects -->
        <section class="card">
          <h2 class="h2">Made-to-stock projects</h2>
          <p class="hint">Family = the item's Commercial Name (else its top item group). With {SEQ}, every new plan for a family in a
            period gets its own project; re-planning from a project's own Plan tab keeps that project.</p>
          <div class="grid">
            <div class="field"><label class="form-label" for="rs-period">One project per</label>
              <select id="rs-period" v-model="s.stock_project_period" class="form-input" :disabled="!s.can_write">
                <option>Quarter</option><option>Month</option><option>Season</option></select></div>
            <div class="field wide2"><label class="form-label" for="rs-pattern">Project name</label>
              <input id="rs-pattern" v-model.trim="s.stock_project_pattern" class="form-input mono" :disabled="!s.can_write" />
              <span class="hint">{YY} or {YYYY}, {FAMILY}, {PERIOD}, {SEQ} (01, 02 …).</span></div>
          </div>
          <div class="preview">
            <span class="sub">This period's names for 2TF ECO 220:</span>
            <code>{{ preview(1) }}</code><span class="sub">then</span><code>{{ preview(2) }}</code>
            <span v-if="!hasSeq" class="sub">— without {SEQ}, both plans share the first project.</span>
          </div>
          <template v-if="s.stock_project_period === 'Season'">
            <table class="data-table seasons">
              <thead><tr><th>Season</th><th>Starts in month</th><th></th></tr></thead>
              <tbody>
                <tr v-if="!s.seasons.length"><td colspan="3" class="empty">Add the seasons, e.g. SUMMER from February, WINTER from August.</td></tr>
                <tr v-for="(r, i) in s.seasons" :key="`n${i}`">
                  <td><input v-model.trim="r.season" class="form-input" placeholder="e.g. SUMMER" :disabled="!s.can_write" /></td>
                  <td><select v-model="r.start_month" class="form-input" :disabled="!s.can_write">
                    <option v-for="(m, mi) in MONTHS" :key="m" :value="String(mi + 1)">{{ m }}</option></select></td>
                  <td class="act"><button v-if="s.can_write" class="icon-btn" :aria-label="`Remove season ${i + 1}`" @click="s.seasons.splice(i, 1)"><i class="pi pi-times"></i></button></td>
                </tr>
              </tbody>
            </table>
            <button v-if="s.can_write" class="btn btn-outline add" @click="s.seasons.push({ season: '', start_month: '' })">+ Add season</button>
          </template>
        </section>
      </template>
    </main>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import AppHeader from '@/components/AppHeader.vue'
import LinkField from '@/components/LinkField.vue'
import { callMessage } from '@/api/frappe'
import { APP_BASE } from '@/config/app'
import { deskUrl } from '@/config/backend'

const DEMAND = ['Sales + Consumption', 'Sales', 'Consumption']
const MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
const s = ref(null)
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const saved = ref('')
const dirty = ref(false)
let original = ''

const when = (t) => (t ? new Date(String(t).replace(' ', 'T')).toLocaleString() : '—')
const learned = (days, orders, what) => (days ? `${Number(days).toLocaleString(undefined, { maximumFractionDigits: 1 })} (${orders || 0} ${what})` : '—')
const hasSeq = computed(() => (s.value?.stock_project_pattern || '').includes('{SEQ}'))

// Mirrors reorder_math.period_of / stock_project_name, for the preview only.
function periodNow() {
  const d = new Date()
  const mode = s.value?.stock_project_period || 'Quarter'
  if (mode === 'Month') return [d.getFullYear(), MONTHS[d.getMonth()]]
  const seasons = (s.value?.seasons || []).filter((r) => r.season && r.start_month)
    .map((r) => [Number(r.start_month), r.season.toUpperCase()]).sort((a, b) => a[0] - b[0])
  if (mode === 'Season' && seasons.length) {
    const started = seasons.filter(([m]) => m <= d.getMonth() + 1)
    return started.length ? [d.getFullYear(), started[started.length - 1][1]] : [d.getFullYear() - 1, seasons[seasons.length - 1][1]]
  }
  return [d.getFullYear(), `Q${Math.floor(d.getMonth() / 3) + 1}`]
}
function preview(seq) {
  const [year, period] = periodNow()
  return (s.value?.stock_project_pattern || '').replace('{YYYY}', String(year)).replace('{YY}', String(year % 100).padStart(2, '0'))
    .replace('{FAMILY}', '2TF ECO 220').replace('{PERIOD}', period).replace('{SEQ}', String(hasSeq.value ? seq : 1).padStart(2, '0'))
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    s.value = await callMessage('pranera_planning.api.reorder_settings.get_settings')
    original = JSON.stringify(s.value)
    dirty.value = false
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}
watch(s, (v) => { if (v) dirty.value = JSON.stringify(v) !== original }, { deep: true })

async function save() {
  busy.value = true
  error.value = ''
  saved.value = ''
  try {
    s.value = await callMessage('pranera_planning.api.reorder_settings.save_settings', { settings: s.value })
    original = JSON.stringify(s.value)
    dirty.value = false
    saved.value = 'Saved. Use Recalculate now (or wait for tonight) for the re-order levels to follow.'
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}
async function recalculate() {
  busy.value = true
  error.value = ''
  try {
    saved.value = await callMessage('pranera_planning.reorder.recalculate_now')
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}
onMounted(load)
</script>

<style scoped>
.toolbar { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 16px; }
.toolbar__actions { display: flex; gap: 10px; flex-wrap: wrap; }
.card { margin-bottom: 16px; }
.card__head { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; }
.h2 { margin: 0 0 12px; font-size: 16px; font-weight: 650; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px 20px; margin-bottom: 14px; }
.field { display: flex; flex-direction: column; gap: 6px; }
.field.half { max-width: 420px; }
.field.wide2 { grid-column: span 2; }
.hint, .sub { font-size: 12px; color: var(--slate-500); }
.check { display: flex; gap: 10px; align-items: flex-start; font-size: 14px; }
.check input { margin-top: 3px; }
.num { text-align: right; white-space: nowrap; }
.form-input.n { width: 110px; text-align: right; }
.form-input.missing { border-color: #f3c79a; background: #fff7ed; }
.mono { font-family: ui-monospace, monospace; }
td.wide { min-width: 240px; }
.act { width: 40px; text-align: right; }
.icon-btn { border: 0; background: transparent; cursor: pointer; color: var(--slate-500); padding: 4px; }
.empty { color: var(--slate-500); font-size: 13px; }
.add { margin-top: 10px; }
.warn-line { margin: 8px 0 0; font-size: 13px; color: #9a3412; }
.preview { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; }
.preview code { background: var(--slate-100); padding: 3px 8px; border-radius: 6px; font-size: 13px; }
.seasons { max-width: 520px; }
.alert-success { background: #ecfdf3; border: 1px solid #bbe5c8; color: #166534; border-radius: 8px; padding: 10px 14px; margin-bottom: 12px; font-size: 13px; }
</style>
