<template>
  <div class="page">
    <AppHeader subtitle="Reserve stock bought for one project to another project's production" />

    <main class="page-content">
      <div class="page-toolbar">
        <div class="picker">
          <label class="form-label" for="pp">Project</label>
          <div class="picker__row">
            <LinkField
              id="pp" v-model="project" doctype="Project" placeholder="e.g. 26PTIN1710"
              :search-fn="searchProjects" empty-label="No project with received or reserved stock found"
              @change="load"
            />
            <button class="btn btn-primary" :disabled="!project || loading" @click="load">Show stock</button>
          </div>
          <div class="types" role="group" aria-label="Project type">
            <label v-for="t in PROJECT_TYPES" :key="t" class="check">
              <input v-model="types[t]" type="checkbox" /> {{ t }}
            </label>
          </div>
          <p class="hint">{{ typeHint }}</p>
        </div>
      </div>

      <div v-if="error" class="alert alert-error" role="alert">{{ error }}</div>
      <div v-if="loading" class="loading-center"><div class="spinner"></div></div>

      <div v-else-if="!data" class="card">
        <div class="empty-state">
          <div class="empty-state__title">Choose a project</div>
          <div class="empty-state__sub">You will see the stock received under it and what is still free to reserve, and for a production project, the stock reserved for it.</div>
        </div>
      </div>

      <div v-else-if="!data.rows.length && !data.reserved_for.length" class="card">
        <div class="empty-state">
          <div class="empty-state__title">Nothing received under or reserved for {{ data.project }}</div>
          <div class="empty-state__sub">Stock shows here once it is received through a submitted Purchase Receipt with this project, or reserved for it from another project.</div>
        </div>
      </div>

      <template v-else>
        <section v-if="data.reserved_for.length" class="section">
          <h2 class="section__h">Reserved for {{ data.project }}</h2>
          <div class="stats">
            <div v-for="s in reservedStats" :key="s.label" class="stat">
              <div class="stat__v">{{ fmt(s.value) }}</div>
              <div class="stat__l">{{ s.label }}</div>
            </div>
          </div>
          <div class="table-wrap">
            <table class="data-table">
              <thead>
                <tr>
                  <th>From project</th>
                  <th>Item / batch</th>
                  <th>Where</th>
                  <th class="num">Reserved</th>
                  <th class="num">Issued</th>
                  <th class="num">Remaining</th>
                  <th class="num">Still in stores</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="x in data.reserved_for" :key="x.name">
                  <td>
                    <button class="link-btn primary" :title="`Show ${x.purchase_project}'s stock`" @click="openProject(x.purchase_project)">{{ x.purchase_project }}</button>
                    <div class="sub">{{ x.name }}<template v-if="x.sales_order"> · {{ x.sales_order }}</template></div>
                  </td>
                  <td>
                    <div class="item">{{ x.item_name || x.item_code }}</div>
                    <div class="sub">{{ x.batch_no }}</div>
                  </td>
                  <td>
                    {{ x.warehouse }}
                    <div v-if="x.roll_no" class="sub">Roll {{ x.roll_no }}</div>
                  </td>
                  <td class="num">{{ fmt(x.reserved_qty) }} <span class="uom">{{ x.uom }}</span></td>
                  <td class="num">{{ fmt(x.issued_qty) }}</td>
                  <td class="num"><strong>{{ fmt(x.remaining_qty) }}</strong></td>
                  <td class="num">
                    <span v-if="x.in_stores_qty + 1e-6 < x.remaining_qty" class="badge badge-warning" title="Less is in stores at this location than is still reserved">{{ fmt(x.in_stores_qty) }}</span>
                    <span v-else>{{ fmt(x.in_stores_qty) }}</span>
                  </td>
                  <td class="act"><button class="link-btn" @click="release(x)">Release</button></td>
                </tr>
              </tbody>
            </table>
          </div>
          <p class="note">Remaining goes down as {{ data.project }}'s work orders issue the batch from that warehouse.</p>
        </section>

        <section v-if="data.rows.length" class="section">
        <h2 v-if="data.reserved_for.length" class="section__h">Received under {{ data.project }}</h2>
        <div class="stats">
          <div v-for="s in stats" :key="s.label" class="stat">
            <div class="stat__v">{{ fmt(s.value) }}</div>
            <div class="stat__l">{{ s.label }}</div>
          </div>
        </div>

        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th></th>
                <th>Item / batch</th>
                <th class="num">Received</th>
                <th class="num">Used by {{ data.project }}</th>
                <th class="num">Used by other projects</th>
                <th class="num">In stores</th>
                <th class="num">Reserved</th>
                <th class="num">Free</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <template v-for="r in data.rows" :key="r.batch_no">
                <tr>
                  <td class="tog">
                    <button class="icon" :aria-label="open[r.batch_no] ? 'Hide details' : 'Show details'" @click="open[r.batch_no] = !open[r.batch_no]">
                      <i :class="open[r.batch_no] ? 'pi pi-chevron-down' : 'pi pi-chevron-right'"></i>
                    </button>
                  </td>
                  <td>
                    <div class="item">{{ r.item_name || r.item_code }}</div>
                    <div class="sub">
                      {{ r.batch_no }}
                      <span class="level" :title="r.roll_tracked ? 'Reserved by warehouse, batch and roll' : 'Reserved by warehouse and batch'">
                        {{ r.roll_tracked ? 'By roll' : 'By batch' }}
                      </span>
                    </div>
                  </td>
                  <td class="num">{{ fmt(r.received_qty) }} <span class="uom">{{ r.uom }}</span></td>
                  <td class="num">{{ fmt(r.used_own_qty) }}</td>
                  <td class="num">{{ fmt(sum(r.used_other)) }}</td>
                  <td class="num">{{ fmt(r.available_qty) }}</td>
                  <td class="num"><span v-if="r.reserved_remaining > 0" class="badge badge-warning">{{ fmt(r.reserved_remaining) }}</span><span v-else>0</span></td>
                  <td class="num"><strong>{{ fmt(r.free_qty) }}</strong></td>
                  <td class="act"><button class="btn btn-outline sm" :disabled="r.free_qty <= 0" @click="openDialog(r)">Reserve</button></td>
                </tr>

                <tr v-if="open[r.batch_no]" class="detail">
                  <td></td>
                  <td colspan="8">
                    <div class="detail__h">Stock by warehouse{{ r.roll_tracked ? ' and roll' : '' }}</div>
                    <p v-if="!r.locations.length" class="muted">None of this batch is in a stores warehouse.</p>
                    <table v-else class="mini locs">
                      <thead>
                        <tr>
                          <th>{{ r.roll_tracked ? 'Warehouse / roll' : 'Warehouse' }}</th>
                          <th class="num">In stores</th><th class="num">Reserved</th><th class="num">Free</th><th></th>
                        </tr>
                      </thead>
                      <tbody>
                        <template v-for="l in r.locations" :key="l.warehouse">
                          <tr :class="{ wh: r.roll_tracked }">
                            <td>{{ l.warehouse }}</td>
                            <td class="num">{{ fmt(l.available_qty) }}</td>
                            <td class="num">{{ fmt(l.reserved_remaining) }}</td>
                            <td class="num">{{ fmt(l.free_qty) }}</td>
                            <td class="act">
                              <button v-if="!r.roll_tracked" class="link-btn primary" :disabled="l.free_qty <= 0" @click="openDialog(r, { warehouse: l.warehouse })">Reserve</button>
                            </td>
                          </tr>
                          <template v-if="r.roll_tracked">
                            <tr v-for="x in l.rolls" :key="l.warehouse + x.roll_no" class="roll">
                              <td>Roll {{ x.roll_no }}</td>
                              <td class="num">{{ fmt(x.qty) }}</td>
                              <td class="num">{{ fmt(x.reserved_remaining) }}</td>
                              <td class="num">{{ fmt(x.free_qty) }}</td>
                              <td class="act">
                                <button class="link-btn primary" :disabled="x.free_qty <= 0" @click="openDialog(r, { warehouse: l.warehouse, roll_no: x.roll_no })">Reserve</button>
                              </td>
                            </tr>
                            <tr v-if="l.unnumbered.qty > 0 || l.unnumbered.reserved_remaining > 0" class="roll">
                              <td>Rolls with no roll no. on record</td>
                              <td class="num">{{ fmt(l.unnumbered.qty) }}</td>
                              <td class="num">{{ fmt(l.unnumbered.reserved_remaining) }}</td>
                              <td class="num">{{ fmt(l.unnumbered.free_qty) }}</td>
                              <td class="act">
                                <button class="link-btn primary" :disabled="l.unnumbered.free_qty <= 0" @click="openDialog(r, { warehouse: l.warehouse, roll_no: '' })">Reserve</button>
                              </td>
                            </tr>
                          </template>
                        </template>
                      </tbody>
                    </table>

                    <div class="detail__grid">
                      <div>
                        <div class="detail__h">Reservations</div>
                        <p v-if="!r.reservations.length" class="muted">Nothing reserved on this batch.</p>
                        <table v-else class="mini">
                          <thead><tr><th>Reserved for</th><th>Where</th><th class="num">Reserved</th><th class="num">Issued</th><th class="num">Remaining</th><th></th></tr></thead>
                          <tbody>
                            <tr v-for="x in r.reservations" :key="x.name">
                              <td>{{ x.production_project }} <span class="sub">{{ x.name }}</span></td>
                              <td>{{ x.warehouse || '—' }}<span v-if="x.roll_no" class="sub"> · roll {{ x.roll_no }}</span></td>
                              <td class="num">{{ fmt(x.reserved_qty) }}</td>
                              <td class="num">{{ fmt(x.issued_qty) }}</td>
                              <td class="num">{{ fmt(x.remaining_qty) }}</td>
                              <td class="act">
                                <button class="link-btn" @click="release(x)">Release</button>
                              </td>
                            </tr>
                          </tbody>
                        </table>
                      </div>
                      <div>
                        <div class="detail__h">Used by other projects</div>
                        <p v-if="!r.used_other.length" class="muted">No other project has used this batch.</p>
                        <table v-else class="mini">
                          <thead><tr><th>Project</th><th class="num">Qty</th></tr></thead>
                          <tbody><tr v-for="u in r.used_other" :key="u.project"><td>{{ u.project }}</td><td class="num">{{ fmt(u.qty) }}</td></tr></tbody>
                        </table>
                      </div>
                    </div>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
        <p class="note">
          "In stores" is stock in issuable warehouses; stock already in WIP or at a subcontractor is counted as used.
          Reserved stock cannot be issued to any other project.
        </p>
        </section>
      </template>
    </main>

    <div v-if="dlg.row" class="overlay" @mousedown.self="closeDialog">
      <form class="dialog" @submit.prevent="save">
        <h2>Reserve stock</h2>
        <p class="sub">{{ dlg.row.item_name || dlg.row.item_code }} · {{ dlg.row.batch_no }}</p>
        <p class="sub">
          Reserved by {{ dlg.row.roll_tracked ? 'warehouse, batch and roll' : 'warehouse and batch' }}.
          Free here: <strong>{{ fmt(dlgFree) }} {{ dlg.row.uom }}</strong>
        </p>

        <div class="form-group">
          <label class="form-label" for="wh">Warehouse</label>
          <select id="wh" v-model="dlg.warehouse" class="form-input" @change="onLocationChange">
            <option v-for="l in dlgWarehouses" :key="l.warehouse" :value="l.warehouse">
              {{ l.warehouse }} ({{ fmt(l.free_qty) }} free)
            </option>
          </select>
        </div>
        <div v-if="dlg.row.roll_tracked" class="form-group">
          <label class="form-label" for="roll">Roll no.</label>
          <input
            id="roll" v-model.trim="dlg.roll_no" class="form-input" list="roll-options" autocomplete="off"
            placeholder="Pick a roll or type its number" @change="onLocationChange"
          />
          <datalist id="roll-options">
            <option v-for="x in dlgRolls" :key="x.roll_no" :value="x.roll_no">{{ fmt(x.free_qty) }} free</option>
          </datalist>
          <p class="hint">{{ rollHint }}</p>
        </div>

        <div class="form-group">
          <label class="form-label" for="prod">Reserve for project</label>
          <LinkField
            id="prod" v-model="dlg.production_project" doctype="Project" title-field="project_name"
            :filters="[['Project', 'project_type', '=', 'Production'], ['Project', 'status', '=', 'Open']]"
            placeholder="Production project" empty-label="No open Production project found"
          />
          <p class="hint">Open projects typed Production only.</p>
        </div>
        <div class="form-group">
          <label class="form-label" for="qty">Quantity ({{ dlg.row.uom }})</label>
          <input id="qty" v-model.number="dlg.qty" type="number" min="0" step="any" class="form-input" />
        </div>
        <div class="form-group">
          <label class="form-label" for="rem">Remarks</label>
          <input id="rem" v-model="dlg.remarks" class="form-input" />
        </div>

        <div v-if="dlg.error" class="alert alert-error" role="alert">{{ dlg.error }}</div>

        <div class="dialog__foot">
          <button type="button" class="btn btn-outline" @click="closeDialog">Cancel</button>
          <button type="submit" class="btn btn-primary" :disabled="dlg.saving || !canSave">
            {{ dlg.saving ? 'Reserving…' : 'Reserve' }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppHeader from '@/components/AppHeader.vue'
import LinkField from '@/components/LinkField.vue'
import { callMessage, createDoc, updateDoc } from '@/api/frappe'

// Only Projects that actually have a received batch — plain Project search would include
// every project in the system, most of which never had anything bought under them and only
// lead to "No stock received under this project" if picked here.
const PROJECT_TYPES = ['Purchase', 'Production']
const types = reactive({ Purchase: true, Production: true })
const selectedTypes = computed(() => PROJECT_TYPES.filter((t) => types[t]))

// Both ticked, or neither, means no type filter (unclassified projects included).
const typeHint = computed(() => {
  const t = selectedTypes.value
  if (t.length === 1) return `Projects with received stock, typed ${t[0]}.`
  return 'Projects with received stock, any type — including ones not yet classified.'
})

async function searchProjects(txt) {
  const t = selectedTypes.value
  return await callMessage('pranera_planning.api.reservation.search_purchase_projects', {
    txt, project_types: t.length === 1 ? t : [],
  })
}

const route = useRoute()
const router = useRouter()

const project = ref('')
const data = ref(null)
const loading = ref(false)
const error = ref('')
const open = reactive({})

const dlg = reactive({
  row: null, warehouse: '', roll_no: '', production_project: '', qty: 0, remarks: '', saving: false, error: '',
})

const fmt = (n) => Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 3 })
const sum = (list) => list.reduce((a, x) => a + x.qty, 0)

