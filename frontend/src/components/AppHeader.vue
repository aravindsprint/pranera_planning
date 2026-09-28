<template>
  <div>
    <transition name="fade">
      <div v-if="drawerOpen" class="overlay" @click="drawerOpen = false"></div>
    </transition>

    <transition name="slide">
      <aside v-if="drawerOpen" class="drawer" aria-label="Main menu">
        <div class="drawer__head">
          <div class="avatar">{{ initials }}</div>
          <div class="who">
            <div class="who__name">{{ auth.displayName || 'User' }}</div>
            <div class="who__role">{{ auth.designation || auth.frappeUser }}</div>
          </div>
          <button class="drawer__close" @click="drawerOpen = false" aria-label="Close menu">
            <i class="pi pi-times"></i>
          </button>
        </div>

        <nav class="drawer__nav">
          <template v-for="group in groups" :key="group.section">
            <div v-if="group.section" class="drawer__section">{{ group.section }}</div>
            <button
              v-for="p in group.items" :key="p.path"
              class="link" :class="{ 'link--active': route.name === p.path }"
              @click="go(`${APP_BASE}/${p.path}`)"
            >
              <i :class="p.icon || 'pi pi-circle'"></i><span>{{ p.title }}</span>
            </button>
          </template>
        </nav>

        <div class="drawer__foot">
          <a class="link" href="/app"><i class="pi pi-external-link"></i><span>Open ERPNext desk</span></a>
          <button class="link link--danger" @click="logout"><i class="pi pi-sign-out"></i><span>Log out</span></button>
        </div>
      </aside>
    </transition>

    <header class="bar">
      <button class="bar__btn" @click="drawerOpen = true" aria-label="Open menu"><i class="pi pi-bars"></i></button>
      <button v-if="showBack" class="bar__btn" @click="router.back()" aria-label="Back"><i class="pi pi-arrow-left"></i></button>
      <div class="bar__title">
        <div class="bar__h">{{ title || route.meta.title || APP_TITLE }}</div>
        <div v-if="subtitle" class="bar__sub">{{ subtitle }}</div>
      </div>
      <button
        v-if="isDev" class="bar__env" :class="`bar__env--${mode}`"
        :title="`Backend: ${backendLabel()} — click to change`"
        @click="router.push(`${APP_BASE}/settings`)"
      >{{ mode === 'live' ? 'LIVE' : 'LOCAL' }}</button>
      <slot name="actions" />
    </header>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { APP_BASE, APP_TITLE } from '@/config/app'
import { pages } from '@/config/pages'
import { isDev, currentBackend, backendLabel } from '@/config/backend'

defineProps({
  title: { type: String, default: '' },      // defaults to the page's title from config/pages.js
  subtitle: { type: String, default: '' },
  showBack: { type: Boolean, default: false },
})

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const drawerOpen = ref(false)
const mode = currentBackend()

// Group nav entries by section, keeping the order they appear in pages.js.
const groups = computed(() => {
  const map = new Map()
  for (const p of pages.filter((p) => p.nav)) {
    if (!map.has(p.section || '')) map.set(p.section || '', [])
    map.get(p.section || '').push(p)
  }
  return [...map].map(([section, items]) => ({ section, items }))
})

const initials = computed(() =>
  (auth.displayName || '').split(/\s+|@/).filter(Boolean).map((w) => w[0]).join('').toUpperCase().slice(0, 2) || 'PL'
)

function go(path) {
  drawerOpen.value = false
  router.push(path)
}

async function logout() {
  drawerOpen.value = false
  await auth.logout()
  router.push(`${APP_BASE}/login`)
}
</script>

<style scoped>
.overlay { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.45); z-index: 200; }

.drawer {
  position: fixed; top: 0; left: 0; bottom: 0; width: 280px; z-index: 300;
  background: #fff; display: flex; flex-direction: column; box-shadow: var(--shadow-lg); overflow-y: auto;
}
.drawer__head { background: var(--primary); padding: 18px 16px; display: flex; align-items: center; gap: 12px; }
.avatar {
  width: 42px; height: 42px; border-radius: 50%; background: rgba(255, 255, 255, 0.18); color: #fff;
  font-size: 14px; font-weight: 700; display: flex; align-items: center; justify-content: center; flex-shrink: 0;
}
.who { flex: 1; min-width: 0; }
.who__name { font-size: 14px; font-weight: 650; color: #fff; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.who__role { font-size: 12px; color: rgba(255, 255, 255, 0.75); margin-top: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.drawer__close {
  background: rgba(255, 255, 255, 0.15); border: none; color: #fff; width: 30px; height: 30px;
  border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 12px;
}

.drawer__nav { padding: 10px 8px; flex: 1; }
.drawer__section { font-size: 12px; font-weight: 600; color: var(--slate-400); padding: 12px 10px 4px; }
.drawer__foot { padding: 8px; border-top: 1px solid var(--slate-100); }

.link {
  width: 100%; display: flex; align-items: center; gap: 12px; padding: 10px; margin-bottom: 2px;
  border: none; border-radius: var(--radius-md); background: none; text-align: left; text-decoration: none;
  font-size: 14px; font-weight: 500; color: var(--slate-700);
}
.link i { width: 20px; text-align: center; font-size: 15px; color: var(--slate-500); }
.link:hover { background: var(--slate-100); }
.link--active { background: var(--primary-soft); color: var(--primary); font-weight: 650; }
.link--active i { color: var(--primary); }
.link--danger, .link--danger i { color: var(--red-600); }

.bar {
  position: sticky; top: 0; z-index: 100; height: var(--header-h); width: 100%;
  background: var(--primary); color: #fff; padding: 0 12px; display: flex; align-items: center; gap: 10px;
  box-shadow: 0 1px 4px rgba(15, 23, 42, 0.2);
}
.bar__btn {
  background: rgba(255, 255, 255, 0.14); border: 1px solid rgba(255, 255, 255, 0.2); color: #fff;
  width: 36px; height: 36px; border-radius: var(--radius-sm); display: flex; align-items: center; justify-content: center; flex-shrink: 0;
}
.bar__btn:hover { background: rgba(255, 255, 255, 0.24); }
.bar__title { flex: 1; min-width: 0; }
.bar__env {
  border: 1px solid rgba(255, 255, 255, 0.55); color: #fff; font-size: 11px; font-weight: 800; letter-spacing: 0.06em;
  padding: 4px 9px; border-radius: 999px; flex-shrink: 0;
}
.bar__env--live { background: #b91c1c; }
.bar__env--local { background: #047857; }
.bar__h { font-size: 17px; font-weight: 650; }
.bar__sub { font-size: 12px; opacity: 0.8; margin-top: 1px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.slide-enter-active, .slide-leave-active { transition: transform 0.22s ease; }
.slide-enter-from, .slide-leave-to { transform: translateX(-100%); }
.fade-enter-active, .fade-leave-active { transition: opacity 0.22s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
@media (prefers-reduced-motion: reduce) {
  .slide-enter-active, .slide-leave-active, .fade-enter-active, .fade-leave-active { transition: none; }
}
</style>
