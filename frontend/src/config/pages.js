// Single source of truth for pages. The router and the side-drawer menu are both
// generated from this list, so adding a page is:
//
//   1. create src/pages/<slug>/<Name>Page.vue   (copy pages/_template/TemplatePage.vue)
//   2. add one entry below
//
//   path      URL segment  ->  /planning-app/<path>
//   title     drawer label and default header title
//   icon      a PrimeIcons class (https://primevue.org/icons)
//   section   drawer group heading; entries with the same section are grouped
//   nav       false = routable but hidden from the drawer (detail/edit pages)
//   component always lazy-imported so each page is its own chunk

export const pages = [
  {
    path: 'home',
    title: 'Home',
    icon: 'pi pi-home',
    section: '',
    nav: true,
    component: () => import('@/pages/home/HomePage.vue'),
  },

  {
    path: 'project-stock-reservation',
    title: 'Stock Reservation',
    icon: 'pi pi-lock',
    section: 'Planning',
    nav: true,
    component: () => import('@/pages/project-stock-reservation/ProjectStockReservationPage.vue'),
  },

  {
    path: 'settings',
    title: 'Settings',
    icon: 'pi pi-cog',
    section: 'System',
    nav: true,
    component: () => import('@/pages/settings/SettingsPage.vue'),
  },

  // ── Add pages below ────────────────────────────────────────────────────────
  // {
  //   path: 'production-plan',
  //   title: 'Production Plan',
  //   icon: 'pi pi-calendar',
  //   section: 'Planning',
  //   nav: true,
  //   component: () => import('@/pages/production-plan/ProductionPlanPage.vue'),
  // },
]
