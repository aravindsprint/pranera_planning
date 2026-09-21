import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { ALLOWED_ROLES } from '@/config/app'
import {
  call, getList, ensureCSRF, resetCSRF, readSessionFromCookie, isLoggedIn as sessionIsLoggedIn,
} from '@/api/frappe'

export const useAuthStore = defineStore('auth', () => {
  const frappeUser = ref(window.__FRAPPE_SESSION__?.user || '')
  const isLoggedIn = ref(sessionIsLoggedIn())

  const fullName = ref('')
  const designation = ref('')
  const employee = ref(null)
  const roles = ref([])
  const detailsLoadedFor = ref('')
  const loading = ref(false)
  const error = ref('')

  // window.__FRAPPE_SESSION__ is a plain object Vue can't observe, so mirror it
  // into refs explicitly whenever the session changes.
  function refreshSession() {
    const u = readSessionFromCookie().user
    frappeUser.value = u
    isLoggedIn.value = sessionIsLoggedIn()
  }

  // Employee + roles for the current user. Never throws: a missing Employee
  // record or a failed roles call must not lock people out of the app — the
  // DocType permissions on the server are what actually protect the data.
  async function loadUserDetails() {
    if (!isLoggedIn.value || detailsLoadedFor.value === frappeUser.value) return
    loading.value = true
    try {
      const [emp, roleList] = await Promise.allSettled([
        getList('Employee', {
          filters: [['user_id', '=', frappeUser.value]],
          fields: ['name', 'employee_name', 'designation', 'department'],
          limit: 1,
        }),
        call('frappe.core.doctype.user.user.get_roles', { uid: frappeUser.value }),
      ])
      if (emp.status === 'fulfilled' && emp.value[0]) {
        employee.value = emp.value[0]
        fullName.value = emp.value[0].employee_name || ''
        designation.value = emp.value[0].designation || ''
      }
      if (roleList.status === 'fulfilled') roles.value = roleList.value.message || []
      else console.warn('Could not load roles:', roleList.reason?.message)
      detailsLoadedFor.value = frappeUser.value
    } finally {
      loading.value = false
    }
  }

  const displayName = computed(() => fullName.value || frappeUser.value)

  // Empty ALLOWED_ROLES = open to everyone logged in. If roles could not be
  // loaded, fail open (see loadUserDetails).
  const hasAccess = computed(() => {
    if (!ALLOWED_ROLES.length) return true
    if (!roles.value.length) return true
    return ALLOWED_ROLES.some((r) => roles.value.includes(r))
  })

  // The caller should do a full page load afterwards (window.location.href):
  // re-running main.js against the fresh session cookie is the only reliably
  // working path, same as pranera_knit.
  async function login(email, password) {
    loading.value = true
    error.value = ''
    try {
      const res = await fetch('/api/method/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({ usr: email, pwd: password }).toString(),
        credentials: 'include',
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok || data.message !== 'Logged In') {
        let msg = 'Incorrect email or password'
        try {
          const msgs = JSON.parse(data._server_messages || '[]')
          if (msgs.length) msg = JSON.parse(msgs[msgs.length - 1]).message || msg
        } catch { /* keep default */ }
        throw new Error(msg)
      }
      return true
    } catch (err) {
      error.value = err.message || 'Login failed'
      throw err
    } finally {
      loading.value = false
    }
  }

  async function logout() {
    try {
      const token = await ensureCSRF()
      await fetch('/api/method/frappe.auth.logout', {
        method: 'POST',
        headers: { 'X-Frappe-CSRF-Token': token },
        credentials: 'include',
      })
    } catch { /* clear local state regardless */ }
    resetCSRF()
    fullName.value = ''
    designation.value = ''
    employee.value = null
    roles.value = []
    detailsLoadedFor.value = ''
    if (window.__FRAPPE_SESSION__) window.__FRAPPE_SESSION__.user = 'Guest'
    frappeUser.value = 'Guest'
    isLoggedIn.value = false
  }

  return {
    frappeUser, isLoggedIn, fullName, displayName, designation, employee, roles,
    loading, error, hasAccess,
    refreshSession, loadUserDetails, login, logout,
  }
})
