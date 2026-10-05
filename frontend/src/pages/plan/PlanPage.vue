<template>
  <div :class="{ page: !embedded }">
    <AppHeader v-if="!embedded" subtitle="Check stock first, then create only what's missing" />

    <main :class="embedded ? 'embedded' : 'page-content'">
      <div v-if="error" class="alert alert-error" role="alert">{{ error }}</div>

      <!-- ── 1 · start ─────────────────────────────────────────────────────── -->
      <section v-if="step === 'start'" class="stack">
        <div class="start-row">
          <fieldset v-if="!forProject" class="seg-field">
            <legend class="form-label">Order type</legend>
            <div class="seg">
              <button v-for="t in ORDER_TYPES" :key="t" type="button" :class="{ on: form.order_type === t }" @click="form.order_type = t">{{ t }}</button>
            </div>
          </fieldset>

          <template v-if="form.order_type === MTO">
            <div v-if="!forProject" class="field wide">
              <label class="form-label" for="pl-project">Project</label>
              <LinkField id="pl-project" v-model="form.project" doctype="Project" :search-fn="searchProjects"
                         placeholder="The order's project" empty-label="No open Production or Purchase project found" />
            </div>
            <div class="field">
              <label class="form-label" for="pl-so">Sales Order</label>
              <LinkField id="pl-so" v-model="form.sales_order" doctype="Sales Order" placeholder="Optional" />
            </div>
            <button class="btn btn-outline" :disabled="!form.sales_order || busy" @click="loadSalesOrder">Load lines</button>
          </template>

          <div class="field">
            <label class="form-label" for="pl-date">Needed by</label>
            <input id="pl-date" v-model="form.needed_by" type="date" class="form-input" />
          </div>
        </div>

        <p v-if="form.order_type === MTO && soInfo" class="note">
          {{ soInfo.customer }} · {{ soInfo.sales_order }} · delivery {{ soInfo.delivery_date || '—' }}
          <template v-if="!soInfo.submitted"> · <b>the Sales Order isn't submitted yet</b></template>
        </p>
        <p v-else-if="form.order_type === MTS && forProject" class="note">
          Re-plans {{ forProject }}: its saved targets are loaded; changes and new requests stay under this project.
        </p>
        <p v-else-if="form.order_type === MTS" class="note">
          Each line goes to the stock project of its family and period: family = the item's Commercial Name (else its top item
          group), period from Re-order Settings. Made items → a Production project, bought items → a Purchase project; it's
          created on Create if it doesn't exist yet.
        </p>

        <div class="card">
          <div class="card__head">
            <div>
              <div class="card__title">{{ form.order_type === MTO ? 'What the order must deliver' : 'What to have in stock' }}</div>
              <div class="sub">Any stage — finished, dyed, greige or yarn. Made items are planned down their default BOMs.</div>
            </div>
            <button class="btn btn-outline" @click="addLine">+ Add item</button>
          </div>
          <table class="data-table lines">
            <thead>
              <tr>
                <th>Item</th>
                <th v-if="form.order_type === MTS">Plan as</th>
                <th class="num">Quantity</th>
                <th>From</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(ln, i) in form.lines" :key="i">
                <td class="item-cell"><LinkField v-model="ln.item" doctype="Item" placeholder="Item code" /></td>
                <td v-if="form.order_type === MTS">
                  <div class="seg small">
                    <button type="button" :class="{ on: ln.mode === 'top_up' }" @click="ln.mode = 'top_up'">Top up to</button>
                    <button type="button" :class="{ on: ln.mode === 'make' }" @click="ln.mode = 'make'">Make qty</button>
                  </div>
                </td>
                <td class="num"><input v-model.number="ln.qty" type="number" min="0" step="any" class="form-input qty" /></td>
                <td class="sub">{{ ln.label || (form.order_type === MTS ? (ln.mode === 'make' ? 'make this much more' : 'stock level to reach') : 'typed in') }}</td>
                <td class="act"><button class="icon-btn" :aria-label="`Remove line ${i + 1}`" @click="form.lines.splice(i, 1)"><i class="pi pi-times"></i></button></td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="card info">
          At every level the plan uses, in order: <b>the project's own free stock</b> → <b>what's already coming</b> (open
          orders and requests, drafts too) → <b>other projects' free purchased stock</b>, reserved. Only the rest is made or
          bought, rounded up.
        </div>

        <div class="actions">
          <button class="btn btn-outline" @click="reset">Clear</button>
          <button class="btn btn-primary" :disabled="!canCheck || busy" @click="check">{{ busy ? 'Checking stock…' : 'Check stock and build plan' }}</button>
        </div>
      </section>

      <!-- ── 2 · proposal ──────────────────────────────────────────────────── -->
      <section v-else-if="step === 'proposal'" class="stack">
        <div v-for="(p, pi) in proposals" :key="pi" class="stack">
          <div class="prop-head">
            <div>
              <h2 class="h2">
                Plan for {{ p.project.project_name || p.project.project }}
                <span v-if="!p.project.exists" class="badge badge-info">will be created</span>
              </h2>
              <div class="sub">
                {{ p.project.project_type }} · {{ p.order_type }}
                <template v-if="p.sales_order"> · {{ p.sales_order }}</template>
                <template v-if="p.project.family"> · family {{ p.project.family }} · {{ p.project.period }}</template>
                · needed by {{ p.needed_by }}
              </div>
            </div>
            <div class="rules">
              <span class="badge" :class="p.rules.explode ? 'badge-info' : 'badge-muted'">{{ p.rules.explode ? 'Makes down the BOMs' : 'Buys only' }}</span>
              <span class="badge" :class="p.rules.borrow ? 'badge-info' : 'badge-muted'">{{ p.rules.borrow ? 'Borrows purchased stock' : "Doesn't borrow" }}</span>
              <span class="badge" :class="p.rules.reserve_own ? 'badge-info' : 'badge-muted'">{{ p.rules.reserve_own ? 'Holds own stock for the order' : 'Own stock stays free' }}</span>
            </div>
          </div>

          <div class="stats">
            <div class="stat"><div class="stat__v">{{ fmt(p.totals.own) }}</div><div class="stat__l">Own stock used</div></div>
            <div class="stat"><div class="stat__v">{{ fmt(p.totals.coming) }}</div><div class="stat__l">Already coming</div></div>
            <div class="stat warn"><div class="stat__v">{{ fmt(p.totals.reserve) }}</div><div class="stat__l">Reserved from other projects</div></div>
            <div class="stat dark"><div class="stat__v">{{ p.totals.requests }}</div><div class="stat__l">draft requests · {{ p.totals.request_lines }} lines</div></div>
          </div>

          <div v-for="(w, wi) in p.warnings" :key="wi" class="alert alert-warning" role="status">{{ w }}</div>

          <div class="table-wrap">
            <table class="data-table levels">
              <thead>
                <tr>
                  <th>Level · item</th><th>Need worked out as</th>
                  <th class="num">Need</th><th class="num">Own</th><th class="num">Coming</th><th class="num">Reserve</th>
                  <th class="num">Shortfall</th><th class="num">Request</th><th>Covered by</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="r in p.levels" :key="r.item">
                  <td :style="{ paddingLeft: `${12 + r.depth * 18}px` }">
                    <div class="lvl">{{ r.depth + 1 }} · {{ (r.stage || '').toUpperCase() }}</div>
                    <div class="item">{{ r.item }}</div>
                  </td>
                  <td class="sub mono">{{ r.how.join(' + ') }}</td>
                  <td class="num">{{ fmt(r.need, 2) }}</td>
                  <td class="num" :class="{ muted: !r.own }">{{ fmt(r.own, 2) }}<div v-if="r.held" class="sub">{{ fmt(r.held) }} already held</div></td>
                  <td class="num" :class="{ muted: !r.coming }" :title="r.coming_from.join('\n')">{{ fmt(r.coming, 2) }}</td>
                  <td class="num" :class="r.reserve ? 'orange' : 'muted'">
                    {{ fmt(r.reserve, 2) }}<div v-if="r.reserve_from.length" class="sub">from {{ r.reserve_from.join(', ') }}</div>
                  </td>
                  <td class="num">{{ fmt(r.short, 2) }}</td>
                  <td class="num"><b>{{ fmt(r.request) }}</b></td>
                  <td class="cover">
                    <template v-if="r.made">
                      <div v-if="r.bom_options.length" class="sub bom">
                        BOM
                        <select class="svc" :value="r.bom" :aria-label="`BOM for ${r.item}`" @change="setBom(r.item, $event.target.value)">
                          <option v-for="b in r.bom_options" :key="b" :value="b">{{ b }}</option>
                        </select>
                        <span v-if="r.process_loss"> · {{ fmt(r.process_loss, 2) }}% process loss</span>
                      </div>
                      <div class="seg small">
                        <button type="button" :class="{ on: r.route !== 'Job work' }" @click="setRoute(r.item, 'In-house')">In-house</button>
                        <button type="button" :class="{ on: r.route === 'Job work' }" @click="setRoute(r.item, 'Job work')">Job work</button>
                      </div>
                      <div v-if="!r.request" class="sub">nothing to make</div>
                      <div v-else-if="r.route === 'Job work'" class="sub">
                        Purchase request ·
                        <select class="svc" :value="r.service" @change="setService(r.item, $event.target.value)">
                          <option v-for="s in r.service_options" :key="s" :value="s">{{ s }}</option>
                        </select>
                        · {{ fmt(r.request) }} <span v-if="r.service_from">({{ r.service_from }})</span>
                      </div>
                      <div v-else class="sub">Manufacture request · {{ fmt(r.request) }} {{ r.uom }}</div>
                    </template>
                    <template v-else>
                      <div class="sub">{{ r.request ? `Purchase request · ${fmt(r.request)} ${r.uom}` : 'nothing to buy' }}</div>
                      <div v-if="r.request && r.arrives_by" class="sub" :title="r.lead_source">
                        {{ r.supplier || 'Usual supplier' }} · {{ fmt(r.lead_days) }} days → arrives ~{{ day(r.arrives_by) }}
                      </div>
                    </template>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="two">
            <div class="card">
              <div class="card__title">Reservations made on Create</div>
              <p v-if="!p.reservations.length" class="sub">None.</p>
              <div v-for="(g, gi) in groupReservations(p.reservations)" :key="gi" class="kv" :class="{ orange: g.kind === 'borrow' }">
                <span>{{ g.item_code }} · {{ g.kind === 'own' ? 'own stock' : `from ${g.project}` }} · {{ g.count }} {{ g.count === 1 ? 'lot' : 'lots/rolls' }}</span>
                <b>{{ fmt(g.qty, 2) }}</b>
              </div>
            </div>
            <div class="card">
              <div class="card__title">Draft Material Requests</div>
              <p v-if="!p.totals.requests" class="sub">None — stock covers the plan.</p>
              <template v-for="(lines, kind) in p.requests" :key="kind">
                <div v-if="lines.length" class="kv">
                  <span>{{ kind === 'Job work' ? 'Purchase · job work' : kind === 'Purchase' ? 'Purchase · materials' : 'Manufacture' }}:
                    {{ lines.map((l) => `${l.item_code} ${fmt(l.qty)}`).join(' · ') }}</span>
                  <b>{{ lines.length }} {{ lines.length === 1 ? 'line' : 'lines' }}</b>
                </div>
              </template>
            </div>
          </div>
        </div>

        <div class="actions spread">
          <span class="sub">Requests are created as drafts for review; stock is re-checked when you click Create.</span>
          <div class="actions">
            <button class="btn btn-outline" @click="step = 'start'">Change plan</button>
            <button class="btn btn-primary" :disabled="busy" @click="create">{{ busy ? 'Creating…' : createLabel }}</button>
          </div>
        </div>
      </section>

      <!-- ── 3 · created ───────────────────────────────────────────────────── -->
      <section v-else class="stack">
        <div v-for="(c, ci) in created" :key="ci" class="card">
          <div class="card__title">{{ c.project_name || c.project }} · created</div>
          <p class="sub">{{ c.reservations.length }} reservations · {{ c.requests.length }} draft Material Requests — review and submit them.</p>
          <div class="kv" v-for="m in c.requests" :key="m.name">
            <span><a :href="deskUrl(`/app/material-request/${m.name}`)" target="_blank">{{ m.name }}</a> · {{ m.kind === 'Job work' ? 'Purchase · job work' : m.kind }}</span>
            <b>{{ m.lines }} {{ m.lines === 1 ? 'line' : 'lines' }}</b>
          </div>
          <div class="actions">
            <a class="btn btn-primary" :href="`${APP_BASE}/project-planning?project=${encodeURIComponent(c.project)}&tab=overview`">Open {{ c.project }}</a>
          </div>
        </div>
        <div class="actions"><button class="btn btn-outline" @click="reset">Plan another</button></div>
      </section>
    </main>
  </div>
