import { describe, expect, it } from 'vitest'

import { canJumpTo, chapterLabel, ORIGIN_LABELS, originLabel } from './annotations'

/**
 * 第 63 期 6/6：批注的**展示口径**。
 *
 * 这个模块存在的唯一理由是「章节」这一栏曾经被两个调用方各写了一遍
 * `第 {{ chapter + 1 }} 章`，而设备（KOReader）回传的批注**只有章节标题、没有序号**，
 * 后端把序号记成 `-1`。照 `+1` 渲染出来的是「第 1 章」——一条明明来自第十二章的批注，
 * 界面上写着第一章，而且**看不出这是猜的**（既不报错也不空着）。
 *
 * 所以用例的重心不在「正常那条」，在**序号未知的那两条**：
 * 有标题就显示标题，连标题都没有就什么都不显示 —— 但绝不显示「第 1 章」。
 */

describe('chapterLabel', () => {
  it('序号已知：后端存 0 基，界面显示 1 基', () => {
    expect(chapterLabel({ chapter: 0 })).toBe('第 1 章')
    expect(chapterLabel({ chapter: 11 })).toBe('第 12 章')
  })

  it('第 0 章是合法章节，不是「没有章节」', () => {
    // `-1` 才是「未知」的哨兵值（见 `db.add_annotation` 的注释）。把 0 也当成未知
    // 会让全书第一章的批注集体丢失章节显示 —— 而封面那一章恰恰是批注最多的地方。
    expect(chapterLabel({ chapter: 0 })).not.toBe('')
  })

  it('序号未知（-1）+ 有标题 ⇒ 显示设备给的标题，不编号', () => {
    expect(chapterLabel({ chapter: -1, chapter_title: '第十二章 夜航' })).toBe('第十二章 夜航')
  })

  it('序号未知 + 没标题 ⇒ 空串，让调用方整段不渲染', () => {
    expect(chapterLabel({ chapter: -1 })).toBe('')
    expect(chapterLabel({ chapter: -1, chapter_title: '' })).toBe('')
  })

  it('标题只有空白 ⇒ 也当没有（否则会渲染出一段看得见的空白）', () => {
    expect(chapterLabel({ chapter: -1, chapter_title: '   ' })).toBe('')
  })

  it('序号已知时**优先**用序号，忽略标题', () => {
    // 两者同时存在是可能的：本应用读了设备导入的批注、又给它补上了序号。
    // 序号是机器算出来的、能拿去跳章；标题是人写的、跳不了。
    expect(chapterLabel({ chapter: 3, chapter_title: '随便什么' })).toBe('第 4 章')
  })

  it('**绝不为未知序号编出一个章号**（这个模块存在的理由）', () => {
    // 三种「未知」的形态都不能变成「第 1 章」。写成 `chapter + 1` 的实现会全挂在这条上。
    for (const a of [
      { chapter: -1 },
      { chapter: -1, chapter_title: '' },
      { chapter: -1, chapter_title: '   ' },
    ]) {
      expect(chapterLabel(a)).not.toBe('第 1 章')
      expect(chapterLabel(a)).not.toContain('第')
    }
  })
})

describe('canJumpTo', () => {
  it('序号已知才可跳 —— 第 0 章算已知', () => {
    expect(canJumpTo({ chapter: 0 })).toBe(true)
    expect(canJumpTo({ chapter: 7 })).toBe(true)
  })

  it('序号未知不可跳', () => {
    // 阅读器只认 `?chapter=<序号>`。拿 -1 去跳会落到章首，用户以为「点进去就到那条批注」，
    // 实际到的是第一章开头 —— 界面上还看不出错了。宁可不算链接。
    expect(canJumpTo({ chapter: -1 })).toBe(false)
  })
})

describe('originLabel', () => {
  it('三个已知来源有中文名', () => {
    expect(originLabel('web')).toBe('本应用阅读器')
    expect(originLabel('koreader')).toBe('KOReader')
    expect(originLabel('kobo')).toBe('Kobo')
  })

  it('未知来源原样返回，不编一个「其他」把它盖掉', () => {
    // 来源是后端的数据，出现没见过的值说明有我们不知道的写入方；
    // 盖成「其他」等于把这条线索藏起来。
    expect(originLabel('calibre')).toBe('calibre')
  })

  it('空 / 缺省 ⇒ 空串（调用方自己决定怎么显示）', () => {
    expect(originLabel('')).toBe('')
    expect(originLabel(undefined)).toBe('')
  })

  it('ORIGIN_LABELS 与后端 origin 枚举对得上', () => {
    // 后端 `db.py` 建表注释里预留的枚举是 web / koreader / kobo 三个。
    // 这里多一个（比如给未接入的 Kobo 之外的来源）会渲染成一个界面上没有的组。
    expect(Object.keys(ORIGIN_LABELS).sort()).toEqual(['kobo', 'koreader', 'web'])
  })
})

describe('调用方不许绕过这个模块自己拼章节号', () => {
  /**
   * `src/` 下全部 `.vue` / `.ts` 的**原文**，键是相对本文件的路径。
   *
   * 用 Vite 的 `import.meta.glob` 而不是 `node:fs`：这个包的 tsconfig 只带了
   * `vite/client` 的 types（没有 `node`），把 `node` 加进去会让**应用代码**也
   * 能用 Node API —— 那是跑在浏览器里的代码，编译期就该拦住。glob 由 Vite 自己做
   * 静态分析，不碰文件系统 API。
   */
  const SOURCES = import.meta.glob('../**/*.{vue,ts}', {
    query: '?raw',
    import: 'default',
    eager: true,
  }) as Record<string, string>

  it('没有任何 .vue/.ts 还在渲染 `chapter + 1`', () => {
    // 这条是**回归锁**：这个模块只能提供口径，挡不住别人再手写一遍。
    // 真出过一次 —— 批注总览页与详情页的批注 tab 各写了一遍，加字段时只改了一处。
    //
    // 跳过 `./annotations.ts` 自己：`chapter + 1` 就在它的正经实现里，
    // 而且它的文件头注释**引用了那行出过事的写法**（引文也是 `{{ chapter + 1 }}`，
    // 正则分不出注释和代码）。这一份就是口径本身，不是绕过它的地方。
    const offenders = Object.entries(SOURCES)
      .filter(([p]) => p !== './annotations.ts' && !p.endsWith('.spec.ts'))
      // 只看模板里的插值写法；`+ 1` 本身在别处（分页、序号换算）是正常的
      .filter(([, src]) => /\{\{[^}]*\bchapter\s*\+\s*1\b/.test(src))
      .map(([p]) => p)
      .sort()
    expect(offenders).toEqual([])
  })

  it('glob 真的扫到了源码（空集合上跑断言永远是绿的）', () => {
    // 上面那条的判据力全押在「SOURCES 里确实有文件」上。glob 的路径写错、
    // 或者 `?raw` 选项在这个 Vite 版本上不生效，都会让 SOURCES 变成 `{}` ——
    // 于是遍历零个文件、断言恒真，一条永远绿的空转测试。
    const files = Object.keys(SOURCES)
    expect(files.length).toBeGreaterThan(50)
    expect(files).toContain('../views/AnnotationsView.vue')
    expect(SOURCES['../views/AnnotationsView.vue']).toContain('<template>')
  })
})
