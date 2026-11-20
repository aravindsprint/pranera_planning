<template>
  <div class="page">
    <AppHeader subtitle="Machines × days: what is booked, what is free, and what still needs a machine" />

    <main class="page-content">
      <div v-if="error" class="alert alert-error pre" role="alert">{{ error }}</div>
      <div v-if="note" class="alert alert-success" role="status">{{ note }}</div>
      <div v-if="needReason" class="override card">
            <label class="form-label" for="wb-reason">Override reason for {{ needReason.item_code }} on {{ needReason.ws }}</label>
            <div class="override__row">
              <input id="wb-reason" v-model.trim="reason" class="form-input" placeholder="e.g. second shift approved for this week" />
              <button class="btn btn-primary" :disabled="busy || !reason" @click="moveCard(needReason, true)">Book with override</button>
              <button class="btn btn-outline" @click="needReason = null">Cancel</button>
            </div>
          </div>

      <section class="card controls">
        <div class="field"><label class="form-label" for="wb-stage">Stage</label>
          <select id="wb-stage" v-model="stage" class="form-input" @change="ws = ''; syncUrl(); load()">
            <option v-for="s in board?.stages || []" :key="s" :value="s">{{ s }}</option></select></div>
        <div class="field"><label class="form-label" for="wb-ws">Machine</label>
          <select id="wb-ws" v-model="ws" class="form-input" @change="syncUrl">
            <option value="">All {{ board?.stage || '' }} machines</option>
            <option v-for="m in board?.machines || []" :key="m.name" :value="m.name">{{ m.label }}</option></select></div>
        <div class="field"><span class="form-label">View</span>
          <div class="seg" role="group" aria-label="View">
            <button v-for="v in VIEWS" :key="v.key" type="button" :class="{ on: view === v.key }" :aria-pressed="view === v.key" @click="setView(v.key)">{{ v.label }}</button>
          </div></div>
        <template v-if="view !== 'calendar'">
        <div class="field"><label class="form-label" for="wb-start">From</label>
          <input id="wb-start" v-model="start" type="date" class="form-input" @change="load" /></div>
        <div class="field"><label class="form-label" for="wb-days">Days</label>
          <select id="wb-days" v-model.number="days" class="form-input" @change="load">
            <option :value="14">2 weeks</option><option :value="28">4 weeks</option><option :value="56">8 weeks</option></select></div>
        </template>
        <button class="btn btn-outline" :disabled="loading" @click="load">{{ loading ? 'Loading…' : 'Refresh' }}</button>
        <span v-if="view === 'grid'" class="legend"><i class="sw l0"></i>free <i class="sw l1"></i>&lt; 80% <i class="sw l2"></i>80–100% <i class="sw l3"></i>over <i class="sw off"></i>holiday</span>
      </section>

      <section v-if="board && board.machines.length && !ws" class="card idle" aria-label="Machines without bookings">
        <div class="idle__head">
          <b>{{ idle.length ? `${idle.length} of ${board.machines.length} machines have no booking` : 'Every machine has a booking' }}</b>
          <span class="sub">{{ dd(board.dates[0]) }} – {{ dd(board.dates[board.dates.length - 1]) }}</span>
          <label class="only"><input v-model="idleOnly" type="checkbox" /> Show only these</label>
        </div>
        <div v-if="idle.length" class="chips">
          <button v-for="m in idle" :key="m.name" class="chip-btn free" :title="`${m.label}: free all ${freeDays(m)} working days`"
                  @click="ws = m.name; syncUrl()">{{ m.label }}</button>
        </div>
        <div v-if="light.length" class="chips">
          <span class="sub">Lightly booked (under 30%):</span>
          <button v-for="m in light" :key="m.name" class="chip-btn" :title="`${freeDays(m)} free working days`"
                  @click="ws = m.name; syncUrl()">{{ m.label }} · {{ loadPct(m) }}% · {{ freeDays(m) }} d free</button>
        </div>
      </section>

      <div v-if="loading && !board" class="loading-center"><div class="spinner"></div></div>

      <template v-else-if="board && view === 'kanban'">
        <WsKanban :board="vb" :busy="busy" @move="(c) => moveCard(c)" @release="release" />
        <p class="hint-k">Drag a job onto a machine to book or move it (its start stays; the end follows the machine's capacity), or back to
          <i>Waiting</i> to release it. The same fit and capacity checks apply.</p>
      </template>

      <section v-else-if="board && view === 'calendar'" class="card">
        <WsCalendar :board="vb" :month="month" @month="shiftMonth" />
      </section>

      <template v-else-if="board">
        <!-- the board -->
        <section class="card flush">
          <div class="card__head"><h2 class="h2">{{ ws ? vb.machines[0]?.label : `${board.stage} machines` }}</h2>
            <span class="sub">{{ vb.machines.length }} machine{{ vb.machines.length === 1 ? '' : 's' }} · click a machine for its bookings</span></div>
          <p v-if="!vb.machines.length" class="empty">No workstation has Planning stage “{{ board.stage }}”. Set it on the Workstation form.</p>
          <div v-else class="grid-wrap">
            <table class="grid">
              <thead><tr><th class="m">Machine</th>
                <th v-for="d in board.dates" :key="d" class="c" :class="{ wk: isWeekStart(d) }">{{ dd(d) }}<br /><span class="sub">{{ wd(d) }}</span></th></tr></thead>
              <tbody>
                <template v-for="m in vb.machines" :key="m.name">
                  <tr class="mrow" @click="open = open === m.name ? '' : m.name">
                    <th class="m">
                      <div class="item">{{ m.label }}</div>
                      <div class="sub">{{ fmt(m.per_day) }} kg/day<template v-if="m.dia"> · {{ m.dia }}″ {{ m.gauge }}G</template></div>
                      <div v-if="m.missing.length" class="miss">set: {{ m.missing.join(', ') }}</div>
                      <div v-if="notReady(m)" class="miss">{{ notReady(m) }} booking{{ notReady(m) === 1 ? '' : 's' }} waiting for material</div>
                    </th>
                    <td v-for="c in m.cells" :key="c.date" class="c" :class="[cls(c), { wk: isWeekStart(c.date) }]"
                        :title="c.capacity ? `${dd(c.date)}: ${fmt(c.booked)} of ${fmt(c.capacity)} kg` : `${dd(c.date)}: holiday`">
                      {{ c.pct == null ? '' : c.pct >= 999 ? '!' : c.pct ? `${c.pct}` : '' }}</td>
                  </tr>
                  <tr v-if="open === m.name" class="detail"><td :colspan="board.dates.length + 1">
                    <p v-if="!m.bookings.length" class="sub">Nothing booked in these days.</p>
                    <table v-else class="data-table compact">
                      <thead><tr><th>Project</th><th>Item</th><th class="num">Qty</th><th>From → to</th><th>Raw material</th><th>Remarks</th><th></th></tr></thead>
                      <tbody><tr v-for="b in m.bookings" :key="b.activity">
                        <td><a :href="`${APP_BASE}/project-planning?project=${encodeURIComponent(b.project)}&tab=ta`">{{ b.project }}</a></td>
                        <td>{{ b.item_code }}</td><td class="num">{{ fmt(b.qty) }} {{ b.uom }}</td>
                        <td>{{ dd(b.planned_start) }} → {{ dd(b.planned_end) }}</td><td @click.stop><MaterialBadge :m="b.material" /></td><td class="sub">{{ b.remarks }}</td>
                        <td class="act"><button class="btn btn-outline sm" :disabled="busy" @click.stop="release(b)">Release</button></td>
                      </tr></tbody>
                    </table>
                  </td></tr>
                </template>
              </tbody>
            </table>
          </div>
        </section>

        <!-- waiting for a machine -->
        <section class="card flush">
          <div class="card__head"><h2 class="h2">Waiting for a machine</h2><span class="sub">{{ vb.waiting.length }} in-house {{ board.stage }} activit{{ vb.waiting.length === 1 ? 'y' : 'ies' }}{{ ws ? ` that fit ${ws}` : '' }}</span></div>
          <p v-if="!vb.waiting.length" class="empty">Every in-house {{ board.stage }} activity has a machine.</p>
          <div v-else class="scroll">
            <table class="data-table">
              <thead><tr><th>Project</th><th>Item</th><th class="num">Qty</th><th>Planned</th><th>Raw material</th><th>Machine</th><th>Start</th><th></th></tr></thead>
              <tbody>
                <tr v-for="a in vb.waiting" :key="a.name">
                  <td><a :href="`${APP_BASE}/project-planning?project=${encodeURIComponent(a.project)}&tab=ta`">{{ a.project }}</a></td>
                  <td><div class="item">{{ a.item_code }}</div><div class="sub"><template v-if="a.dia">{{ a.dia }}″ {{ a.gauge }}G</template></div></td>
                  <td class="num">{{ fmt(a.qty - a.done_qty) }} <span class="sub">{{ a.uom }}</span></td>
                  <td>{{ dd(a.planned_start) }} → {{ dd(a.planned_end) }}</td>
                  <td><MaterialBadge :m="a.material" /></td>
                  <td>
                    <select v-model="pick[a.name].ws" class="form-input" :aria-label="`Machine for ${a.item_code}`" @change="pickSlot(a)">
                      <option value="">Choose…</option>
                      <option v-for="c in a.candidates" :key="c.workstation" :value="c.workstation" :disabled="!c.fits && !board.can_override">
                        {{ c.workstation }} — {{ c.fits ? (c.slot ? `free ${dd(c.slot.start)} → ${dd(c.slot.end)}${c.late ? ' (after planned end)' : ''}` : 'no free slot / no capacity') : `doesn't fit: ${c.why.join(', ')}` }}
                      </option>
                    </select>
                  </td>
                  <td><input v-model="pick[a.name].start" type="date" class="form-input d" :aria-label="`Start for ${a.item_code}`" /></td>
                  <td class="act">
                    <button class="btn btn-primary sm" :disabled="busy || !pick[a.name].ws" @click="book(a)">Book</button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="foot">Capacity a day = Kg per hour × Working Hours × Production Capacity, from each Workstation; holidays from its Holiday List.
            The booking's end follows from that capacity. A machine that doesn't fit (stage, dia, gauge) or would go over capacity is refused
            unless an override role gives a reason.</div>
        </section>
      </template>
    </main>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppHeader from '@/components/AppHeader.vue'
import MaterialBadge from '@/components/MaterialBadge.vue'
import WsKanban from './WsKanban.vue'
import WsCalendar from './WsCalendar.vue'
import { callMessage } from '@/api/frappe'
import { APP_BASE } from '@/config/app'

const board = ref(null)
const stage = ref(String(useRoute().query.stage || ''))
const start = ref(new Date().toISOString().slice(0, 10))
const days = ref(28)
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const note = ref('')
const open = ref('')
const pick = reactive({})
const needReason = ref(null)
const route = useRoute()
const router = useRouter()
const ws = ref(String(route.query.ws || ''))
// the board as shown: one machine when a machine is chosen, and only waiting jobs that fit it
const idleOnly = ref(false)
// per machine over the period shown: % of capacity booked, and working days with nothing booked
const loadPct = (m) => {
  const cap = m.cells.reduce((a, c) => a + c.capacity, 0)
  return cap > 0 ? Math.round((m.cells.reduce((a, c) => a + c.booked, 0) / cap) * 100) : 0
}
const freeDays = (m) => m.cells.filter((c) => c.capacity > 0 && c.booked <= 0).length
const idle = computed(() => (board.value?.machines || []).filter((m) => !m.cells.some((c) => c.booked > 0)))
const light = computed(() => (board.value?.machines || []).filter((m) => m.cells.some((c) => c.booked > 0) && loadPct(m) < 30))
const vb = computed(() => {
  if (board.value && !ws.value && idleOnly.value) {
    const names = new Set(idle.value.map((m) => m.name))
    return { ...board.value, machines: board.value.machines.filter((m) => names.has(m.name)) }
  }
  if (!board.value || !ws.value) return board.value
  return {
    ...board.value,
    machines: board.value.machines.filter((m) => m.name === ws.value),
    waiting: board.value.waiting.filter((a) => a.candidates.some((c) => c.workstation === ws.value && c.fits)),
  }
})
function syncUrl() {
  router.replace({ query: { ...route.query, ws: ws.value || undefined, stage: stage.value || undefined } })
  if (ws.value && board.value) {
    for (const a of vb.value.waiting) {
      const c = a.candidates.find((x) => x.workstation === ws.value)
      pick[a.name] = { ws: ws.value, start: c?.slot ? c.slot.start : a.planned_start }
    }
  }
}
const VIEWS = [{ key: 'grid', label: 'Grid' }, { key: 'kanban', label: 'Kanban' }, { key: 'calendar', label: 'Calendar' }]
const view = ref('grid')
const month = ref(new Date().toISOString().slice(0, 7))
// the calendar shows whole weeks around the month: from the Monday on or before the 1st, 6 weeks
function monthRange() {
  const first = new Date(`${month.value}-01T00:00:00`)
  const back = (first.getDay() + 6) % 7
  const s = new Date(first.getTime() - back * 864e5)
  return { start: `${s.getFullYear()}-${String(s.getMonth() + 1).padStart(2, '0')}-${String(s.getDate()).padStart(2, '0')}`, days: 42 }
}
function setView(v) {
  view.value = v
  if (v === 'calendar') { const r = monthRange(); start.value = r.start; days.value = r.days }
  else { start.value = new Date().toISOString().slice(0, 10); days.value = v === 'kanban' ? 56 : 28 }
  load()
}
function shiftMonth(n) {
  const d = new Date(`${month.value}-01T00:00:00`)
  d.setMonth(d.getMonth() + n)
  month.value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
  const r = monthRange(); start.value = r.start; days.value = r.days
  load()
}
const reason = ref('')

const fmt = (n) => Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })
const dt = (d) => new Date(`${String(d).slice(0, 10)}T00:00:00`)
const dd = (d) => (d ? dt(d).toLocaleDateString(undefined, { day: 'numeric', month: 'short' }) : '—')
const wd = (d) => dt(d).toLocaleDateString(undefined, { weekday: 'narrow' })
const isWeekStart = (d) => dt(d).getDay() === 1
const notReady = (m) => m.bookings.filter((b) => b.material && b.material.status !== 'Ready').length
const cls = (c) => (c.capacity <= 0 ? (c.booked > 0 ? 'l3' : 'off') : c.pct > 100 ? 'l3' : c.pct >= 80 ? 'l2' : c.pct > 0 ? 'l1' : 'l0')