const stats = computed(() => {
  const t = data.value?.totals
  return t ? [
    { label: 'Received', value: t.received_qty },
    { label: 'Used by this project', value: t.used_own_qty },
    { label: 'Used by other projects', value: t.used_other_qty },
    { label: 'In stores', value: t.available_qty },
    { label: 'Reserved', value: t.reserved_remaining },
    { label: 'Free to reserve', value: t.free_qty },
  ] : []
})

const reservedStats = computed(() => {
  const t = data.value?.reserved_totals
  return t ? [
    { label: 'Reserved', value: t.reserved_qty },
    { label: 'Issued', value: t.issued_qty },
    { label: 'Remaining', value: t.remaining_qty },
    { label: 'Still in stores', value: t.in_stores_qty },
  ] : []
})

// A different (or cleared) project must never leave the previous project's figures on screen.
watch(project, (v) => {
  if (data.value && v !== data.value.project) data.value = null
})

function openProject(name) {
  project.value = name
  load()
}

async function load() {
  if (!project.value) return
  loading.value = true
  error.value = ''
  try {
    data.value = await callMessage('pranera_planning.api.reservation.get_purchase_project_stock', { project: project.value })
    router.replace({ query: { project: project.value } })
  } catch (e) {
    error.value = e.message
    data.value = null
  } finally {
    loading.value = false
  }
}

