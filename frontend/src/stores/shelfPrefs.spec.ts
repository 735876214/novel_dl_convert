import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { normalizePayload, SHELF_SYNC_DEFAULT } from '@/lib/prefsPayload'
import { SHELF_PREFS_DEFAULT, SHELF_PREFS_REV, useShelfPrefsStore } from '@/stores/shelfPrefs'

/**
 * 书架偏好的**口径版本**（第 152 期）—— 这一族坏起来全是静默的。
 *
 * 第 152 期把「系列默认折叠」的默认值由 `false` 翻成 `true`（`SHELF_PREFS_REV` 1 → 2）。
 * 只改默认值不够：`save()` 在任何字段变动时都整份落盘，所以「用户从没碰过那个开关」
 * 与「用户明确关掉了折叠」在存档里长得一模一样（都是 `collapseSeries:false`）。
 * 版本号是唯一能区分两者的信息 —— 少了它，老存档会永远压着新默认值，
 * 表现是「漫画库照旧一册一张卡」，**不报错、界面上也看不出哪里不对**。
 *
 * 两个落点都要钉：
 *   ① 本机存档（`shelfPrefs.read()`）；
 *   ② 服务端设备记录（`prefsPayload.normalizeShelf` 经 `normalizePayload`）。
 * 少钉 ② 的后果更隐蔽：本机好了，但换台设备 / 清了缓存回来，那枚 `false` 又从
 * 服务端被拉回来盖掉默认值。
 */

const KEY = 'nf-shelf-prefs'

/** 第 152 期之前的存档长这样：没有 `rev`，`collapseSeries` 是旧默认值 `false` */
const OLD_ARCHIVE = {
  view: 'table',
  sort: 'title',
  dir: 'asc',
  collapseSeries: false,
  thumbnailClick: 'reader',
  filtersOpenByDefault: true,
}

describe('shelfPrefs：默认值与口径版本', () => {
  // `read()` 只在 store 首次实例化时跑 ⇒ 每个用例换一份新 pinia，才会真的重读存档
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
  })

  it('全新设备：默认**折叠**系列（第 152 期翻盘）', () => {
    expect(SHELF_PREFS_DEFAULT.collapseSeries).toBe(true)
    expect(useShelfPrefsStore().prefs.collapseSeries).toBe(true)
  })

  it('旧存档里的 collapseSeries:false **作废**，取新默认值', () => {
    localStorage.setItem(KEY, JSON.stringify(OLD_ARCHIVE))
    const prefs = useShelfPrefsStore().prefs
    expect(prefs.collapseSeries).toBe(true)
    expect(prefs.rev).toBe(SHELF_PREFS_REV)
  })

  it('旧存档的其余字段照旧沿用（视图 / 排序 / 缩略图点击 / 筛选默认展开）', () => {
    localStorage.setItem(KEY, JSON.stringify(OLD_ARCHIVE))
    const prefs = useShelfPrefsStore().prefs
    expect(prefs.view).toBe('table')
    expect(prefs.sort).toBe('title')
    expect(prefs.dir).toBe('asc')
    expect(prefs.thumbnailClick).toBe('reader')
    expect(prefs.filtersOpenByDefault).toBe(true)
  })

  it('**当前版本**存档里的 false 是用户的真实选择，必须尊重', () => {
    localStorage.setItem(KEY, JSON.stringify({ ...OLD_ARCHIVE, rev: SHELF_PREFS_REV }))
    expect(useShelfPrefsStore().prefs.collapseSeries).toBe(false)
  })

  it('用户关掉折叠后再读，不会被版本逻辑改回来（落盘带着新 rev）', () => {
    useShelfPrefsStore().patch({ collapseSeries: false })
    expect(JSON.parse(localStorage.getItem(KEY) as string).rev).toBe(SHELF_PREFS_REV)
    // 换一份 pinia = 重新走一遍 `read()`（同一份 pinia 会命中缓存，验不出落盘值）
    setActivePinia(createPinia())
    expect(useShelfPrefsStore().prefs.collapseSeries).toBe(false)
  })

  it('坏存档不抛错，退回默认值', () => {
    localStorage.setItem(KEY, '{not json')
    expect(useShelfPrefsStore().prefs.collapseSeries).toBe(true)
  })
})

describe('prefsPayload：服务端设备记录里的旧口径同样作废', () => {
  it('同步块默认值 = 书架偏好默认值（同一个真值源）', () => {
    expect(SHELF_SYNC_DEFAULT.collapseSeries).toBe(SHELF_PREFS_DEFAULT.collapseSeries)
    expect(SHELF_SYNC_DEFAULT.rev).toBe(SHELF_PREFS_REV)
  })

  it('第 152 期之前推上来的 shelf 块（无 rev）⇒ collapseSeries 作废', () => {
    const p = normalizePayload({ shelf: { collapseSeries: false } as never })
    expect(p.shelf.collapseSeries).toBe(true)
    expect(p.shelf.rev).toBe(SHELF_PREFS_REV)
  })

  it('版本不符的 shelf 块同样作废（别用「旧 rev 也算」的宽容换静默错值）', () => {
    const p = normalizePayload({ shelf: { collapseSeries: false, rev: SHELF_PREFS_REV - 1 } })
    expect(p.shelf.collapseSeries).toBe(true)
  })

  it('当前版本的 shelf 块原样采纳（换设备能带过来）', () => {
    const p = normalizePayload({ shelf: { collapseSeries: false, rev: SHELF_PREFS_REV } })
    expect(p.shelf.collapseSeries).toBe(false)
  })

  it('归一化是幂等的：同一份载荷比较结果稳定（dirty 判定依赖这一点）', () => {
    const once = normalizePayload({ shelf: { collapseSeries: false } as never })
    const twice = normalizePayload(once)
    expect(twice.shelf).toEqual(once.shelf)
  })
})