async function load() {
  loading.value = true
  error.value = ''
  try {
    board.value = await callMessage('pranera_planning.api.workstation_board.get_board', { stage: stage.value || undefined, start: start.value, days: days.value })
    stage.value = board.value.stage || ''
    if (ws.value && !board.value.machines.some((m) => m.name === ws.value)) ws.value = ''
    for (const a of board.value.waiting) {
      const best = a.candidates.find((c) => c.fits && c.slot)
      pick[a.name] = { ws: best ? best.workstation : '', start: best ? best.slot.start : a.planned_start }
    }
    if (ws.value) syncUrl()
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}
function pickSlot(a) {
  const c = a.candidates.find((x) => x.workstation === pick[a.name].ws)
  if (c?.slot) pick[a.name].start = c.slot.start
}
function book(a) {
  return moveCard({ activity: a.name, item_code: a.item_code, ws: pick[a.name].ws, start: pick[a.name].start })
}
async function moveCard(c, withReason = false) {
  busy.value = true
  error.value = ''
  note.value = ''
  try {
    const r = await callMessage('pranera_planning.api.workstation_board.allocate', {
      activity: c.activity, workstation: c.ws, start: c.start, override_reason: withReason ? reason.value : undefined,
    })
    note.value = `${c.item_code} booked on ${c.ws}: ${dd(r.start)} → ${dd(r.end)} (${r.working_days} working day${r.working_days === 1 ? '' : 's'})${r.after_delivery ? ' — ends after the delivery date' : ''}.`
    needReason.value = null
    reason.value = ''
    await load()
  } catch (e) {
    error.value = String(e.message || '').replace(/<br\s*\/?>/g, '\n').replace(/<[^>]+>/g, '')
    if (board.value?.can_override && !withReason) needReason.value = c
  } finally {
    busy.value = false
  }
}
async function release(b) {
  busy.value = true
  error.value = ''
  try {
    await callMessage('pranera_planning.api.workstation_board.release', { activity: b.activity })
    note.value = `${b.item_code} released from its machine.`
    await load()
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}
onMounted(load)
</script>

<style scoped>
.controls { display: flex; gap: 14px; align-items: flex-end; flex-wrap: wrap; margin-bottom: 16px; }
.field { display: flex; flex-direction: column; gap: 6px; min-width: 160px; }
.seg { display: inline-flex; border: 1px solid var(--slate-200); border-radius: 8px; overflow: hidden; }
.seg button { border: 0; background: #fff; padding: 8px 12px; font: inherit; font-size: 13px; cursor: pointer; color: var(--slate-700); }
.seg button + button { border-left: 1px solid var(--slate-200); }
.seg button.on { background: var(--slate-900, #0f172a); color: #fff; }
.idle { display: flex; flex-direction: column; gap: 8px; margin-bottom: 16px; }
.idle__head { display: flex; gap: 12px; align-items: baseline; flex-wrap: wrap; }
.only { margin-left: auto; font-size: 13px; display: flex; gap: 6px; align-items: center; cursor: pointer; }
.chips { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.chip-btn { border: 1px solid var(--slate-200); background: #fff; border-radius: 999px; padding: 3px 10px; font: inherit; font-size: 12px; cursor: pointer; }
.chip-btn.free { background: #ecfdf3; border-color: #bbe5c8; color: #166534; font-weight: 600; }
.chip-btn:hover { border-color: var(--slate-400); }
.hint-k { font-size: 12px; color: var(--slate-500); margin-top: 6px; }
.legend { margin-left: auto; font-size: 12px; color: var(--slate-500); display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.sw { display: inline-block; width: 14px; height: 14px; border-radius: 3px; border: 1px solid var(--slate-200); vertical-align: middle; }
.card.flush { padding: 0; margin-bottom: 16px; overflow: hidden; }
.card__head { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 14px 18px; border-bottom: 1px solid var(--slate-200); }
.h2 { margin: 0; font-size: 16px; font-weight: 650; }
.sub { font-size: 12px; color: var(--slate-500); font-weight: 400; }
.item { font-weight: 600; }
.empty { padding: 16px 18px; margin: 0; font-size: 14px; color: var(--slate-500); }
.grid-wrap, .scroll { overflow-x: auto; }
.grid { border-collapse: collapse; width: 100%; font-size: 12px; }
.grid th, .grid td { border-bottom: 1px solid var(--slate-100); }
.grid .m { position: sticky; left: 0; background: #fff; text-align: left; padding: 8px 12px; min-width: 190px; z-index: 1; font-weight: 400; }
.grid .c { text-align: center; min-width: 34px; padding: 6px 2px; font-variant-numeric: tabular-nums; }
.grid thead .c { font-weight: 600; color: var(--slate-500); }
.grid .wk { border-left: 1px solid var(--slate-200); }
.mrow { cursor: pointer; }
.mrow:hover .m { background: var(--slate-50, #f8fafc); }
.l0, .sw.l0 { background: #fff; }
.l1, .sw.l1 { background: #dcfce7; color: #166534; }
.l2, .sw.l2 { background: #fef3c7; color: #92400e; }
.l3, .sw.l3 { background: #fee2e2; color: #b91c1c; font-weight: 700; }
.off, .sw.off { background: repeating-linear-gradient(45deg, #f1f5f9, #f1f5f9 4px, #e2e8f0 4px, #e2e8f0 8px); }
.miss { font-size: 11px; color: #b45309; }
.detail td { background: var(--slate-50, #f8fafc); padding: 10px 14px; }
.num { text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
.act { text-align: right; white-space: nowrap; }
.btn.sm { padding: 4px 10px; font-size: 13px; }
.form-input.d { width: 150px; }
.data-table.compact td, .data-table.compact th { padding-top: 6px; padding-bottom: 6px; }
.override { padding: 12px 18px; border: 1px solid #f3c79a; background: #fff7ed; margin-bottom: 12px; }
.override__row { display: flex; gap: 8px; margin-top: 6px; flex-wrap: wrap; }
.override__row .form-input { flex: 1; min-width: 260px; }
.foot { padding: 10px 18px; background: var(--slate-50, #f8fafc); border-top: 1px solid var(--slate-200); font-size: 12px; color: var(--slate-500); }
.pre { white-space: pre-line; }
.alert-success { background: #ecfdf3; border: 1px solid #bbe5c8; color: #166534; border-radius: 8px; padding: 10px 14px; margin-bottom: 12px; font-size: 13px; }
</style>
