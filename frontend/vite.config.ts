/// <reference types="vitest/config" />
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

  /**
   * 前端单测（第 39 期）。
   *
   * 刻意**不新建 `vitest.config.ts`**：上面 `resolve.alias` 的 `@` 是**唯一**的 `@` 定义，
   * 另起一个配置文件就得把它复制一份 —— 那正是本仓库一直在避免的「两处各写一遍」。
   * 用 `/// <reference types="vitest/config" />` 让 `defineConfig` 认 `test` 字段即可。
   *
   * 也刻意**不开 `globals`**：spec 一律显式 `import { describe, it, expect } from 'vitest'`。
   * 开了就得往 tsconfig 的 `types` 里加东西，而 spec 文件在 `src/**` 下、本来就被
   * `vue-tsc --build` 类型检查 —— 显式 import 让这条检查保持干净。
   */
  test: {
    environment: 'happy-dom',
    include: ['src/**/*.spec.ts'],
    clearMocks: true,
    restoreMocks: true,
    // 组件测试不校验样式产物；关掉省掉一条 tailwind 处理链
    css: false,

    /**
     * ⚠️ 全量并行下的超时（第 116 期）：默认 5 s，实测**不够**。
     *
     * 第 103 / 104 期各复现一次偶发红（先 `ReadingLogTab.spec.ts` 的「重试按钮真的会再拉一次」、
     * 后又换成同文件另一条），**都是** `Test timed out in 5000ms`；单跑该文件 12 例 453 ms 全绿、
     * 紧接着全量复跑 686 passed ⇒ 不是用例坏了。
     *
     * 根因是**环境创建**：vitest 给**每个 spec 文件**各建一次 happy-dom（`isolate` 默认开），
     * 代价随机器负载浮动 —— 第 104 期记到 `67 次 / 256.61 s，占 tracked time 55%`，
     * 第 116 期同机再跑是 `69 次 / 72.75 s，48%`。这几秒被记在**恰好排在环境创建之后**的
     * 那条用例头上 ⇒ **命中的用例会换，别按行号认领**。
     *
     * 放宽到 15 s 覆盖这个抖动；**不是**在掩盖死循环 —— 真挂住的用例 15 s 同样会红。
     * 若还要继续压这块成本，vitest 自己给的方向是 `pool: 'vmThreads'`（每个 worker 只建一次环境、
     * 仍保留文件间隔离）或 `isolate: false`（全量共用一个环境）—— 那会动 717 例的隔离语义，
     * 属**另一件事**，别在没实测前顺手开。
     */
    testTimeout: 15000,
  },
}))
