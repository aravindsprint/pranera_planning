<template>
  <div>
    <div v-if="error" class="alert alert-error" role="alert">{{ error }}</div>
    <div v-if="saved" class="alert alert-success" role="status">{{ saved }}</div>
    <div v-if="loading && !data" class="loading-center"><div class="spinner"></div></div>

    <div v-else-if="data && !data.exists" class="card">
      <div class="empty-state">
        <div class="empty-state__title">No Time and Action plan yet</div>
        <div class="empty-state__sub">It is built when you click Create in the Plan tab, or now from the project's saved plan.</div>
        <button class="btn btn-primary" :disabled="busy" @click="rebuild">{{ busy ? 'Building…' : 'Build from plan' }}</button>
      </div>
    </div>

    <template v-else-if="data">
      <section class="stats">
        <div class="stat"><div class="stat__v">{{ day(data.deliver_on) }}</div><div class="stat__l">{{ mts ? 'needed by' : 'delivery by' }}</div></div>
        <div class="stat" :class="{ warn: finishLate }"><div class="stat__v">{{ day(data.summary.finish) }}</div><div class="stat__l">last activity ends</div></div>
        <div class="stat"><div class="stat__v">{{ data.summary.done }} / {{ data.summary.activities }}</div><div class="stat__l">done · {{ data.summary.in_progress }} in progress</div></div>
        <div class="stat" :class="data.summary.late ? 'bad' : 'ok'"><div class="stat__v">{{ data.summary.late }}</div><div class="stat__l">{{ data.summary.late ? 'late or starting late' : 'on track' }}</div></div>
      </section>

      <!-- timeline -->
      <section class="card flush">
        <div class="card__head">
          <h2 class="h2">Timeline</h2>
          <span class="legend"><i class="sw planned"></i>planned <i class="sw actual"></i>actual <i class="sw late"></i>late <i class="ln today"></i>today <i class="ln due"></i>{{ mts ? 'needed by' : 'delivery' }}</span>
        </div>
        <div class="gantt" role="img" :aria-label="`Timeline of ${rows.length} activities`">
          <div class="g-scale">
            <span v-for="t in ticks" :key="t.d" class="g-tick" :style="{ left: `${t.x}%` }">{{ t.label }}</span>
          </div>
          <div v-for="r in rows" :key="r._k" class="g-row">
            <div class="g-label" :title="r.item_code">{{ r.activity }}<span v-if="r.item_code" class="sub"> · {{ r.item_code }}</span></div>
            <div class="g-track">
              <template v-if="r.kind === 'Milestone'">
                <span class="g-diamond" :class="{ done: r.status === 'Done', late: isLate(r) }" :style="{ left: `${x(r.planned_end)}%` }"
                      :title="`${r.activity}: ${r.planned_end}`"></span>
              </template>
              <template v-else>
                <span class="g-bar planned" :class="{ late: isLate(r) }" :style="bar(r.planned_start, r.planned_end)"
                      :title="`Planned ${r.planned_start} → ${r.planned_end}`"></span>
                <span v-if="r.actual_start" class="g-bar actual" :style="bar(r.actual_start, r.actual_end || data.today)"
                      :title="`Actual ${r.actual_start} → ${r.actual_end || 'now'}`"></span>
              </template>
            </div>
          </div>
          <span class="g-line today" :style="{ left: line(data.today) }"></span>
          <span class="g-line due" :style="{ left: line(data.deliver_on) }"></span>
        </div>
      </section>

      <!-- activities -->
      <section class="card flush">
        <div class="card__head">
          <h2 class="h2">Activities</h2>
          <div class="head-actions">
            <button class="btn btn-outline" :disabled="busy" @click="addMilestone">+ Milestone</button>
            <button class="btn btn-outline" :disabled="busy" @click="rebuild">Rebuild from plan</button>
            <button class="btn btn-primary" :disabled="busy || !dirty" @click="save">{{ busy ? 'Saving…' : 'Save' }}</button>
          </div>
        </div>
        <div class="scroll">
          <table class="data-table">
            <thead><tr><th>Activity</th><th>By</th><th class="num">Qty</th><th>Planned start</th><th>Planned end</th>
              <th>Actual</th><th>Status</th><th class="num">Delay</th><th>Remarks</th><th></th></tr></thead>
            <tbody>
              <tr v-for="r in rows" :key="r._k" :class="{ late: isLate(r) }">
                <td>
                  <input v-if="r.source !== 'plan'" v-model.trim="r.activity" class="form-input" :aria-label="`Milestone ${r.seq || ''} name`" />
                  <template v-else><div class="item">{{ r.activity }}</div><div class="sub">{{ r.item_code }}</div></template>
                </td>
                <td class="sub">{{ by(r) }}
                  <a v-if="r.kind === 'Stage' && r.route === 'In-house' && !r.workstation && r.status !== 'Done'"
                     class="book" :href="`${APP_BASE}/workstation-board`">Book a machine</a></td>
                <td class="num">
                  <template v-if="r.kind !== 'Milestone'">{{ fmt(r.done_qty) }} / {{ fmt(r.qty) }} <span class="sub">{{ r.uom }}</span></template>
                </td>
                <td><input v-model="r.planned_start" type="date" class="form-input d" :aria-label="`${r.activity} planned start`" /></td>
                <td><input v-model="r.planned_end" type="date" class="form-input d" :aria-label="`${r.activity} planned end`" />
                  <div v-if="r.slip_days" class="sub">{{ r.slip_days > 0 ? `+${r.slip_days}` : r.slip_days }} d vs first plan</div></td>
                <td>
                  <template v-if="r.kind === 'Milestone'">
                    <input v-model="r.actual_end" type="date" class="form-input d" :aria-label="`${r.activity} done on`" />
                  </template>
                  <template v-else-if="r.actual_start"><span class="sub">{{ day(r.actual_start) }} → {{ r.actual_end ? day(r.actual_end) : '…' }}</span></template>
                  <span v-else class="sub">—</span>
                </td>
                <td><span class="badge" :class="badge(r)">{{ isLate(r) && r.status !== 'Done' ? (r.late_start ? 'Start late' : 'Late') : r.status }}</span></td>
                <td class="num" :class="{ bad: r.delay_days > 0, good: r.status === 'Done' && r.delay_days <= 0 }">
                  {{ r.delay_days ? `${r.delay_days > 0 ? '+' : ''}${r.delay_days} d` : '—' }}</td>
                <td><input v-model.trim="r.remarks" class="form-input" placeholder="Reason, note" :aria-label="`${r.activity} remarks`" /></td>
                <td class="act"><button v-if="r.source !== 'plan'" class="icon-btn" :aria-label="`Remove ${r.activity || 'milestone'}`" @click="remove(r)"><i class="pi pi-times"></i></button></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="foot">Stages are scheduled back from the {{ mts ? 'needed-by' : 'delivery' }} date with the stage days in Re-order Settings
          (in-house or job work) and suppliers' lead days. Actual dates come from Work Orders, subcontracting and purchase documents;
          milestones are closed by hand. Rebuild keeps activities already started and your milestones.
          Built {{ data.generated_on ? data.generated_on.slice(0, 16) : '' }}.</div>
      </section>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { callMessage } from '@/api/frappe'
