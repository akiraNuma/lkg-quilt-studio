import { defineConfig, mergeConfig } from 'vitest/config'
import viteConfig from './vite.config.ts'

// plugin / alias は vite.config.ts が正本。ここでは test の設定だけを足す
export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      include: ['src/**/*.test.ts'],
    },
  })
)
