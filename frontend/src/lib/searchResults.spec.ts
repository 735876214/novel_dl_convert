import { describe, expect, it } from 'vitest'

import type { SearchHit, SearchSourceState } from '@/lib/api'
import {
  appendHits,
  groupHits,
  mergeSourceStates,
  keepLoadingMore,
  normalizeAuthor,
  normalizeTitle,
  rankGroups,
  sourcesOf,
  splitSources,
} from '@/lib/searchResults'

/** 造一条命中（字段名与后端 `_mark()` 产出的一致） */
function hit(source: string, title: string, author = '', url = ''): SearchHit {
  return { source, title, author, url: url || `${source}://${title}` }
}

function src(name: string, patch: Partial<SearchSourceState> = {}): SearchSourceState {
  return {
    name, display_name: name, ok: true, count: 1, error: '', skipped: false, reason: '',
    has_more: false, ...patch,
  }
}

describe('searchResults · normalizeTitle（书名归一化）', () => {
  it('去书名号与首尾标点', () => {
    expect(normalizeTitle('《三体》')).toBe('三体')
    expect(normalizeTitle('三体！')).toBe('三体')
    expect(normalizeTitle('「诡秘之主」')).toBe('诡秘之主')
  })

  it('全角字母数字归一（NFKC），而不是自己列一张表', () => {
    expect(normalizeTitle('Ｔｈｅ Ｈｏｂｂｉｔ')).toBe('thehobbit')
    expect(normalizeTitle('１９８４')).toBe('1984')
  })

  it('空白与分隔符一律去掉（「三体 全集」与「三体全集」等价）', () => {
    expect(normalizeTitle('三体 全集')).toBe('三体全集')
    expect(normalizeTitle('三体·全集')).toBe('三体全集')
    expect(normalizeTitle('三体（一）')).toBe('三体一')
  })

  it('不猜副标题 / 卷次：只去符号，不做「去括号后面那一截」', () => {
    // 这两条归一化后**不相等**正是要的效果 —— 它们可能是两本书的两卷
    expect(normalizeTitle('三体')).not.toBe(normalizeTitle('三体 2'))
    expect(normalizeTitle('三体')).not.toBe(normalizeTitle('三体（全集）'))
  })

  it('空值不抛错', () => {
    expect(normalizeTitle('')).toBe('')
    expect(normalizeTitle('   ')).toBe('')
  })
})

describe('searchResults · normalizeAuthor（作者归一化）', () => {
  it('取第一个作者', () => {
    expect(normalizeAuthor('刘慈欣、某人')).toBe('刘慈欣')
    expect(normalizeAuthor('Liu Cixin; Someone')).toBe('liucixin')
  })

  it('占位作者一律归为「不知道」（空串）——否则会被错并成同一本书', () => {
    for (const s of ['未知', '佚名', 'UNKNOWN', 'N/A', '—', '']) {
      expect(normalizeAuthor(s), s).toBe('')
    }
  })
})

describe('searchResults · groupHits（同名合并）', () => {
  it('同名同作者跨源合并成一条，组内保持后端顺序', () => {
    const groups = groupHits([
      hit('gutenberg', '《三体》', '刘慈欣'),
      hit('other', '三体', '刘慈欣'),
    ])

    expect(groups).toHaveLength(1)
    expect(groups[0].title).toBe('《三体》')          // 展示用原文取第一条
    expect(groups[0].hits.map((h) => h.source)).toEqual(['gutenberg', 'other'])
    expect(sourcesOf(groups[0])).toEqual(['gutenberg', 'other'])
  })

  it('同名不同作者**不合并**（中文重名书名很多）', () => {
    const groups = groupHits([hit('a', '三体', '刘慈欣'), hit('b', '三体', '另一个人')])
    expect(groups).toHaveLength(2)
  })

  it('一方作者未知**不合并**（无从判断，宁可不并）', () => {
    const groups = groupHits([hit('a', '三体', '刘慈欣'), hit('b', '三体', '未知')])
    expect(groups).toHaveLength(2)
  })

  it('双方作者都是占位作者也**不合并**（最容易错并的一条）', () => {
    const groups = groupHits([hit('a', '三体', '未知'), hit('b', '三体', '未知')])
    expect(groups).toHaveLength(2)
  })

  it('同一个源给出多条时，来源数按去重算（说「1 个来源 / 2 条命中」才是实话）', () => {
    const groups = groupHits([
      hit('same', '三体', '刘慈欣', 'u1'),
      hit('same', '三体', '刘慈欣', 'u2'),
    ])

    expect(groups).toHaveLength(1)
    expect(groups[0].hits).toHaveLength(2)
    expect(sourcesOf(groups[0])).toEqual(['same'])
  })

  it('空结果与无书名条目各自成组，不互相牵连', () => {
    expect(groupHits([])).toEqual([])
    expect(groupHits([hit('a', '', ''), hit('b', '', '')])).toHaveLength(2)
  })
})

