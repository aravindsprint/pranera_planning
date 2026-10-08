<template>
  <div>
    <div class="cal-bar">
      <button class="btn btn-outline sm" aria-label="Previous month" @click="$emit('month', -1)"><i class="pi pi-chevron-left"></i></button>
      <h2 class="h2">{{ monthLabel }}</h2>
      <button class="btn btn-outline sm" aria-label="Next month" @click="$emit('month', 1)"><i class="pi pi-chevron-right"></i></button>
      <span class="mach sub">{{ machine ? board.machines[0].label : `All ${board.stage} machines` }} · choose one in Machine above</span>
    </div>
    <div class="cal" role="grid" :aria-label="`Bookings in ${monthLabel}`">
      <div v-for="w in WEEKDAYS" :key="w" class="dow" role="columnheader">{{ w }}</div>
      <div v-for="d in board.dates" :key="d" class="day" role="gridcell"
           :class="{ out: !inMonth(d), today: d === todayStr, off: isOff(d) }">
        <div class="dnum">{{ Number(d.slice(8, 10)) }}<span v-if="machine && cap(d)" class="cap">{{ pct(d) }}</span></div>
        <a v-for="b in on(d)" :key="b.activity + d" class="ev" :class="`s-${slug(b.status)}`" :href="ta(b.project)"
           :title="`${b.machine} · ${b.project} · ${b.item_code} · ${f(b.qty)} ${b.uom} · ${b.planned_start} → ${b.planned_end} · ${b.status}`">
          <span v-if="!machine" class="m">{{ b.machine }}</span>{{ b.project }} · {{ b.item_code }}
        </a>
      </div>
    </div>
    <p class="sub legend"><i class="sw s-booked"></i>booked <i class="sw s-in-progress"></i>in progress <i class="sw s-late"></i>late
      <i class="sw s-done"></i>done · a booking shows on each day it runs (start up to its planned end) · click to open its Time &amp; Action</p>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { APP_BASE } from '@/config/app'

const props = defineProps({ board: { type: Object, required: true }, month: { type: String, required: true } })
defineEmits(['month'])
const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
// one machine chosen (the page's Machine filter): show its daily load and holidays too
const machine = computed(() => (props.board.machines.length === 1 ? props.board.machines[0].name : ''))
const todayStr = new Date().toISOString().slice(0, 10)
const f = (n) => Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })
const slug = (s) => String(s || '').toLowerCase().replace(/\s+/g, '-')
const ta = (p) => `${APP_BASE}/project-planning?project=${encodeURIComponent(p)}&tab=ta`
const monthLabel = computed(() => new Date(`${props.month}-01T00:00:00`).toLocaleDateString(undefined, { month: 'long', year: 'numeric' }))
const inMonth = (d) => d.slice(0, 7) === props.month
const all = computed(() => props.board.machines.flatMap((m) => m.bookings.map((b) => ({ ...b, machine: m.label, ws: m.name }))))
const runs = (b, d) => (b.planned_end > b.planned_start ? b.planned_start <= d && d < b.planned_end : d === b.planned_start)
const on = (d) => all.value.filter((b) => (!machine.value || b.ws === machine.value) && runs(b, d))
const cell = (d) => props.board.machines.find((m) => m.name === machine.value)?.cells.find((c) => c.date === d)
const cap = (d) => cell(d)?.capacity
const pct = (d) => `${cell(d)?.pct ?? 0}%`
const isOff = (d) => (machine.value ? cell(d) && !cell(d).capacity : false)
</script>

<style scoped>
.cal-bar { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; flex-wrap: wrap; }
.h2 { margin: 0; font-size: 16px; font-weight: 650; min-width: 170px; text-align: center; }
.mach { margin-left: auto; max-width: 280px; }
.btn.sm { padding: 4px 10px; }
.cal { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); border: 1px solid var(--slate-200); border-radius: 10px; overflow: hidden; background: #fff; }
.dow { padding: 6px 8px; font-size: 12px; font-weight: 600; color: var(--slate-500); background: var(--slate-50, #f8fafc); border-bottom: 1px solid var(--slate-200); }
.day { min-height: 104px; border-right: 1px solid var(--slate-100); border-bottom: 1px solid var(--slate-100); padding: 4px 5px; display: flex; flex-direction: column; gap: 3px; }
.day.out { background: #fafafa; color: var(--slate-400); }
.day.today { box-shadow: inset 0 0 0 2px #f59e0b; }
.day.off { background: repeating-linear-gradient(45deg, #f8fafc, #f8fafc 5px, #eef2f7 5px, #eef2f7 10px); }
.dnum { font-size: 12px; font-weight: 600; display: flex; justify-content: space-between; }
.cap { font-weight: 400; color: var(--slate-500); }
.ev { display: block; font-size: 11px; line-height: 1.3; padding: 2px 5px; border-radius: 4px; text-decoration: none; color: #0f172a;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; border-left: 3px solid; }
.ev .m { font-weight: 700; margin-right: 4px; }
.s-booked { background: #f1f5f9; border-color: #94a3b8; } .s-in-progress { background: #dbeafe; border-color: #2563eb; }
.s-late { background: #fee2e2; border-color: #dc2626; } .s-done { background: #dcfce7; border-color: #16a34a; }
.sub { font-size: 12px; color: var(--slate-500); }
.legend { margin-top: 8px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.sw { display: inline-block; width: 12px; height: 12px; border-radius: 3px; border-left: 3px solid; vertical-align: middle; }
</style>