</template>

<script setup>
import { deskUrl } from '@/config/backend'
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import AppHeader from '@/components/AppHeader.vue'
import LinkField from '@/components/LinkField.vue'
import { callMessage } from '@/api/frappe'
import { APP_BASE } from '@/config/app'

const MTO = 'Made to order'
const MTS = 'Made to stock'
const ORDER_TYPES = [MTO, MTS]
const route = useRoute()

// Embedded as the Project Planning page's "Plan" tab (forProject set) or its "New plan" view
// (embedded, no project: made to stock). On Create it tells the page which project to open.
const props = defineProps({
  embedded: { type: Boolean, default: false },
  forProject: { type: String, default: '' },
  prefill: { type: Object, default: null },
})
const emit = defineEmits(['created'])

const blank = () => ({ order_type: MTO, project: '', sales_order: '', needed_by: '', lines: [{ item: '', qty: null, mode: 'need' }], routes: {}, services: {}, boms: {} })
const form = reactive(blank())
const step = ref('start')
const proposals = ref([])
const created = ref([])
const soInfo = ref(null)
const busy = ref(false)
const error = ref('')

const fmt = (n, d = 0) => Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: d })
const day = (d) => (d ? new Date(`${d}T00:00:00`).toLocaleDateString(undefined, { day: 'numeric', month: 'short' }) : '')
const canCheck = computed(() => form.lines.some((l) => l.item && l.qty > 0) && (form.order_type === MTS || form.project))
const createLabel = computed(() => {
  const res = proposals.value.reduce((a, p) => a + p.reservations.length, 0)
  const req = proposals.value.reduce((a, p) => a + p.totals.requests, 0)
  return `Create ${res} reservation${res === 1 ? '' : 's'} and ${req} draft request${req === 1 ? '' : 's'}`
})

