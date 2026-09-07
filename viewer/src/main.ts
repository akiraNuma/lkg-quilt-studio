import { createApp } from 'vue'
import App from './App.vue'
import './styles.css'

// This app uses no Service Worker. When another project has used the same localhost port, its
// registration survives and intercepts fetches (a leftover hitting /api/projects 500 times a
// second stopped previews from arriving). Unregister them on startup
if ('serviceWorker' in navigator) {
  void navigator.serviceWorker.getRegistrations().then(found => {
    for (const registration of found) void registration.unregister()
  })
}

createApp(App).mount('#app')
