import { describe, expect, it } from 'vitest'

import {
  HASH_BUCKET,
  UNKNOWN_BUCKET,
  bucketKeyOf,
  bucketKeyOfSort,
  buildBuckets,
  yearBucketKeyOf,
} from './shelfBuckets'

/**
 * 第 43 期：书架首字母分桶判据（跳转条的唯一真值源）。
 *
 * 钉住三条：拉丁字母大小写归并、非拉丁字符统一归 `#`、桶序 A–Z 升序且 `#` 垫底。
 *
 * 第 156 期起跳转条**跟随排序维度**（书名 / 作者 / 系列 / 年份），这里同时钉住
 * 「桶键必须与排序字段同一套提取」—— 否则按作者排序却按书名分桶，跳过去永远是错的桶。
 */
describe('shelfBuckets', () => {
  it('拉丁字母按首字分桶，大小写归并', () => {
    expect(bucketKeyOf('Dune')).toBe('D')
    expect(bucketKeyOf('dune')).toBe('D')
    expect(bucketKeyOf('  Apple')).toBe('A')
  })

  it('非拉丁字符、数字与空值统一归 #', () => {
    expect(bucketKeyOf('三体')).toBe(HASH_BUCKET)
    expect(bucketKeyOf('1984')).toBe(HASH_BUCKET)
    expect(bucketKeyOf('')).toBe(HASH_BUCKET)
    expect(bucketKeyOf(undefined)).toBe(HASH_BUCKET)
  })

  it('桶序 A–Z 升序、# 垫底，且统计本数', () => {
    const buckets = buildBuckets(['Dune', '三体', 'Apple', 'Dune'])
    expect(buckets.map((b) => b.key)).toEqual(['A', 'D', HASH_BUCKET])
    expect(buckets.find((b) => b.key === 'D')?.count).toBe(2)
    expect(buckets.find((b) => b.key === HASH_BUCKET)?.count).toBe(1)
  })

  it('undefined 条目跳过、不计入', () => {
    expect(buildBuckets([undefined, 'Apple']).map((b) => b.key)).toEqual(['A'])
  })

  it('入库时间按年份分桶，无日期归「未知」并垫底', () => {
    const ts = (y: number, m = 0, d = 1) => Math.floor(new Date(y, m, d).getTime() / 1000)
    expect(yearBucketKeyOf(ts(2026))).toBe('2026')
    expect(yearBucketKeyOf(ts(2019, 5, 20))).toBe('2019')
    expect(yearBucketKeyOf(undefined)).toBe(UNKNOWN_BUCKET)
    expect(yearBucketKeyOf(0)).toBe(UNKNOWN_BUCKET)
    const buckets = buildBuckets(
      [ts(2019), 0, ts(2026), ts(2026)],
      (v) => yearBucketKeyOf(v),
      UNKNOWN_BUCKET,
    )
    expect(buckets.map((b) => b.key)).toEqual(['2019', '2026', UNKNOWN_BUCKET])
    expect(buckets.find((b) => b.key === '2026')?.count).toBe(2)
    expect(buckets.find((b) => b.key === UNKNOWN_BUCKET)?.count).toBe(1)
  })

  it('桶键跟随排序维度（作者 / 系列 / 入库时间 / 书名）', () => {
    const book = { author: '阿西莫夫', series: '基地', added_at: 1_700_000_000, mtime: 1 }
    expect(bucketKeyOfSort('title', 'Dune', book)).toBe('D')
    expect(bucketKeyOfSort('author', 'Dune', book)).toBe(HASH_BUCKET)
    expect(bucketKeyOfSort('series', 'Dune', { series: '' })).toBe(HASH_BUCKET)
    expect(bucketKeyOfSort('added', 'Dune', book)).toBe('2023')
    // added_at 优先；没有覆盖值时退回文件 mtime（与「入库日期」那一列同口径）
    expect(bucketKeyOfSort('added', 'Dune', { mtime: 1_600_000_000 })).toBe('2020')
  })
})
