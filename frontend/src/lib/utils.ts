import type { ClassValue } from 'clsx'
import { clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

/**
 * 类名合并（第 90 期）。
 *
 * 逐字照搬 BookOrbit 的 `lib/utils.ts`：`clsx` 负责条件拼接，`tailwind-merge`
 * 负责「后写的同类工具类覆盖先写的」（`px-2 px-4` ⇒ 只留 `px-4`）。
 *
 * ⚠️ 为什么必须要 `twMerge` 而不是只用 `clsx`：移植来的 shadcn-vue 基础组件
 * 都写成 `cn(基础类, props.class)`，调用方要靠**传 class 覆盖**基础类
 * （如折叠态把 `px-2` 改成 `px-0`）。只 `clsx` 拼接的话两个类都在，
 * 谁生效取决于生成顺序 ⇒ 覆盖「有时灵有时不灵」。
 *
 * 本文件是 `cn` 的**唯一实现**，组件里别再各写一遍。
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}