// ── Reserve dialog: warehouse (+ roll) ───────────────────────────────────────
const dlgWarehouses = computed(() => {
  const locs = dlg.row?.locations || []
  return locs.filter((l) => l.free_qty > 0 || l.warehouse === dlg.warehouse)
})
const dlgLocation = computed(() => (dlg.row?.locations || []).find((l) => l.warehouse === dlg.warehouse) || null)
const dlgRolls = computed(() => (dlgLocation.value?.rolls || []).filter((x) => x.free_qty > 0))
const dlgKnownRoll = computed(() => (dlgLocation.value?.rolls || []).find((x) => x.roll_no === dlg.roll_no) || null)

// What the server will let this reservation hold (it caps anything above this).
const dlgFree = computed(() => {
  const l = dlgLocation.value
  if (!l) return 0
  if (!dlg.row.roll_tracked) return l.free_qty
  if (dlgKnownRoll.value) return dlgKnownRoll.value.free_qty
  return l.unnumbered?.free_qty || 0
})

const rollHint = computed(() => {
  const l = dlgLocation.value
  if (!l) return ''
  if (!dlg.roll_no) {
    return dlgRolls.value.length
      ? `${dlgRolls.value.length} numbered roll(s) free here. A roll not in the list is taken from stock with no roll no. on record.`
      : 'No numbered rolls on record here — type the roll no. from the roll tag.'
  }
  if (dlgKnownRoll.value) return `Roll ${dlg.roll_no}: ${fmt(dlgKnownRoll.value.qty)} in stock, ${fmt(dlgKnownRoll.value.free_qty)} free.`
  return `Roll ${dlg.roll_no} has no record in this warehouse yet — reserved out of the ${fmt(l.unnumbered?.free_qty)} with no roll no. on record.`
})

