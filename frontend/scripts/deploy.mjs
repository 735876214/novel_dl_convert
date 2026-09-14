#!/usr/bin/env node
/**
 * 把 frontend/dist 同步到 novelforge/static/v2。
 *
 * 采用「先删除、再整体拷贝」而不是增量覆盖，避免上一版构建遗留的
 * 旧 hash 资源文件一直堆在目录里。
 *
 * 注意：这会清空目标目录，请确认构建已通过再执行。
 */
import { cpSync, existsSync, rmSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const source = resolve(here, '..', 'dist')
const target = resolve(here, '..', '..', 'novelforge', 'static', 'v2')

if (!existsSync(source)) {
  console.error(`[deploy] 找不到构建产物：${source}`)
  console.error('[deploy] 请先执行 npm run build')
  process.exit(1)
}

rmSync(target, { recursive: true, force: true })
cpSync(source, target, { recursive: true })

console.log(`[deploy] 已同步：${source}`)
console.log(`[deploy]       → ${target}`)