import { APP_BASE } from '@/config/app'

const props = defineProps({ project: { type: String, required: true } })
const data = ref(null)
const rows = ref([])
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const saved = ref('')
const dirty = ref(false)
let original = ''
let seq = 0

const mts = computed(() => data.value?.order_type === 'Made to stock')
const fmt = (n) => Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 1 })
const day = (d) => (d ? new Date(`${String(d).slice(0, 10)}T00:00:00`).toLocaleDateString(undefined, { day: 'numeric', month: 'short' }) : '—')
const editable = (list) => JSON.stringify(list.map((r) => [r.name, r.activity, r.planned_start, r.planned_end, r.actual_end, r.remarks]))
const isLate = (r) => r.status !== 'Done' && (r.delay_days > 0 || r.late_start)
const finishLate = computed(() => data.value?.summary?.finish && data.value.deliver_on && data.value.summary.finish > data.value.deliver_on)
const by = (r) => (r.kind === 'Milestone' ? '' : [r.route, r.workstation || r.supplier || r.service].filter(Boolean).join(' · '))
const badge = (r) => (r.status === 'Done' ? 'badge-success' : isLate(r) ? 'badge-danger' : r.status === 'In progress' ? 'badge-info' : 'badge-muted')

// timeline scale: from the earliest date to a little after the last
const range = computed(() => {
  const ds = []
  for (const r of rows.value) for (const k of ['planned_start', 'planned_end', 'actual_start', 'actual_end']) if (r[k]) ds.push(r[k])
  if (data.value?.deliver_on) ds.push(data.value.deliver_on)
  if (data.value?.today) ds.push(data.value.today)
  const t = ds.map((d) => new Date(`${String(d).slice(0, 10)}T00:00:00`).getTime())
  const lo = Math.min(...t), hi = Math.max(...t) + 2 * 864e5
  return { lo, span: Math.max(hi - lo, 864e5) }
})
const x = (d) => (d ? Math.min(100, Math.max(0, ((new Date(`${String(d).slice(0, 10)}T00:00:00`).getTime() - range.value.lo) / range.value.span) * 100)) : 0)
// the gantt has 18px padding each side and a label column of --lw before the tracks
const line = (d) => `calc(18px + var(--lw) + (100% - 36px - var(--lw)) * ${x(d) / 100})`
const bar = (a, b) => { const l = x(a), r = x(b || a); return { left: `${l}%`, width: `${Math.max(0.6, r - l)}%` } }
const ticks = computed(() => {
  const out = [], { lo, span } = range.value
  const step = span / 864e5 > 120 ? 30 : span / 864e5 > 40 ? 7 : 2
  for (let t = lo; t <= lo + span; t += step * 864e5) {
    out.push({ d: t, x: ((t - lo) / span) * 100, label: new Date(t).toLocaleDateString(undefined, { day: 'numeric', month: 'short' }) })
  }
  return out
})

