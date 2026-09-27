import { describe, expect, it } from 'vitest'

import { api } from '@/lib/api'

/**
 * 成品文件下载地址（第 64 期修的两处，都在这里钉住）。
 *
 * 为什么值得单独一个 spec：这个函数是**纯字符串**，错了不会有任何异常 ——
 * 页面照常渲染、链接照常可点，只是点下去 404 或者下到一个别的文件。三条静默失效：
 *
 * 1. **整串编码**（`encodeURIComponent(name)`）会把库内相对路径里的 `/` 变成 `%2F`，
 *    能不能还原就取决于中间层怎么解 URL —— 按段编码不依赖那件事；
 * 2. **`#` 不编码**：浏览器把它之后当片段，请求发到的是**另一个路径**
 *    （Komga 布局的名字里带 `#` 很常见，形如 `三体 #1.epub`）；
 * 3. **漏传 `library_id`**：服务端基根退回 `OUTPUT_DIR`，库根不是它的书一律解析不到。
 */
describe('api.downloadUrl', () => {
  it('单段文件名：一段编码，不带查询串', () => {
    expect(api.downloadUrl('三体.epub')).toBe('/download/%E4%B8%89%E4%BD%93.epub')
    // 基根是 /download/ 而不是 /api/download/（旧接口不在 /api 前缀下，也就不强制鉴权）
    expect(api.downloadUrl('三体.epub').startsWith('/download/')).toBe(true)
  })

  it('库内相对路径按段编码：斜杠保持斜杠', () => {
    const url = api.downloadUrl('三体/三体-1.epub')
    expect(url).toBe('/download/%E4%B8%89%E4%BD%93/%E4%B8%89%E4%BD%93-1.epub')
    expect(url).not.toContain('%2F')
  })

  it('片段号与空格都要编码（不编码就会被浏览器当成锚点，请求发到别处）', () => {
    const url = api.downloadUrl('三体/三体 #1.epub')
    expect(url).toContain('%23')
    expect(url).toContain('%20')
    expect(url).not.toContain('#')
    expect(url.split('/').slice(0, 3)).toEqual(['', 'download', '%E4%B8%89%E4%BD%93'])
  })

  it('libraryId 进查询串并自身编码；不传就不出现这个参数', () => {
    expect(api.downloadUrl('三体.epub', 'lib-b')).toBe(
      '/download/%E4%B8%89%E4%BD%93.epub?library_id=lib-b',
    )
    // 空字符串 = 「不带库维度」的既有语义（服务端基根退回 OUTPUT_DIR 的行为不变）
    expect(api.downloadUrl('三体.epub', '')).not.toContain('library_id')
  })
})
