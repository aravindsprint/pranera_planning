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
              :search-fn="searchProjects" empty-label="No project with received, produced or reserved stock found"
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

      <div v-else-if="!data.rows.length && !data.reserved_for.length && !data.produced_rows.length" class="card">
        <div class="empty-state">
          <div class="empty-state__title">Nothing received, produced or reserved for {{ data.project }}</div>
          <div class="empty-state__sub">Stock shows here once it is received through a submitted Purchase Receipt with this project, produced by its work orders or subcontracting receipts, or reserved for it from another project.</div>
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
                <tr v-for="x in data.reserved_for" :key="x.name" :class="{ done: x.status === 'Fulfilled' }">
                  <td>
                    <button class="link-btn primary" :title="`Show ${x.purchase_project}'s stock`" @click="openProject(x.purchase_project)">{{ x.purchase_project }}</button>
                    <div class="sub">
                      {{ x.name }}<template v-if="x.sales_order"> · {{ x.sales_order }}</template>
                      <span v-if="x.status === 'Fulfilled'" class="level ok">Fulfilled</span>
                    </div>
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
                  <td class="act"><button v-if="x.status === 'Active'" class="link-btn" @click="release(x)">Release</button></td>
                </tr>
              </tbody>
            </table>
          </div>
          <p class="note">
            Remaining goes down as the batch is issued to {{ data.project }} from that warehouse — by its work orders
            (Material Transfer for Manufacture, Manufacture) or its subcontracting orders (Send to Subcontractor against
            a Subcontracting Order whose item, or the Purchase Order item behind it, is for {{ data.project }}).
            A reservation is marked Fulfilled once everything reserved has been issued.
          </p>
        </section>

        <section v-for="sec in batchSections" :key="sec.key" class="section">
        <h2 v-if="sectionCount > 1" class="section__h">{{ sec.title }}</h2>

        <div v-if="sec.key === 'produced' && data.stages.length" class="table-wrap flow">
          <table class="data-table">
            <thead>
              <tr>
                <th>Stage</th>
                <th class="num" title="What the previous stage issued to this project">Input</th>
                <th class="num">Produced</th>
                <th class="num" title="Input minus produced: still being processed, or process loss">Difference</th>
                <th class="num">In stores</th>
                <th class="num">In WIP</th>
                <th class="num">At subcontractor</th>
                <th class="num">Moved on</th>
                <th class="num">To other projects</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="g in data.stages" :key="g.stage">
                <td>
                  <div class="item">{{ g.stage }}</div>
                  <div class="sub">
                    {{ g.batches }} batch{{ g.batches === 1 ? '' : 'es' }}
                    <template v-if="g.shared_step"> · runs alongside {{ siblings(g) }}</template>
                  </div>
                </td>
                <td class="num" :title="g.shared_step ? 'Shared with the stages running alongside it' : ''">{{ g.input_qty ? fmt(g.input_qty) : '—' }}</td>
                <td class="num"><strong>{{ fmt(g.produced_qty) }}</strong> <span class="uom">{{ g.uom }}</span></td>
                <td class="num">
                  <template v-if="g.difference_qty !== null">
                    {{ fmt(g.difference_qty) }}
                    <span v-if="g.input_qty" class="sub">({{ pct(g.difference_qty, g.input_qty) }})</span>
                  </template>
                  <template v-else>—</template>
                </td>
                <td class="num">{{ fmt(g.in_stores_qty) }}</td>
                <td class="num">{{ fmt(g.in_wip_qty) }}</td>
                <td class="num">{{ fmt(g.at_subcontractor_qty) }}</td>
                <td class="num">{{ fmt(g.used_own_qty) }}</td>
                <td class="num">
                  <span v-if="g.used_other_qty > 0" class="badge badge-warning">{{ fmt(g.used_other_qty) }}</span>
                  <span v-else>0</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="stats">
          <div v-for="s in sectionStats(sec)" :key="s.label" class="stat">
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
                <th class="num">{{ sec.qtyLabel }}</th>
                <th class="num">Used by {{ data.project }}</th>
                <th class="num">Used by other projects</th>
                <th class="num">In stores</th>
                <th class="num">Reserved</th>
                <th class="num">Free</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <template v-for="r in sec.rows" :key="r.batch_no">
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
                      <span v-if="r.stage" class="level">{{ r.stage }}</span>
                      <span v-if="r.made_by" class="level">{{ r.made_by }}</span>
                    </div>
                  </td>
                  <td class="num">{{ fmt(r.received_qty) }} <span class="uom">{{ r.uom }}</span></td>
                  <td class="num">{{ fmt(r.used_own_qty) }}</td>
                  <td class="num">{{ fmt(sum(r.used_other)) }}</td>
                  <td class="num">
                    {{ fmt(r.available_qty) }}
                    <div v-for="(q, place) in r.elsewhere" :key="place" class="sub">{{ place }} {{ fmt(q) }}</div>
                  </td>
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
                            <td>
                              {{ l.warehouse }}
                              <div v-if="l.rolls_uncertain" class="sub warn">
                                Part of this batch left without roll numbers — some listed rolls may already be gone.
                              </div>
                            </td>
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
          <template v-if="sec.key === 'produced'">
            Produced stock belongs to {{ data.project }}: another project can take it only once it is reserved for that project here.
            Stages come from the operation that made each batch (its Roll Packing List's job card, else its work order);
            knitted rolls come from submitted Roll Packing Lists.
          </template>
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
          <div class="rolls__head">
            <label class="form-label">Rolls</label>
            <span class="rolls__count">{{ pickedRolls.length }} of {{ dlgRolls.length }} selected</span>
          </div>
          <template v-if="dlgRolls.length">
            <div class="rolls__tools">
              <input v-model.trim="dlg.rollSearch" class="form-input sm" placeholder="Search roll no." autocomplete="off" />
              <button type="button" class="link-btn primary" @click="selectAllRolls">Select all free</button>
              <button type="button" class="link-btn" :disabled="!pickedRolls.length" @click="clearRolls">Clear</button>
            </div>
            <div class="rolls__list" role="group" aria-label="Rolls">
              <label v-for="x in shownRolls" :key="x.roll_no" class="rolls__item" :class="{ on: dlg.picked[x.roll_no] }">
                <input v-model="dlg.picked[x.roll_no]" type="checkbox" />
                <span class="rolls__no">{{ x.roll_no }}</span>
                <span class="rolls__qty">{{ fmt(x.free_qty) }}<template v-if="x.free_qty < x.qty"> of {{ fmt(x.qty) }}</template> {{ dlg.row.uom }}</span>
              </label>
              <p v-if="!shownRolls.length" class="muted">No roll matches “{{ dlg.rollSearch }}”.</p>
            </div>
          </template>
          <p v-else class="hint">No numbered rolls on record in this warehouse.</p>

          <label class="form-label other" for="other-roll">Roll not in the list</label>
          <input
            id="other-roll" v-model.trim="dlg.otherRoll" class="form-input" autocomplete="off"
            placeholder="Type its roll no. (optional)"
          />
          <p class="hint">{{ otherRollHint }}</p>
          <p v-if="rollsUncertain" class="hint warn">Part of this batch left without roll numbers — some listed rolls may already be gone.</p>
        </div>

        <div class="form-group">
          <label class="form-label" for="prod">Reserve for project</label>
          <LinkField
            id="prod" v-model="dlg.production_project" doctype="Project" title-field="project_name"
            :filters="[['Project', 'project_type', '=', 'Production'], ['Project', 'status', '=', 'Open'], ['Project', 'name', '!=', data.project]]"
            placeholder="Production project" empty-label="No open Production project found"
          />
          <p class="hint">Open projects typed Production only, other than {{ data.project }}.</p>
        </div>
        <div class="form-group">
          <label class="form-label" for="qty">Quantity ({{ dlg.row.uom }})</label>
          <input
            id="qty" v-model.number="dlg.qty" type="number" min="0" step="any" class="form-input"
            :readonly="qtyIsTotal" :class="{ total: qtyIsTotal }"
          />
          <p v-if="qtyIsTotal" class="hint">Sum of the {{ entries.length }} rolls selected — each is reserved in full.</p>
          <p v-else-if="dlg.row.roll_tracked && entries.length === 1" class="hint">One roll: lower the quantity to reserve only part of it.</p>
        </div>
        <div class="form-group">
          <label class="form-label" for="rem">Remarks</label>
          <input id="rem" v-model="dlg.remarks" class="form-input" />
        </div>

        <div v-if="dlg.error" class="alert alert-error" role="alert">{{ dlg.error }}</div>

        <div class="dialog__foot">
          <button type="button" class="btn btn-outline" @click="closeDialog">Cancel</button>
          <button type="submit" class="btn btn-primary" :disabled="dlg.saving || !canSave">
            {{ dlg.saving ? 'Reserving…' : entries.length > 1 ? `Reserve ${entries.length} rolls` : 'Reserve' }}
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
import { callMessage, updateDoc } from '@/api/frappe'

// Only Projects that actually have a received batch — plain Project search would include
// every project in the system, most of which never had anything bought under them and only
// lead to "No stock received under this project" if picked here.
const PROJECT_TYPES = ['Purchase', 'Production']
const types = reactive({ Purchase: true, Production: true })
const selectedTypes = computed(() => PROJECT_TYPES.filter((t) => types[t]))

// Both ticked, or neither, means no type filter (unclassified projects included).
const typeHint = computed(() => {
  const t = selectedTypes.value
  if (t.length === 1) return `Projects with received, produced or reserved stock, typed ${t[0]}.`
  return 'Projects with received, produced or reserved stock, any type — including ones not yet classified.'
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
  row: null, warehouse: '', picked: {}, otherRoll: '', rollSearch: '',
  production_project: '', qty: 0, remarks: '', saving: false, error: '',
})

const fmt = (n) => Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 3 })
const sum = (list) => list.reduce((a, x) => a + x.qty, 0)

