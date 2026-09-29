<template>
  <div class="page">
    <AppHeader subtitle="Reserve stock bought for one project to another project's production" />

    <main class="page-content">
      <div class="page-toolbar">
        <div class="picker">
          <label class="form-label" for="pp">Purchase project</label>
          <LinkField
            id="pp" v-model="project" doctype="Project" placeholder="e.g. 26PTIN1710"
            :search-fn="searchPurchaseProjects" empty-label="No project with received stock found"
            @change="load"
          />
          <p class="hint">Only projects with received stock, and not typed Production.</p>
        </div>
        <button class="btn btn-primary" :disabled="!project || loading" @click="load">Show stock</button>
      </div>

      <div v-if="error" class="alert alert-error" role="alert">{{ error }}</div>
      <div v-if="loading" class="loading-center"><div class="spinner"></div></div>

      <div v-else-if="!data" class="card">
        <div class="empty-state">
          <div class="empty-state__title">Choose a purchase project</div>
          <div class="empty-state__sub">You will see every batch bought under it, who has used it, and what is still free to reserve.</div>
        </div>
      </div>

      <div v-else-if="!data.rows.length" class="card">
        <div class="empty-state">
          <div class="empty-state__title">No stock received under {{ data.project }}</div>
          <div class="empty-state__sub">Only stock received through a submitted Purchase Receipt with this project appears here.</div>
        </div>
      </div>

      <template v-else>
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
                    <div class="sub">{{ r.batch_no }}</div>
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
                    <div class="detail__grid">
                      <div>
                        <div class="detail__h">Reservations</div>
                        <p v-if="!r.reservations.length" class="muted">Nothing reserved on this batch.</p>
                        <table v-else class="mini">
                          <thead><tr><th>Reserved for</th><th class="num">Reserved</th><th class="num">Issued</th><th class="num">Remaining</th><th></th></tr></thead>
                          <tbody>
                            <tr v-for="x in r.reservations" :key="x.name">
                              <td>{{ x.production_project }} <span class="sub">{{ x.name }}</span></td>
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
      </template>
    </main>

    <div v-if="dlg.row" class="overlay" @mousedown.self="closeDialog">
      <form class="dialog" @submit.prevent="save">
        <h2>Reserve stock</h2>
        <p class="sub">{{ dlg.row.item_name || dlg.row.item_code }} · {{ dlg.row.batch_no }}</p>
        <p class="sub">Free to reserve: <strong>{{ fmt(dlg.row.free_qty) }} {{ dlg.row.uom }}</strong></p>

        <div class="form-group">
          <label class="form-label" for="prod">Reserve for project</label>
          <LinkField
            id="prod" v-model="dlg.production_project" doctype="Project" title-field="project_name"
            :filters="[['Project', 'project_type', 'in', ['Production', '']]]"
            placeholder="Production project"
          />
          <p class="hint">Projects typed Purchase are hidden here — this list is Production projects (or not yet classified).</p>
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
          <button type="submit" class="btn btn-primary" :disabled="dlg.saving || !dlg.production_project || !(dlg.qty > 0)">
            {{ dlg.saving ? 'Reserving…' : 'Reserve' }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppHeader from '@/components/AppHeader.vue'
import LinkField from '@/components/LinkField.vue'
import { callMessage, createDoc, updateDoc } from '@/api/frappe'

// Only Projects that actually have a purchased batch — plain Project search would include
// every project in the system, most of which never had anything bought under them and only
// lead to "No stock received under this project" if picked here.
async function searchPurchaseProjects(txt) {
  return await callMessage('pranera_planning.api.reservation.search_purchase_projects', { txt })
}

const route = useRoute()
const router = useRouter()

const project = ref('')
const data = ref(null)
const loading = ref(false)
const error = ref('')
const open = reactive({})

const dlg = reactive({ row: null, production_project: '', qty: 0, remarks: '', saving: false, error: '' })

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

function openDialog(row) {
  Object.assign(dlg, { row, production_project: '', qty: row.free_qty, remarks: '', saving: false, error: '' })
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
.picker { width: 280px; max-width: 100%; }
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

.overlay { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.45); z-index: 400; display: flex; align-items: center; justify-content: center; padding: 16px; }
.dialog { background: #fff; border-radius: var(--radius-lg); padding: 24px; width: 100%; max-width: 420px; box-shadow: var(--shadow-lg); }
.dialog h2 { font-size: 18px; margin-bottom: 4px; }
.dialog .sub { margin-bottom: 4px; }
.dialog .form-group:first-of-type { margin-top: 16px; }
.dialog__foot { display: flex; justify-content: flex-end; gap: 10px; margin-top: 8px; }
</style>
