<template>
  <span v-if="!m" class="sub">—</span>
  <details v-else class="mb">
    <summary :class="tone" :title="title">
      {{ m.status === 'Ready' ? 'Ready' : m.status === 'Partial' ? `${m.pct}% ready` : 'Not ready' }}<template
        v-if="m.status !== 'Ready'"> · {{ m.expected ? `rest ${dd(m.expected)}` : 'nothing planned' }}</template>
    </summary>
    <div class="mb-pop">
      <p v-if="m.no_bom" class="sub">No default BOM: nothing to check.</p>
      <table v-else class="mb-t">
        <thead><tr><th>Input</th><th>Need</th><th>In WIP</th><th>In stores</th><th>On order</th><th>Expected</th></tr></thead>
        <tbody><tr v-for="l in m.inputs" :key="l.item" :class="{ short: l.transferred + l.in_stores < l.need - 1e-6 }">
          <td>{{ l.item }}</td><td>{{ f(l.need) }}</td><td>{{ f(l.transferred) }}</td><td>{{ f(l.in_stores) }}</td>
          <td>{{ f(l.on_order) }}</td><td>{{ l.expected ? dd(l.expected) : '—' }}</td></tr></tbody>
      </table>
      <p class="sub">In WIP = transferred to its Work Orders; in stores = the project's own lots and stock held for it, shared
        with its other stages earliest first; expected = the end of the input's own Time &amp; Action activity.</p>
    </div>
  </details>
</template>

<script setup>
import { computed } from 'vue'
const props = defineProps({ m: { type: Object, default: null } })
const f = (n) => Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })
const dd = (d) => new Date(`${String(d).slice(0, 10)}T00:00:00`).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
const tone = computed(() => (props.m?.status === 'Ready' ? 'ok' : props.m?.late ? 'bad' : 'warn'))
const title = computed(() => (props.m?.late && props.m?.status !== 'Ready' ? 'The rest arrives after this stage is planned to start' : 'Click for the inputs'))
</script>

<style scoped>
.mb { position: relative; display: inline-block; }
.mb summary { list-style: none; cursor: pointer; font-size: 12px; font-weight: 600; padding: 2px 8px; border-radius: 999px; white-space: nowrap; }
.mb summary::-webkit-details-marker { display: none; }
.ok { background: #dcfce7; color: #166534; }
.warn { background: #fef3c7; color: #92400e; }
.bad { background: #fee2e2; color: #b91c1c; }
.mb-pop { margin-top: 6px; background: #fff; border: 1px solid var(--slate-200); border-radius: 8px;
  padding: 10px 12px; width: max-content; max-width: 560px; }   /* opens in place: tables scroll sideways */
.mb-t { width: 100%; border-collapse: collapse; font-size: 12px; }
.mb-t th, .mb-t td { text-align: right; padding: 4px 6px; border-bottom: 1px solid var(--slate-100); white-space: nowrap; }
.mb-t th:first-child, .mb-t td:first-child { text-align: left; }
.mb-t tr.short td { color: #b91c1c; }
.sub { font-size: 11px; color: var(--slate-500); margin: 6px 0 0; white-space: normal; }
</style>
