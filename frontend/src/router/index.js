import { createRouter, createWebHistory } from 'vue-router'
import { APP_BASE } from '@/config/app'
import { pages } from '@/config/pages'
import { isLoggedIn } from '@/api/frappe'
import { useAuthStore } from '@/stores/auth'

const LOGIN = `${APP_BASE}/login`
const HOME = `${APP_BASE}/home`

const routes = [
  { path: '/', redirect: HOME },
  { path: APP_BASE, redirect: HOME },

  { path: LOGIN, name: 'login', component: () => import('@/pages/login/LoginPage.vue'), meta: { public: true } },
  { path: `${APP_BASE}/no-access`, name: 'no-access', component: () => import('@/pages/NoAccessPage.vue'), meta: { noRoleCheck: true } },

  ...pages.map((p) => (p.redirect
    ? { path: `${APP_BASE}/${p.path}`, name: p.path, redirect: p.redirect }
    : {
        path: `${APP_BASE}/${p.path}`,
        name: p.path,
        component: p.component,
        meta: { title: p.title, section: p.section },
      })),

  { path: '/:pathMatch(.*)*', name: 'not-found', component: () => import('@/pages/NotFoundPage.vue'), meta: { noRoleCheck: true } },
]

const router = createRouter({ history: createWebHistory(), routes })

// window.__FRAPPE_SESSION__.user is set synchronously in main.js (from the
// user_id cookie) before the router is created, so this is safe on the very
// first navigation.
router.beforeEach(async (to) => {
  const loggedIn = isLoggedIn()

  if (!to.meta.public && !loggedIn) {
    return { path: LOGIN, query: { redirect: to.fullPath } }
  }
  if (to.path === LOGIN && loggedIn) return { path: HOME }

  if (loggedIn && !to.meta.public && !to.meta.noRoleCheck) {
    const auth = useAuthStore()
    await auth.loadUserDetails()
    if (!auth.hasAccess) return { path: `${APP_BASE}/no-access` }
  }
  return true
})

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} — Planning` : 'Planning — Pranera'
})

export default router
