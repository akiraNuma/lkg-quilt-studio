import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// https://vite.dev/config/
// 変換 API の場所。compose ではサービス名、ローカルでは localhost
const apiTarget =
  process.env.VITE_API_TARGET ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      '/api': { target: apiTarget, changeOrigin: true },
    },
    // Docker のバインドマウント越しでは inotify が届かず HMR が黙る環境がある。
    // 常時ポーリングは CPU を食うので、届かない環境だけ VITE_USE_POLLING=1 を渡す
    watch: process.env.VITE_USE_POLLING
      ? { usePolling: true }
      : undefined,
  },
})
