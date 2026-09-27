import type { BookMetadataFields } from '@/lib/api'

/**
 * 元数据字段的**中文名与呈现顺序** —— 单一来源。
 *
 * 抽出来的原因：同一份清单原先在四个地方各抄了一遍（编辑器、抓取预览抽屉、
 * 设置页的逐字段策略表、Book Dock 的预设写回），并且**已经抄出过一次事故**：
 * Book Dock 那份写的是 `year`，而引擎按字段名 `date` 查策略 —— 预设里「出版年」
 * 那一档静默失效了若干个期，没有任何报错。同一个字段名在这四处各有归属，
 * 分开写必然走样（与 `lib/bookInfo.ts` 抽出来的同一条理由）。
 *
 * ⚠️ 键必须是**后端字段名**（`fileops.METADATA_FIELDS` 那一套）：
 * 出版年是 `date`（OPF 的 `dc:date`），`year` 是**书卡片**上的名字。
 * 两者的区别在后端 `metafetch._CURRENT` 的注释里也专门写过一遍。
 */
export const FIELD_LABELS: Record<keyof BookMetadataFields, string> = {
  title: '书名',
  author: '作者',
  series: '系列',
  series_index: '系列序号',
  date: '出版年',
  publisher: '出版社',
  language: '语言',
  description: '简介',
  isbn: 'ISBN',
  tags: '题材',
  narrators: '演播者',
  subtitle: '副标题',
  google_books_id: 'Google Books ID',
  goodreads_id: 'Goodreads ID',
  amazon_id: 'Amazon ASIN',
  hardcover_id: 'Hardcover ID',
  openlibrary_id: 'Open Library ID',
  itunes_id: 'iTunes ID',
  kobo_id: 'Kobo ID',
  aladin_id: 'Aladin ID',
  audible_id: 'Audible ASIN',
}

/**
 * 提供商 ID 的字段名（顺序即展示顺序）。
 *
 * 只有**真能拿到该源标识**的 9 家在这里。另外 4 家（comicvine / ranobedb /
 * librofm / lubimyczytac）不是漏了：它们抓到的只是一个页面 URL，后端没有给它们开字段。
 */
export const PROVIDER_ID_FIELDS = [
  'google_books_id',
  'goodreads_id',
  'amazon_id',
  'hardcover_id',
  'openlibrary_id',
  'itunes_id',
  'kobo_id',
  'aladin_id',
  'audible_id',
] as const satisfies readonly (keyof BookMetadataFields)[]

/**
 * 编辑器的文本框字段（不含 `tags` / `narrators` —— 那两项是多值，各有一块 UI）。
 *
 * 顺序 / 分组对齐上游 Book Orbit 的编辑器：IDENTITY（书名…语言）与
 * CATALOG（ISBN 与提供商 ID）分成两段，中间插 `subtitle`（上游也把它放在 IDENTITY 段）。
 */
export const IDENTITY_FIELDS: (keyof BookMetadataFields)[] = [
  'title', 'subtitle', 'author', 'series', 'series_index',
  'date', 'publisher', 'language',
]

/** CATALOG 段：ISBN + 9 个提供商 ID（上游同款分段） */
export const CATALOG_FIELDS: (keyof BookMetadataFields)[] = ['isbn', ...PROVIDER_ID_FIELDS]

/**
 * **没有 OPF 对应物**的字段：后端 `fileops.patch_opf_meta` 只认它那串 if/elif 里的
 * 字段，这里的几个**写得进数据库、写不进 OPF**。
 *
 * 为什么要在前端也标一份：编辑器对「已覆盖但无在线值」的字段会说一句
 * 「恢复后将回到文件原值 / 恢复后该字段为空」—— 选哪一句取决于**这个字段有没有
 * OPF 那一层**，不是取决于格式。早先按「是不是 EPUB」判，在 EPUB 上给每个字段
 * 都说「回到文件原值」：这对 `narrators`（第 53 期）就已经是假话，
 * 对第 63 期的副标题与 9 个提供商 ID 更是 —— 文件里根本没有对应元素。
 */
export const DB_ONLY_FIELDS: ReadonlySet<string> = new Set<string>([
  // 第 53 期：经 meta_override 落库、绝不写回文件
  'narrators',
  // 第 63 期：同一种待遇
  'subtitle',
  ...PROVIDER_ID_FIELDS,
])

/**
 * `metadata_fetch.fields` 逐字段写入策略的键。
 *
 * ⚠️ 与 `metafetch._FINALIZE_FIELDS` / `config.DEFAULTS.metadata_fetch.fields`
 * **必须同集合**（后端有测试钉住那两者；这里靠下面那条开发期断言兜住本文件）。
 * 与上面的编辑字段只差一项：多了封面（它不在 `fields` 字典里，锁用独立键）。
 */
export const POLICY_FIELDS: (keyof BookMetadataFields | 'cover')[] = [
  'title', 'author', 'publisher', 'date', 'language', 'isbn',
  'description', 'tags', 'cover', 'subtitle', ...PROVIDER_ID_FIELDS,
]

/** 策略键的中文名（`cover` 不在 `FIELD_LABELS` 里，单独补） */
export function policyLabel(k: string): string {
  if (k === 'cover') return '封面'
  return FIELD_LABELS[k as keyof BookMetadataFields] ?? k
}
