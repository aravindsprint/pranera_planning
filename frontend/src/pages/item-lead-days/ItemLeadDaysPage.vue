<template>
  <div class="page">
    <AppHeader subtitle="Items whose lead days differ from their supplier's usual days" />

    <main class="page-content">
      <div v-if="error" class="alert alert-error" role="alert">{{ error }}</div>
      <div v-if="saved" class="alert alert-success" role="status">{{ saved }}</div>
      <div v-if="loading && !d" class="loading-center"><div class="spinner"></div></div>

      <template v-else-if="d">
        <div class="toolbar">
          <span class="sub">
            Which of these numbers counts is set in
            <a :href="`${APP_BASE}/reorder-settings`">Re-order Settings › Supplier lead days</a>.
            Every item from a supplier: <a :href="`${APP_BASE}/supplier-lead-days`">Supplier Lead Days</a>.
            <template v-if="!d.can_write"> You can view these numbers but not change them.</template>
          </span>
          <div class="toolbar__actions">
            <input v-model.trim="search" class="form-input search" placeholder="Find a supplier or item" aria-label="Find a supplier or item" />
            <button class="btn btn-primary" :disabled="busy || !d.can_write || !dirty" @click="save">{{ busy ? 'Saving…' : 'Save' }}</button>
          </div>
        </div>
        <p v-if="!d.lead_fields_ready" class="warn-line">The supplier lead day fields aren't installed yet: run bench migrate.</p>

        <section class="card">
          <div class="card__head">
            <h2 class="h2">One item from one supplier</h2>
            <span class="sub">{{ plural(filled(d.item_supplier_leads, 'item_code', 'lead_days'), 'exception') }}</span>
          </div>
          <p class="hint">Only where an item differs from its supplier's usual days, e.g. melange 45. Stored on the Item's Supplier Items row as <i>Lead days</i>.</p>
          <table class="data-table">
            <thead><tr><th>Item</th><th>Supplier</th><th class="num">Lead days</th><th></th></tr></thead>
            <tbody>
              <tr v-if="!shownItems.length"><td colspan="4" class="empty">{{ search ? 'No item matches.' : 'None yet.' }}</td></tr>
              <tr v-for="r in shownItems" :key="r._k">
                <td class="wide"><LinkField v-model="r.item_code" doctype="Item" placeholder="Item" :disabled="!d.can_write" /></td>
                <td class="wide"><LinkField v-model="r.supplier" doctype="Supplier" placeholder="Supplier" :disabled="!d.can_write" /></td>
                <td class="num"><input v-model.number="r.lead_days" type="number" min="0" step="1" class="form-input n"
                                       :aria-label="`Lead days for ${r.item_code || 'new item'}`" :disabled="!d.can_write" /></td>
                <td class="act"><button v-if="d.can_write" class="icon-btn" :aria-label="`Remove ${r.item_code || 'row'}`" @click="drop(d.item_supplier_leads, r)"><i class="pi pi-times"></i></button></td>
              </tr>
            </tbody>
          </table>
          <button v-if="d.can_write && d.lead_fields_ready" class="btn btn-outline add" @click="add(d.item_supplier_leads, { item_code: '', supplier: '', lead_days: null })">+ Add item</button>
        </section>

        <p class="hint">Removing a row clears its lead days; the Item's Supplier Items row itself stays, as it may carry a part number. After saving, use Recalculate now in Re-order Settings (or wait for tonight) for the re-order levels to follow.</p>
      </template>
    </main>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import AppHeader from '@/components/AppHeader.vue'
import LinkField from '@/components/LinkField.vue'
import { callMessage } from '@/api/frappe'
import { APP_BASE } from '@/config/app'

const d = ref(null)
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const saved = ref('')
const dirty = ref(false)
const search = ref('')
let original = ''
let seq = 0

// _k keeps each row's identity while filtering; it is stripped before saving and comparing.
const keyed = (rows) => (rows || []).map((r) => ({ ...r, _k: ++seq }))
const plain = (v) => JSON.stringify(v.item_supplier_leads.map(({ _k, ...r }) => r))
const filled = (rows, key, days) => rows.filter((r) => r[key] && r[days] > 0).length
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`
const match = (...xs) => !search.value || xs.some((x) => (x || '').toLowerCase().includes(search.value.toLowerCase()))
// New, still-empty rows always show, so a row just added doesn't vanish under a search.
const shownItems = computed(() => (d.value?.item_supplier_leads || []).filter((r) => !r.item_code || match(r.item_code, r.supplier)))

function take(res) {
  d.value = { ...res, item_supplier_leads: keyed(res.item_supplier_leads) }
  original = plain(d.value)
  dirty.value = false
}
function add(list, row) { list.push({ ...row, _k: ++seq }) }
function drop(list, row) { list.splice(list.indexOf(row), 1) }

async function load() {
  loading.value = true
  error.value = ''
  try {
    take(await callMessage('pranera_planning.api.supplier_lead_days.get_lead_days'))
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}
watch(d, (v) => { if (v) dirty.value = plain(v) !== original }, { deep: true })

async function save() {
  busy.value = true
  error.value = ''
  saved.value = ''
  try {
    const strip = (rows) => rows.map(({ _k, ...r }) => r)
    take(await callMessage('pranera_planning.api.supplier_lead_days.save_lead_days', {
      data: { item_supplier_leads: strip(d.value.item_supplier_leads) },
    }))
    saved.value = 'Saved. Recalculate in Re-order Settings (or wait for tonight) for the re-order levels to follow.'
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}
onMounted(load)
</script>

<style scoped>
.toolbar { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 16px; }
.toolbar__actions { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
.search { width: 240px; }
.card { margin-bottom: 16px; }
.card__head { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; }
.h2 { margin: 0 0 6px; font-size: 16px; font-weight: 650; }
.hint, .sub { font-size: 12px; color: var(--slate-500); }
.hint { margin: 0 0 10px; }
.num { text-align: right; white-space: nowrap; }
.form-input.n { width: 110px; text-align: right; }
td.wide { min-width: 260px; }
.act { width: 40px; text-align: right; }
.icon-btn { border: 0; background: transparent; cursor: pointer; color: var(--slate-500); padding: 4px; }
.empty { color: var(--slate-500); font-size: 13px; }
.add { margin-top: 10px; }
.warn-line { margin: 0 0 12px; font-size: 13px; color: #9a3412; }
.alert-success { background: #ecfdf3; border: 1px solid #bbe5c8; color: #166534; border-radius: 8px; padding: 10px 14px; margin-bottom: 12px; font-size: 13px; }
@media (max-width: 640px) { .search { width: 100%; } td.wide { min-width: 180px; } }
</style>
