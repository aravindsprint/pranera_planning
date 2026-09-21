<!--
  Starting point for a new page. NOT routed — copy it, don't edit it.

    1. cp -r src/pages/_template src/pages/<slug> and rename the file
    2. register it in src/config/pages.js
    3. swap DOCTYPE / FIELDS / columns below for the real thing

  Shows the standard shape: header, toolbar, load / error / empty / data states.
-->
<template>
  <div class="page">
    <AppHeader />

    <main class="page-content">
      <div class="page-toolbar">
        <input v-model="search" class="form-input search" placeholder="Search…" @keyup.enter="load" />
        <div class="page-toolbar__grow"></div>
        <button class="btn btn-outline" :disabled="loading" @click="load">
          <i class="pi pi-refresh"></i> Refresh
        </button>
      </div>

      <div v-if="error" class="alert alert-error" role="alert">{{ error }}</div>

      <div v-if="loading" class="loading-center"><div class="spinner"></div></div>

      <div v-else-if="!rows.length" class="card">
        <div class="empty-state">
          <div class="empty-state__title">Nothing to show</div>
          <div class="empty-state__sub">No {{ DOCTYPE }} records match.</div>
        </div>
      </div>

      <div v-else class="table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Status</th>
              <th class="num">Qty</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in rows" :key="r.name">
              <td>{{ r.name }}</td>
              <td><span class="badge badge-secondary">{{ r.status }}</span></td>
              <td class="num">{{ r.qty }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import AppHeader from '@/components/AppHeader.vue'
import { getList } from '@/api/frappe'

const DOCTYPE = 'Work Order'                       // ← replace
const FIELDS = ['name', 'status', 'qty']           // ← replace

const rows = ref([])
const loading = ref(false)
const error = ref('')
const search = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    rows.value = await getList(DOCTYPE, {
      fields: FIELDS,
      filters: search.value ? [[DOCTYPE, 'name', 'like', `%${search.value}%`]] : [],
      orderBy: 'modified desc',
      limit: 100,
    })
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.search { max-width: 280px; }
</style>