const pct = (part, whole) => `${((100 * part) / whole).toFixed(1)}%`

// Batches produced for the project (its work orders / subcontracting receipts), then batches
// received under it (purchase receipts). Same table for both.
const batchSections = computed(() => {
  const d = data.value
  if (!d) return []
  return [
    { key: 'produced', title: `Produced for ${d.project}`, qtyLabel: 'Produced', rows: d.produced_rows, totals: d.produced_totals },
    { key: 'received', title: `Received under ${d.project}`, qtyLabel: 'Received', rows: d.rows, totals: d.totals },
  ].filter((sec) => sec.rows.length)
})
const sectionCount = computed(() => batchSections.value.length + (data.value?.reserved_for.length ? 1 : 0))

function siblings(g) {
  return data.value.stages.filter((x) => x.step === g.step && x.stage !== g.stage).map((x) => x.stage).join(', ')
}

function sectionStats(sec) {
  const t = sec.totals
  return [
    { label: sec.qtyLabel, value: t.received_qty },
    { label: 'Used by this project', value: t.used_own_qty },
    { label: 'Used by other projects', value: t.used_other_qty },
    { label: 'In stores', value: t.available_qty },
    { label: 'Reserved', value: t.reserved_remaining },
    { label: 'Free to reserve', value: t.free_qty },
  ]
}

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
const shownRolls = computed(() => {
  const q = dlg.rollSearch.toLowerCase()
  return q ? dlgRolls.value.filter((x) => x.roll_no.toLowerCase().includes(q)) : dlgRolls.value
})
const pickedRolls = computed(() => dlgRolls.value.filter((x) => dlg.picked[x.roll_no]))
const rollsUncertain = computed(() => !!dlgLocation.value?.rolls_uncertain)
const unnumberedFree = computed(() => dlgLocation.value?.unnumbered?.free_qty || 0)

