<template>
  <router-view />
</template>

<script setup>
import { onMounted } from 'vue'
import { initCSRF } from '@/api/frappe'

// Pre-warm the CSRF token so the first write doesn't have to fetch it.
onMounted(initCSRF)
</script>
