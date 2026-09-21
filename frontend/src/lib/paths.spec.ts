/**
 * 路径判据（第 40 期）。
 *
 * ## 这组用例的来历
 *
 * 不是「顺手补个单测」，而是一次**本机实测**：向导第 2 步库根、成品目录都填好了，
 * 点「继续」却推不动，红字写着「请输入绝对路径」—— 填的是
 * `C:\Users\…\Temp\nf40e2e\libraries\comics`，**它就是绝对路径**。
 *
 * 根因：判据写死 `raw.startsWith('/')`，把后端 `pathlib.Path(text).resolve()`
 * 抄成了 POSIX 版。同一处比较又只用 `/` 拼前缀，于是「成品目录落在库根里」
 * 这类重叠在 Windows 上**恒判为不重叠**（看着有防护，实际没有）。
 * 生产跑 Linux/Docker，两个错都没露头。
 *
 * ## 为什么用 `win()` 拼路径而不是写反斜杠字面量
 *
 * `'C:\\Users'` 这种字面量要过好几层转义，写错一个就是 `C:Users`
 * —— 仍能编译、仍能跑、只是**静默测了个别的东西**。`win()` 把
 * 「造一个 Windows 路径」这件事写成意图，没有转义可写错。
 */
import { describe, expect, it } from 'vitest'

import { isAbsolutePath, normalizePath, pathsOverlap } from '@/lib/paths'

/** 反斜杠（码点写法，避免字面量转义） */
const BS = String.fromCharCode(92)

/** 把 `/` 分隔的路径写成一个 Windows 风格路径 */
function win(p: string): string {
  return p.split('/').join(BS)
}

describe('lib/paths · 绝对路径判据（与后端 Path.is_absolute 同义）', () => {
  it('Windows 盘符路径算绝对 —— 本机卡住向导的就是这条', () => {
    expect(isAbsolutePath(win('C:/Users/qingr/AppData/Local/Temp/nf40e2e/libraries/comics'))).toBe(true)
    expect(isAbsolutePath('C:/srv/library')).toBe(true)
  })

  it('分隔符混写仍算绝对（默认成品目录就是 `…\\libraries/../output/x` 这种）', () => {
    expect(isAbsolutePath(win('C:/Users/qingr/Temp') + '/nf40e2e/libraries/../output/comic-sorted')).toBe(true)
  })

  it('POSIX 与 UNC 都算 —— 前者是生产环境（Linux/Docker）的实际形状', () => {
    expect(isAbsolutePath('/srv/library/ebooks')).toBe(true)
    expect(isAbsolutePath(`${BS}${BS}nas${BS}share${BS}books`)).toBe(true)
  })

  it('相对路径与半截盘符不算（`C:` / `C:foo` 是「当前盘上的相对路径」，不是绝对）', () => {
    expect(isAbsolutePath('相对/目录')).toBe(false)
    expect(isAbsolutePath('C:')).toBe(false)
    expect(isAbsolutePath('C:foo')).toBe(false)
    expect(isAbsolutePath('')).toBe(false)
  })
})

describe('lib/paths · 重叠检测', () => {
  it('Windows 混写分隔符下也能测出重叠（原来这四种写法全都漏判）', () => {
    const root = win('C:/srv/library/comics')
    expect(pathsOverlap(root, 'C:/srv/library/comics/out')).toBe(true)   // 成品目录在库根里
    expect(pathsOverlap('C:/srv/library/comics/out', root)).toBe(true)   // 反过来（互为祖先）
    expect(pathsOverlap(root, root + BS)).toBe(true)                     // 同一个目录，尾部多个分隔符
    expect(pathsOverlap(root, 'C:/srv/library/comics-out')).toBe(false)  // 同名前缀不算
  })

  it('不去折叠 `..` —— 那是故意的，留给后端 resolve()', () => {
    // 前端预检只覆盖纯字符串就能判定的部分。折叠 `..` 要先知道哪一段是目录名、
    // 哪一段是「上一级」，符号链接更没法纯字符串解析 —— 与其猜，不如漏报：
    // 漏报的代价是「点下去才报 400」，误报的代价是**合法的成品目录永远填不进去**。
    expect(pathsOverlap('C:/srv/lib/../out', 'C:/srv/out')).toBe(false)
  })
})

describe('lib/paths · 归一化', () => {
  it('统一分隔符、折叠重复、去掉尾部分隔符；根路径不被削成空串', () => {
    expect(normalizePath(win('C:/a/b/'))).toBe('C:/a/b')
    expect(normalizePath('C:/a//b///')).toBe('C:/a/b')
    expect(normalizePath('/')).toBe('/')
    expect(normalizePath('')).toBe('')
  })
})
