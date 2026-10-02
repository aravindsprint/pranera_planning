import { APP_BASE } from '@/config/app'
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
    path: 'project-planning',
    title: 'Project Planning',
    icon: 'pi pi-sitemap',
    section: 'Planning',
    nav: true,
    component: () => import('@/pages/project-planning/ProjectPlanningPage.vue'),
  },

  // The two pages that became tabs of Project Planning: old links and bookmarks land on the right tab.
  {
    path: 'project-stock-reservation',
    title: 'Stock Reservation',
    nav: false,
    redirect: (to) => ({ path: `${APP_BASE}/project-planning`, query: { ...to.query, tab: 'stock' } }),
  },

  {
    path: 'plan',
    title: 'Plan Project',
    nav: false,
    redirect: (to) => ({
      path: `${APP_BASE}/project-planning`,
      query: to.query.project && !to.query.item ? { project: to.query.project, tab: 'plan' } : { ...to.query, new: '1' },
    }),
  },

  {
    path: 'reorder-report',
    title: 'Stock Levels & Re-order',
    icon: 'pi pi-chart-bar',
    section: 'Planning',
    nav: true,
    component: () => import('@/pages/reorder-report/ReorderReportPage.vue'),
  },

  {
    path: 'reorder-settings',
    title: 'Re-order Settings',
    icon: 'pi pi-sliders-h',
    section: 'Planning',
    nav: true,
    component: () => import('@/pages/reorder-settings/ReorderSettingsPage.vue'),
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