const canSave = computed(() =>
  !!dlg.production_project && !!dlg.warehouse && dlg.qty > 0 && (!dlg.row?.roll_tracked || !!dlg.roll_no),
)

function onLocationChange() { dlg.qty = dlgFree.value }

function openDialog(row, at = {}) {
  const first = row.locations.find((l) => l.free_qty > 0)
  Object.assign(dlg, {
    row,
    warehouse: at.warehouse || first?.warehouse || '',
    roll_no: at.roll_no || '',
    production_project: '', remarks: '', saving: false, error: '',
  })
  dlg.qty = dlgFree.value
}
function closeDialog() { dlg.row = null }

async function save() {
  dlg.saving = true
  dlg.error = ''
  try {
    await createDoc('Project Stock Reservation', {
      purchase_project: data.value.project,
      production_project: dlg.production_project,
      item_code: dlg.row.item_code,
      batch_no: dlg.row.batch_no,
      warehouse: dlg.warehouse,
      roll_no: dlg.row.roll_tracked ? dlg.roll_no : '',
      reserved_qty: dlg.qty,
      remarks: dlg.remarks,
    })
    const batch = dlg.row.batch_no
    closeDialog()
    await load()
    open[batch] = true
  } catch (e) {
    dlg.error = e.message
  } finally {
    dlg.saving = false
  }
}