describe('searchResults · rankGroups（匹配度排序）', () => {
  it('书名完全相同 > 前缀/包含 > 其它', () => {
    const groups = groupHits([
      hit('a', '三体前传：球状闪电', '刘慈欣'),
      hit('b', '三体', '刘慈欣'),
      hit('c', '三体全集', '刘慈欣'),
    ])

    expect(rankGroups(groups, '三体').map((g) => g.title))
      .toEqual(['三体', '三体前传：球状闪电', '三体全集'])
  })

  it('同档内有作者的排前面', () => {
    const groups = groupHits([hit('a', '三体', '未知'), hit('b', '三体', '刘慈欣')])

    expect(rankGroups(groups, '别的关键词').map((g) => g.author)).toEqual(['刘慈欣', '未知'])
  })

  it('关键词为空时保持原顺序（不做「未命中」的伪排序）', () => {
    const groups = groupHits([hit('a', '甲'), hit('b', '乙')])
    expect(rankGroups(groups, '').map((g) => g.title)).toEqual(['甲', '乙'])
  })

  it('不就地改入参数组（分页追加后要重排，不能有一份被悄悄改写的旧顺序）', () => {
    const groups = groupHits([hit('a', '别的'), hit('b', '三体')])
    const before = groups.map((g) => g.title)

    rankGroups(groups, '三体')

    expect(groups.map((g) => g.title)).toEqual(before)
  })
})

describe('searchResults · appendHits（分页追加）', () => {
  it('追加不覆盖，且同源同地址不重复计入', () => {
    const first = [hit('a', 'T1', 'A', 'u1')]
    const { hits, added } = appendHits(first, [hit('a', 'T1', 'A', 'u1'), hit('a', 'T2', 'A', 'u2')])

    expect(added).toBe(1)
    expect(hits.map((h) => h.url)).toEqual(['u1', 'u2'])
  })

  it('不同源的同名书**不去重**（那正是要合并展示的对象）', () => {
    const { added } = appendHits([hit('a', '三体', '刘慈欣', 'u1')], [hit('b', '三体', '刘慈欣', 'u1')])
    expect(added).toBe(1)
  })
})

describe('searchResults · keepLoadingMore（按钮该不该留着）', () => {
  it('后端说没有了 ⇒ 收起', () => {
    expect(keepLoadingMore(false, 5)).toBe(false)
  })

  it('后端说可能有、但这一页什么都没新增 ⇒ 收起（站点回吐同一页时不让按钮白点）', () => {
    expect(keepLoadingMore(true, 0)).toBe(false)
  })

  it('还有下一页且真取到了新内容 ⇒ 留着', () => {
    expect(keepLoadingMore(true, 3)).toBe(true)
  })
})

describe('searchResults · splitSources（逐源状态三态）', () => {
  it('成功 / 失败 / 被跳过 各归各类，顺序保持', () => {
    const r = splitSources([
      src('a', { count: 2 }),
      src('b', { ok: false, error: '连接失败' }),
      src('c', { ok: false, skipped: true, reason: '下载功能未开启' }),
      src('d', { ok: true, count: 0 }),
    ])

    expect(r.ok.map((s) => s.name)).toEqual(['a', 'd'])
    expect(r.failed.map((s) => s.name)).toEqual(['b'])
    expect(r.skipped.map((s) => s.name)).toEqual(['c'])
  })

  it('没有结果的成功源仍算成功（0 条 ≠ 失败，不该报错给用户）', () => {
    const r = splitSources([src('a', { ok: true, count: 0 })])
    expect(r.failed).toEqual([])
    expect(r.ok.map((s) => s.name)).toEqual(['a'])
  })
})

describe('searchResults · mergeSourceStates（逐源状态跨页合并）', () => {
  it('计数累加（翻页后「成功 N 条」不该反而变小）', () => {
    const merged = mergeSourceStates(
      [src('a', { count: 3 })],
      [src('a', { count: 2 })],
    )

    expect(merged[0].count).toBe(5)
  })

  it('失败原因 / has_more 以新页为准', () => {
    const merged = mergeSourceStates(
      [src('a', { ok: false, error: '上一次超时', has_more: true })],
      [src('a', { ok: true, count: 1, error: '', has_more: false })],
    )

    expect(merged[0].ok).toBe(true)
    expect(merged[0].error).toBe('')
    expect(merged[0].has_more).toBe(false)
  })

  it('上一页有、这一页没回来的源留着（别让失败原因凭空消失）', () => {
    const merged = mergeSourceStates(
      [src('a'), src('gone', { ok: false, error: '连接失败' })],
      [src('a')],
    )

    expect(merged.map((s) => s.name)).toEqual(['a', 'gone'])
    expect(merged[1].error).toBe('连接失败')
  })
})