function addLine() {
  form.lines.push({ item: '', qty: null, mode: form.order_type === MTS ? 'top_up' : 'need' })
}
function reset() {
  Object.assign(form, blank())
  proposals.value = []
  created.value = []
  soInfo.value = null
  error.value = ''
  step.value = 'start'
}
async function searchProjects(txt) {
  return await callMessage('pranera_planning.api.plan.search_plan_projects', { txt })
}
async function loadSalesOrder() {
  busy.value = true
  error.value = ''
  try {
    const so = await callMessage('pranera_planning.api.plan.sales_order_lines', { sales_order: form.sales_order })
    soInfo.value = so
    form.lines = so.lines.map((l) => ({ item: l.item, qty: l.qty, mode: 'need', label: l.label }))
    if (!form.needed_by && so.delivery_date) form.needed_by = so.delivery_date
    if (!form.project && so.project) form.project = so.project
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}
function payload() {
  return {
    order_type: form.order_type, project: form.project || null,
    sales_order: form.order_type === MTO ? form.sales_order : null, needed_by: form.needed_by || null,
    lines: form.lines.filter((l) => l.item && l.qty > 0)
      .map((l) => ({ item: l.item, qty: l.qty, mode: form.order_type === MTS ? l.mode : 'need', label: l.label })),
    routes: form.routes, services: form.services, boms: form.boms,
  }
}
async function check() {
  busy.value = true
  error.value = ''
  try {
    proposals.value = await callMessage('pranera_planning.api.plan.preview', { payload: payload() })
    step.value = 'proposal'
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}
function setRoute(item, r) { form.routes[item] = r; check() }
function setService(item, s) { form.services[item] = s; check() }
function setBom(item, b) { form.boms[item] = b; check() }
function groupReservations(list) {
  const g = new Map()
  for (const r of list) {
    const k = `${r.item_code}|${r.kind}|${r.project}`
    if (!g.has(k)) g.set(k, { item_code: r.item_code, kind: r.kind, project: r.project, qty: 0, count: 0 })
    const e = g.get(k); e.qty += r.qty; e.count += 1
  }
  return [...g.values()]
}
async function create() {
  busy.value = true
  error.value = ''
  try {
    created.value = await callMessage('pranera_planning.api.plan.create_plan', { payload: payload() })
    step.value = 'created'
    if (props.embedded && created.value.length) emit('created', created.value)
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}

async function loadDefaults(project) {
  // The project's own plan: made to order → its Sales Order's open lines; made to stock → its saved targets.
  busy.value = true
  error.value = ''
  try {
    const d = await callMessage('pranera_planning.api.plan.plan_defaults', { project })
    reset()
    form.order_type = d.order_type
    form.project = project
    form.sales_order = d.sales_order || ''
    form.needed_by = d.needed_by || ''
    if (d.lines.length) form.lines = d.lines.map((l) => ({ item: l.item, qty: l.qty, mode: l.mode, label: l.label }))
    if (d.sales_order) soInfo.value = d.sales_order_info
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}

watch(() => props.forProject, (p) => { if (props.embedded && p) loadDefaults(p) }, { immediate: true })

onMounted(() => {
  if (props.embedded && !props.forProject) {
    form.order_type = MTS
    form.lines = [{ item: '', qty: null, mode: 'top_up' }]
  }
  // From the re-order report's Plan button: ?item=…&qty=…&mode=make (or the page's prefill)
  const q = props.prefill || route.query
  if (q.item) {
    form.order_type = q.order_type === MTO ? MTO : MTS
    form.lines = [{ item: String(q.item), qty: Number(q.qty) || null, mode: q.mode === 'top_up' ? 'top_up' : 'make', label: 'from the re-order report' }]
  }
})
</script>

<style scoped>
.stack { display: flex; flex-direction: column; gap: 16px; }
.start-row { display: flex; gap: 16px; align-items: flex-end; flex-wrap: wrap; }
.field { display: flex; flex-direction: column; gap: 6px; width: 220px; }
.field.wide { width: 320px; }
.seg-field { border: 0; margin: 0; padding: 0; }
.seg { display: inline-flex; border: 1px solid var(--slate-200); border-radius: 8px; overflow: hidden; background: #fff; }
.seg button { border: 0; background: transparent; padding: 0 16px; height: 40px; font: inherit; font-size: 14px; cursor: pointer; }
.seg button.on { background: var(--primary); color: #fff; font-weight: 600; }
.seg.small button { height: 30px; padding: 0 10px; font-size: 13px; }
.note { font-size: 13px; color: var(--slate-500); margin: 0; }
.card__head { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 8px; }
.sub { font-size: 12px; color: var(--slate-500); }
.lines .item-cell { min-width: 320px; }
.form-input.qty { width: 130px; text-align: right; }
.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.act { text-align: right; }
.icon-btn { border: 0; background: transparent; cursor: pointer; color: var(--slate-500); padding: 4px; }
.info { font-size: 13px; color: var(--slate-500); }
.actions { display: flex; gap: 12px; justify-content: flex-end; align-items: center; }
.actions.spread { justify-content: space-between; }
.prop-head { display: flex; justify-content: space-between; gap: 16px; align-items: flex-end; flex-wrap: wrap; }
.h2 { margin: 0; font-size: 18px; font-weight: 650; display: flex; gap: 10px; align-items: center; }
.rules { display: flex; gap: 6px; flex-wrap: wrap; }
.badge-muted { background: var(--slate-100); color: var(--slate-500); }
.stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.stat.warn { background: #fff7ed; border-color: #f3c79a; }
.stat.dark { background: var(--primary); color: #fff; }
.stat.dark .stat__l { color: #c9d6e6; }
.levels { font-size: 13px; }
.levels th { white-space: nowrap; font-size: 11px; text-transform: uppercase; letter-spacing: 0.03em; }
.lvl { font-size: 11px; font-weight: 600; color: var(--primary); }
.item { font-weight: 600; }
.mono { font-variant-numeric: tabular-nums; }
.muted { color: var(--slate-400); }
.orange { color: #9a3412; }
.cover { min-width: 260px; }
.cover .sub { margin-top: 4px; }
.bom { margin: 0 0 6px; }
.svc { font: inherit; font-size: 12px; padding: 1px 4px; border: 1px solid var(--slate-200); border-radius: 6px; }
.two { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.kv { display: flex; justify-content: space-between; gap: 16px; font-size: 14px; padding: 4px 0; }
.alert-warning { background: #fff7ed; border: 1px solid #f3c79a; color: #7c2d12; border-radius: 8px; padding: 10px 14px; font-size: 13px; }
</style>