// What gets reserved: one entry per selected roll (in full), plus a typed roll not in the
// list (from the stock with no roll no. on record), or the warehouse for a batch item.
const entries = computed(() => {
  if (!dlg.row) return []
  if (!dlg.row.roll_tracked) return [{ roll_no: '', qty: dlgLocation.value?.free_qty || 0 }]
  const out = pickedRolls.value.map((x) => ({ roll_no: x.roll_no, qty: x.free_qty }))
  const other = dlg.otherRoll
  if (other && !dlgRolls.value.some((x) => x.roll_no === other)) out.push({ roll_no: other, qty: unnumberedFree.value })
  return out
})
const qtyIsTotal = computed(() => !!dlg.row?.roll_tracked && entries.value.length > 1)

// "Free here" for the header: the whole warehouse for a batch item, the selection for rolls.
const dlgFree = computed(() => {
  const l = dlgLocation.value
  if (!l) return 0
  if (!dlg.row.roll_tracked) return l.free_qty
  return entries.value.length ? entries.value.reduce((a, e) => a + e.qty, 0) : l.free_qty
})

const otherRollHint = computed(() => {
  const other = dlg.otherRoll
  if (!other) return `Stock here with no roll no. on record: ${fmt(unnumberedFree.value)} free.`
  if (dlgRolls.value.some((x) => x.roll_no === other)) return `Roll ${other} is in the list above — tick it there instead.`
  return `Roll ${other} is reserved out of the ${fmt(unnumberedFree.value)} with no roll no. on record.`
})

