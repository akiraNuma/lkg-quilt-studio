import { createApp } from 'vue'
import App from './App.vue'
import './styles.css'

// このアプリは Service Worker を使わない。localhost の同じポートを別プロジェクトで
// 使っていると、その登録が残って fetch を横取りする（実際に /api/projects を
// 毎秒 500 回叩く残骸を踏んで、プレビューが届かなくなった）。開いた時点で外す
if ('serviceWorker' in navigator) {
  void navigator.serviceWorker.getRegistrations().then(found => {
    for (const registration of found) void registration.unregister()
  })
}

createApp(App).mount('#app')
