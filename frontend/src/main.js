import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { readSessionFromCookie } from '@/api/frappe'
import 'primeicons/primeicons.css'
import '@/styles/base.css'

// Must run before the router and stores exist: both read the session user.
readSessionFromCookie()

createApp(App).use(createPinia()).use(router).mount('#app')