function take(res) {
  data.value = res
  rows.value = (res.rows || []).map((r) => ({ ...r, _k: ++seq }))
  original = editable(rows.value)
  dirty.value = false
}
watch(rows, (v) => { dirty.value = editable(v) !== original }, { deep: true })

async function run(fn, ok) {
  busy.value = true
  error.value = ''
  saved.value = ''
  try {
    take(await fn())
    if (ok) saved.value = ok
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}
async function load() {
  loading.value = true
  await run(() => callMessage('pranera_planning.api.time_and_action.get_ta', { project: props.project }))
  loading.value = false
}
const rebuild = () => run(() => callMessage('pranera_planning.api.time_and_action.rebuild_ta', { project: props.project }),
  'Rebuilt from the plan. Activities already started kept their dates.')
const save = () => run(() => callMessage('pranera_planning.api.time_and_action.save_ta', {
  project: props.project,
  rows: rows.value.map(({ _k, status, done_qty, delay_days, late_start, slip_days, ...r }) => r),
}), 'Saved.')
function addMilestone() {
  rows.value.push({ _k: ++seq, activity: '', kind: 'Milestone', source: 'manual', planned_start: '', planned_end: data.value.deliver_on,
    actual_end: '', remarks: '', status: 'Not started', delay_days: 0 })
}
function remove(r) { rows.value.splice(rows.value.indexOf(r), 1) }

watch(() => props.project, (p) => { data.value = null; if (p) load() }, { immediate: true })
</script>

<style scoped>
.stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 16px; }
.stat.warn { background: #fff7ed; border-color: #f3c79a; }
.stat.bad { background: #fef2f2; border-color: #fecaca; }
.stat.ok { background: #ecfdf3; border-color: #bbe5c8; }
.card.flush { padding: 0; margin-bottom: 16px; overflow: hidden; }
.card__head { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; padding: 14px 18px; border-bottom: 1px solid var(--slate-200); }
.h2 { margin: 0; font-size: 16px; font-weight: 650; }
.head-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.sub { font-size: 12px; color: var(--slate-500); }
.item { font-weight: 600; }
.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.act { width: 40px; text-align: right; }
.icon-btn { border: 0; background: transparent; cursor: pointer; color: var(--slate-500); padding: 4px; }
.scroll { overflow-x: auto; }
.book { display: block; font-size: 12px; }
.form-input.d { width: 150px; }
tr.late td { background: #fff7f7; }
.good { color: #166534; font-weight: 600; }
.bad { color: #b91c1c; font-weight: 600; }
.badge-success { background: #dcfce7; color: #166534; }
.badge-danger { background: #fee2e2; color: #b91c1c; }
.badge-muted { background: var(--slate-100); color: var(--slate-500); }
.foot { padding: 10px 18px; background: var(--slate-50, #f8fafc); border-top: 1px solid var(--slate-200); font-size: 12px; color: var(--slate-500); }
.alert-success { background: #ecfdf3; border: 1px solid #bbe5c8; color: #166534; border-radius: 8px; padding: 10px 14px; margin-bottom: 12px; font-size: 13px; }
.empty-state { display: flex; flex-direction: column; gap: 10px; align-items: flex-start; }

/* timeline */
.legend { font-size: 12px; color: var(--slate-500); display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.sw { display: inline-block; width: 18px; height: 8px; border-radius: 3px; margin-right: 2px; vertical-align: middle; }
.ln { display: inline-block; width: 2px; height: 12px; margin-right: 2px; vertical-align: middle; }
.gantt { --lw: 230px; position: relative; padding: 8px 18px 14px; overflow-x: auto; min-width: 640px; }
.g-scale { position: relative; height: 18px; margin-left: var(--lw); border-bottom: 1px solid var(--slate-200); }
.g-tick { position: absolute; top: 0; transform: translateX(-50%); font-size: 11px; color: var(--slate-500); white-space: nowrap; }
.g-row { display: flex; align-items: center; height: 30px; border-bottom: 1px dashed var(--slate-100); }
.g-label { width: var(--lw); flex: none; font-size: 13px; padding-right: 10px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.g-track { position: relative; flex: 1; height: 100%; }
.g-bar { position: absolute; border-radius: 4px; }
.g-bar.planned, .sw.planned { background: #cbd5e1; top: 7px; height: 16px; }
.g-bar.planned.late, .sw.late { background: #fca5a5; }
.g-bar.actual, .sw.actual { background: #1d4ed8; top: 12px; height: 6px; }
.g-diamond { position: absolute; top: 8px; width: 13px; height: 13px; transform: translateX(-50%) rotate(45deg); background: #64748b; }
.g-diamond.done { background: #16a34a; }
.g-diamond.late { background: #dc2626; }
.g-line { position: absolute; top: 26px; bottom: 14px; width: 2px; }
.g-line.today, .ln.today { background: #f59e0b; }
.g-line.due, .ln.due { background: #0f172a; }
@media (max-width: 760px) { .stats { grid-template-columns: repeat(2, minmax(0, 1fr)); } .gantt { --lw: 150px; } }
</style>
