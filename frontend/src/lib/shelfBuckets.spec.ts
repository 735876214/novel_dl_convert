import { describe, expect, it } from 'vitest'

import { HASH_BUCKET, bucketKeyOf, buildBuckets } from './shelfBuckets'

/**
 * 第 43 期：书架首字母分桶判据（跳转条的唯一真值源）。
 *
 * 钉住三条：拉丁字母大小写归并、非拉丁字符统一归 `#`、桶序 A–Z 升序且 `#` 垫底。
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
})
