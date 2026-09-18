import { fileURLToPath, URL } from 'node:url'

import tailwindcss from '@tailwindcss/vite'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

/**
 * 构建产物的部署路径。
 * 由 FastAPI 的 /static 挂载点提供服务，因此默认落在 /static/v2/ 之下。
 * 将来 v1 退役、本应用迁到 /static/ 根时，只需改这里（或设环境变量 VITE_BASE）。
 */
const BUILD_BASE = process.env.VITE_BASE ?? '/static/v2/'

/** 开发期后端（docker-compose.test.yml 暴露的 FastAPI） */
const BACKEND = process.env.VITE_BACKEND ?? 'http://localhost:8993'

export default defineConfig(({ command }) => ({
  // 开发期挂在根路径，构建产物带真实部署前缀
  base: command === 'build' ? BUILD_BASE : '/',

  plugins: [vue(), tailwindcss()],

  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },

  build: {
    // 先产物到 dist，再由 `npm run deploy` 同步到 novelforge/static/v2，
    // 避免构建失败时把现有界面覆盖掉（可回滚）。
    outDir: 'dist',
    emptyOutDir: true,
    assetsDir: 'assets',
    sourcemap: false,
  },

  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    allowedHosts: true,
    proxy: {
      '/api': { target: BACKEND, changeOrigin: true },
      '/health': { target: BACKEND, changeOrigin: true },
      '/download': { target: BACKEND, changeOrigin: true },
      '/convert': { target: BACKEND, changeOrigin: true },
    },
  },
}))