const canSave = computed(() =>
  !!dlg.production_project && !!dlg.warehouse && entries.value.length > 0 && dlg.qty > 0,
)

// Re-total whenever the selection changes (not when the quantity itself is edited).
watch(() => entries.value.map((e) => `${e.roll_no}:${e.qty}`).join('|'), () => syncQty())

function syncQty() {
  dlg.qty = Math.round(entries.value.reduce((a, e) => a + e.qty, 0) * 1000) / 1000
}
function onLocationChange() {
  dlg.picked = {}
  dlg.otherRoll = ''
  dlg.rollSearch = ''
  syncQty()
}
function selectAllRolls() {
  for (const x of shownRolls.value) dlg.picked[x.roll_no] = true
  syncQty()
}
function clearRolls() {
  dlg.picked = {}
  syncQty()
}

function openDialog(row, at = {}) {
  const first = row.locations.find((l) => l.free_qty > 0)
  Object.assign(dlg, {
    row,
    warehouse: at.warehouse || first?.warehouse || '',
    picked: {}, otherRoll: '', rollSearch: '',
    production_project: '', remarks: '', saving: false, error: '',
  })
  if (at.roll_no) {
    if ((dlgLocation.value?.rolls || []).some((x) => x.roll_no === at.roll_no)) dlg.picked[at.roll_no] = true
    else dlg.otherRoll = at.roll_no
  }
  syncQty()
}
function closeDialog() { dlg.row = null }

async function save() {
  dlg.saving = true
  dlg.error = ''
  try {
    // One entry keeps the typed quantity (a whole batch-item reservation, or part of one
    // roll); several rolls are each reserved in full.
    const list = entries.value.length === 1 ? [{ ...entries.value[0], qty: dlg.qty }] : entries.value
    await callMessage('pranera_planning.api.reservation.create_reservations', {
      reservations: list.map((e) => ({
        purchase_project: data.value.project,
        production_project: dlg.production_project,
        item_code: dlg.row.item_code,
        batch_no: dlg.row.batch_no,
        warehouse: dlg.warehouse,
        roll_no: e.roll_no,
        reserved_qty: e.qty,
        remarks: dlg.remarks,
      })),
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
.flow { margin-bottom: 16px; }
.level.ok { background: #dcfce7; color: #166534; }
.sub.warn { color: #b45309; font-weight: 400; }
.hint.warn { color: #b45309; }
.rolls__head { display: flex; justify-content: space-between; align-items: baseline; }
.rolls__count { font-size: 12px; color: var(--slate-500); }
.rolls__tools { display: flex; gap: 12px; align-items: center; margin-bottom: 8px; }
.rolls__tools .form-input { flex: 1; min-width: 0; }
.rolls__list {
  max-height: 220px; overflow-y: auto; border: 1px solid var(--slate-200, #e2e8f0); border-radius: 8px;
  display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 4px; padding: 6px;
}
.rolls__item {
  display: flex; align-items: center; gap: 8px; padding: 6px 8px; border-radius: 6px; cursor: pointer;
  font-size: 13px; user-select: none;
}
.rolls__item:hover { background: var(--slate-50, #f8fafc); }
.rolls__item.on { background: #eff6ff; }
.rolls__item input { accent-color: var(--primary); width: 15px; height: 15px; }
.rolls__no { font-weight: 600; }
.rolls__qty { margin-left: auto; color: var(--slate-500); font-variant-numeric: tabular-nums; }
.form-label.other { margin-top: 12px; }
.form-input.total { background: var(--slate-50, #f8fafc); font-weight: 600; }
tr.done td { color: var(--slate-500); }
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
