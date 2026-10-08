<template>
  <div class="kb" role="list" aria-label="Machines and their bookings">
    <!-- waiting for a machine -->
    <section class="col wait" :class="{ over: overCol === '' }" @dragover.prevent="overCol = ''" @dragleave="overCol = null"
             @drop.prevent="drop('')">
      <header><div class="name">Waiting for a machine</div><div class="sub">{{ board.waiting.length }} · drag onto a machine</div></header>
      <article v-for="a in board.waiting" :key="a.name" class="card-k" draggable="true" @dragstart="drag({ ...a, activity: a.name, from: '' })">
        <div class="top"><a :href="ta(a.project)" class="proj">{{ a.project }}</a><span class="chip c-wait">Waiting</span></div>
        <div class="item">{{ a.item_code }}</div>
        <div class="sub">{{ f(a.qty - (a.done_qty || 0)) }} {{ a.uom }} · planned {{ dd(a.planned_start) }} → {{ dd(a.planned_end) }}</div>
        <MaterialBadge :m="a.material" />
      </article>
      <p v-if="!board.waiting.length" class="empty">Nothing waiting.</p>
    </section>

    <!-- one column per machine, its queue in start order -->
    <section v-for="m in board.machines" :key="m.name" class="col" :class="{ over: overCol === m.name }"
             @dragover.prevent="overCol = m.name" @dragleave="overCol = null" @drop.prevent="drop(m.name)">
      <header>
        <div class="name">{{ m.label }}</div>
        <div class="sub">{{ f(m.per_day) }} kg/day<template v-if="m.dia"> · {{ m.dia }}″ {{ m.gauge }}G</template> · {{ load(m) }}% booked</div>
        <div class="bar"><span :style="{ width: `${Math.min(100, load(m))}%` }" :class="{ hot: load(m) > 100 }"></span></div>
      </header>
      <article v-for="b in queue(m)" :key="b.activity" class="card-k" :class="`s-${slug(b.status)}`" draggable="true"
               @dragstart="drag({ ...b, from: m.name })">
        <div class="top"><a :href="ta(b.project)" class="proj">{{ b.project }}</a><span class="chip" :class="`c-${slug(b.status)}`">{{ b.status }}</span></div>
        <div class="item">{{ b.item_code }}</div>
        <div class="sub">{{ dd(b.planned_start) }} → {{ dd(b.planned_end) }} · {{ f(b.qty) }} {{ b.uom }}</div>
        <div v-if="b.done_qty" class="prog" :title="`${f(b.done_qty)} of ${f(b.qty)} done`"><span :style="{ width: `${Math.min(100, (b.done_qty / b.qty) * 100)}%` }"></span></div>
        <div class="foot"><MaterialBadge v-if="b.status !== 'Done'" :m="b.material" />
          <button v-if="b.status === 'Booked' || b.status === 'Late'" class="link" :disabled="busy" @click="$emit('release', b)">Release</button></div>
      </article>
      <p v-if="!queue(m).length" class="empty">Free — drop a job here.</p>
    </section>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import MaterialBadge from '@/components/MaterialBadge.vue'
import { APP_BASE } from '@/config/app'

const props = defineProps({ board: { type: Object, required: true }, busy: Boolean })
const emit = defineEmits(['move', 'release'])
const dragging = ref(null)
const overCol = ref(null)
const f = (n) => Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })
const dd = (d) => (d ? new Date(`${String(d).slice(0, 10)}T00:00:00`).toLocaleDateString(undefined, { day: 'numeric', month: 'short' }) : '—')
const ta = (p) => `${APP_BASE}/project-planning?project=${encodeURIComponent(p)}&tab=ta`
const slug = (s) => String(s || '').toLowerCase().replace(/\s+/g, '-')
const queue = (m) => [...m.bookings].sort((a, b) => String(a.planned_start).localeCompare(String(b.planned_start)))
const load = (m) => {
  const cap = m.cells.reduce((a, c) => a + c.capacity, 0)
  return cap > 0 ? Math.round((m.cells.reduce((a, c) => a + c.booked, 0) / cap) * 100) : 0
}
function drag(card) { dragging.value = card }
function drop(ws) {
  overCol.value = null
  const c = dragging.value
  dragging.value = null
  if (!c || c.from === ws) return
  if (!ws) { if (c.from) emit('release', c); return }
  emit('move', { activity: c.activity, item_code: c.item_code, ws, start: c.planned_start })
}
</script>

<style scoped>
.kb { display: flex; gap: 12px; overflow-x: auto; padding-bottom: 8px; align-items: flex-start; }
.col { flex: 0 0 270px; background: var(--slate-50, #f8fafc); border: 1px solid var(--slate-200); border-radius: 10px; padding: 10px;
  display: flex; flex-direction: column; gap: 8px; min-height: 140px; }
.col.over { outline: 2px dashed var(--primary); outline-offset: -2px; background: #eef4ff; }
.col.wait { background: #fffaf0; }
header .name { font-weight: 650; font-size: 14px; }
.sub { font-size: 12px; color: var(--slate-500); }
.bar { height: 4px; background: var(--slate-200); border-radius: 2px; margin-top: 6px; overflow: hidden; }
.bar span { display: block; height: 100%; background: #16a34a; }
.bar span.hot { background: #dc2626; }
.card-k { background: #fff; border: 1px solid var(--slate-200); border-left-width: 4px; border-radius: 8px; padding: 8px 10px;
  cursor: grab; display: flex; flex-direction: column; gap: 3px; }
.card-k:active { cursor: grabbing; }
.s-booked { border-left-color: #94a3b8; } .s-in-progress { border-left-color: #2563eb; }
.s-late { border-left-color: #dc2626; } .s-done { border-left-color: #16a34a; opacity: .7; }
.top { display: flex; justify-content: space-between; align-items: center; gap: 6px; }
.proj { font-size: 12px; font-weight: 600; }
.item { font-weight: 600; font-size: 13px; word-break: break-word; }
.chip { font-size: 11px; padding: 1px 7px; border-radius: 999px; background: var(--slate-100); color: var(--slate-700); white-space: nowrap; }
.c-in-progress { background: #dbeafe; color: #1d4ed8; } .c-late { background: #fee2e2; color: #b91c1c; }
.c-done { background: #dcfce7; color: #166534; } .c-wait { background: #fef3c7; color: #92400e; }
.prog { height: 4px; background: var(--slate-100); border-radius: 2px; overflow: hidden; }
.prog span { display: block; height: 100%; background: #2563eb; }
.foot { display: flex; justify-content: space-between; align-items: flex-start; gap: 6px; }
.link { border: 0; background: none; color: var(--slate-500); font-size: 12px; text-decoration: underline; cursor: pointer; padding: 0; }
.empty { font-size: 12px; color: var(--slate-400); margin: 4px 0; }
</style>