async function release(res) {
  if (!confirm(`Release ${res.remaining_qty} reserved for ${res.production_project}? Other projects will be able to use it.`)) return
  try {
    await updateDoc('Project Stock Reservation', res.name, { status: 'Released' })
    await load()
  } catch (e) {
    error.value = e.message
  }
}

onMounted(() => {
  if (typeof route.query.project === 'string' && route.query.project) {
    project.value = route.query.project
    load()
  }
})
</script>

<style scoped>
.picker { width: 440px; max-width: 100%; }
.picker__row { display: flex; gap: 12px; align-items: center; }
.picker__row > :first-child { flex: 1; min-width: 0; }
.picker__row .btn { white-space: nowrap; }
.types { display: flex; gap: 16px; margin-top: 8px; }
.check { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; color: var(--slate-700, #334155); cursor: pointer; }
.check input { width: 15px; height: 15px; accent-color: var(--primary); cursor: pointer; }
.hint { font-size: 12px; color: var(--slate-500); margin-top: 5px; }
.page-toolbar { align-items: flex-end; }

.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin-bottom: 16px; }
.stat { background: #fff; border: 1px solid var(--slate-200); border-radius: var(--radius-md); padding: 12px 14px; }
.stat__v { font-size: 20px; font-weight: 650; font-variant-numeric: tabular-nums; }
.stat__l { font-size: 12px; color: var(--slate-500); margin-top: 2px; }

.tog { width: 36px; padding-right: 0; }
.icon { background: none; border: none; color: var(--slate-500); width: 28px; height: 28px; border-radius: var(--radius-sm); }
.icon:hover { background: var(--slate-100); }
.item { font-weight: 600; }
.sub { font-size: 12px; color: var(--slate-500); }
.uom { font-size: 12px; color: var(--slate-500); }
.act { text-align: right; white-space: nowrap; }
.sm { padding: 5px 12px; font-size: 13px; }
.muted { color: var(--slate-500); font-size: 13px; }
.section + .section { margin-top: 32px; }
.section__h { font-size: 16px; font-weight: 650; margin-bottom: 12px; }
.note { margin-top: 12px; font-size: 13px; color: var(--slate-500); max-width: 80ch; }

.detail td { background: var(--slate-50); }
.detail__grid { display: grid; grid-template-columns: 3fr 2fr; gap: 24px; padding: 4px 0 8px; }
@media (max-width: 900px) { .detail__grid { grid-template-columns: 1fr; } }
.detail__h { font-size: 13px; font-weight: 650; margin-bottom: 6px; }
.mini { width: 100%; border-collapse: collapse; font-size: 13px; font-variant-numeric: tabular-nums; }
.mini th { text-align: left; font-weight: 600; color: var(--slate-500); padding: 4px 8px 4px 0; }
.mini td { padding: 4px 8px 4px 0; border-top: 1px solid var(--slate-200); }
.mini .num { text-align: right; }
.link-btn { background: none; border: none; color: var(--red-600); font-size: 13px; font-weight: 600; }
.link-btn:hover { text-decoration: underline; }
.link-btn.primary { color: var(--primary); }
.link-btn:disabled { color: var(--slate-400); text-decoration: none; cursor: default; }

.level { margin-left: 6px; padding: 1px 6px; border-radius: 4px; font-size: 11px; background: var(--slate-100); color: var(--slate-500); }
.locs { margin-bottom: 16px; }
.locs tr.wh td { font-weight: 600; }
.locs tr.roll td:first-child { padding-left: 18px; color: var(--slate-700, #334155); }

.overlay { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.45); z-index: 400; display: flex; align-items: center; justify-content: center; padding: 16px; }
.dialog { background: #fff; border-radius: var(--radius-lg); padding: 24px; width: 100%; max-width: 420px; box-shadow: var(--shadow-lg); }
.dialog h2 { font-size: 18px; margin-bottom: 4px; }
.dialog .sub { margin-bottom: 4px; }
.dialog .form-group:first-of-type { margin-top: 16px; }
.dialog__foot { display: flex; justify-content: flex-end; gap: 10px; margin-top: 8px; }
</style>
