<!-- Search-as-you-type picker for a Link field (Project, Item, ...). -->
<template>
  <div ref="root" class="lf">
    <input
      v-bind="$attrs" v-model="text" class="form-input" :placeholder="placeholder" :disabled="disabled"
      role="combobox" :aria-expanded="open" autocomplete="off"
      @focus="onFocus" @input="onInput" @keydown.enter.prevent="pickFirst" @keydown.esc="open = false"
    />
    <ul v-if="open" class="lf__list" role="listbox">
      <li v-if="loading" class="lf__hint">Searching…</li>
      <li v-else-if="!options.length" class="lf__hint">No {{ doctype }} found</li>
      <li v-for="o in options" :key="o.name" class="lf__opt" role="option" @mousedown.prevent="pick(o.name)">
        {{ o.name }}<span v-if="o.title && o.title !== o.name" class="lf__title"> — {{ o.title }}</span>
      </li>
    </ul>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { getList } from '@/api/frappe'

// id / aria-* / etc. belong on the <input> (so <label for> works), not on the wrapper div.
defineOptions({ inheritAttrs: false })

const props = defineProps({
  modelValue: { type: String, default: '' },
  doctype: { type: String, required: true },
  placeholder: { type: String, default: 'Search…' },
  filters: { type: Array, default: () => [] },
  disabled: { type: Boolean, default: false },
  // Doctype field to search and show alongside the ID (e.g. "project_name" on Project) —
  // the picked/emitted value is always the ID, this only affects what's searched and shown.
  titleField: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue', 'change'])

const root = ref(null)
const text = ref(props.modelValue)
const options = ref([])
const open = ref(false)
const loading = ref(false)
let timer = null
let seq = 0

watch(() => props.modelValue, (v) => { if (v !== text.value) text.value = v })

async function search() {
  const mine = ++seq
  loading.value = true
  try {
    const q = text.value.trim()
    const fields = props.titleField ? ['name', props.titleField] : ['name']
    // Matching name OR the title field is what makes typing "Test" find PROJ-0001 whose
    // project_name is "Test" — id-only search would miss it entirely.
    const orFilters = q
      ? props.titleField
        ? [[props.doctype, 'name', 'like', `%${q}%`], [props.doctype, props.titleField, 'like', `%${q}%`]]
        : [[props.doctype, 'name', 'like', `%${q}%`]]
      : []
    const rows = await getList(props.doctype, {
      filters: props.filters, orFilters, fields, orderBy: 'modified desc', limit: 15,
    })
    if (mine === seq) options.value = rows.map((r) => ({ name: r.name, title: props.titleField ? r[props.titleField] : '' }))
  } catch {
    if (mine === seq) options.value = []
  } finally {
    if (mine === seq) loading.value = false
  }
}

function onFocus() { open.value = true; search() }
function onInput() {
  open.value = true
  emit('update:modelValue', '')           // typing invalidates the previous pick
  clearTimeout(timer)
  timer = setTimeout(search, 250)
}
function pick(v) {
  text.value = v
  open.value = false
  emit('update:modelValue', v)
  emit('change', v)
}
function pickFirst() { if (options.value.length) pick(options.value[0].name) }

function outside(e) { if (root.value && !root.value.contains(e.target)) open.value = false }
onMounted(() => document.addEventListener('mousedown', outside))
onBeforeUnmount(() => { document.removeEventListener('mousedown', outside); clearTimeout(timer) })
</script>

<style scoped>
.lf { position: relative; }
.lf__list {
  position: absolute; z-index: 50; left: 0; right: 0; top: calc(100% + 4px); max-height: 240px; overflow-y: auto;
  list-style: none; background: #fff; border: 1px solid var(--slate-200); border-radius: var(--radius-md); box-shadow: var(--shadow-lg);
}
.lf__opt, .lf__hint { padding: 9px 12px; font-size: 14px; }
.lf__opt { cursor: pointer; }
.lf__title { color: var(--slate-500); }
.lf__opt:hover { background: var(--primary-soft); }
.lf__hint { color: var(--slate-500); }
</style>
