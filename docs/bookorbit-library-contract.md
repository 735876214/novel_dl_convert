# BookOrbit 书库结构参考契约（移植四工具用）

> 来源：`https://github.com/bookorbit/bookorbit` ，类型定义集中在 `@bookorbit/types` 包（`packages/types/src/`）。
> 用途：本文件是 **novel_dl_convert 移植四工具（book-duplicates / bulk-rename / entity-manager / missing-resources）** 时，前端 `lib/api.ts`、后端 `core/*` 与上游数据模型的对齐基准。
> 领域映射约定（已拍板）：
> - 「书 book」→ 转换后的小说 epub（`OUTPUT_DIR` 成品文件）+ 元数据（标题/作者/系列）
> - 「实体 entity」→ 作者 / 系列（EPUB 元数据 + 文件名解析）
> - 「重复 duplicate」→ 归一化书名+作者分组或内容哈希重复
> - 「批量重命名 bulk-rename」→ 按规则批量重命名 `OUTPUT_DIR` 内的 epub 文件
> - 「缺失资源 missing-resources」→ 零字节 / 无法解析 / 缺封面

---

## 1. Library 书库（`library.ts`）

```ts
export type OrganizationMode = "book_per_file" | "book_per_folder";
export type CoverAspectRatio = "2/3" | "1/1";
export type AddedAtSource = "imported" | "file_modified" | "file_created";
export type AccessLevel = "viewer" | "editor" | "owner";

export interface LibraryFolder { id: number; path: string; createdAt: string; }

export interface Library {
  id: number;
  name: string;
  icon?: string | null;
  displayOrder: number;
  coverAspectRatio: CoverAspectRatio;
  watch: boolean;
  autoScanCronExpression?: string | null;
  metadataPrecedence: string[];
  formatPriority: string[];
  allowedFormats: string[];
  organizationMode: OrganizationMode;
  addedAtSource: AddedAtSource;
  excludePatterns: string[];
  readingThreshold: number;
  markAsFinishedPercentComplete: number;
  fileNamingPattern?: string | null;   // ← bulk-rename 的核心规则来源
  fileWriteEnabled: boolean;
  fileWriteWriteCover: boolean;
  fileWriteEpubEnabled: boolean;
  fileWriteEpubMaxFileSizeMb: number;
  fileWriteFb2Enabled: boolean;
  fileWriteFb2MaxFileSizeMb: number;
  fileWritePdfEnabled: boolean;
  fileWritePdfMaxFileSizeMb: number;
  fileWriteCbxEnabled: boolean;
  fileWriteCbxMaxFileSizeMb: number;
  fileWriteKindleEnabled: boolean;
  fileWriteKindleMaxFileSizeMb: number;
  fileWriteAudioEnabled: boolean;
  fileWriteAudioMaxFileSizeMb: number;
  fileRenameEnabled: boolean;          // ← bulk-rename 开关
  folders: LibraryFolder[];            // ← 真正的物理路径在这里，没有单一 rootDir
  bookCount?: number;
  createdAt: string;
  updatedAt: string;
}
```

> 注意：上游没有 `path` / `rootDir` / `coverDir` 单字段。物理路径在 `folders[]`，封面只存宽高比。本项目已把「书库」映射为 `OUTPUT_DIR` 成品目录，对应得上。

---

## 2. Book 书（`book.ts`）—— 查重 / 重命名 / 缺失都围绕它

```ts
// 媒体类型
export const AUDIO_FORMAT_LIST = ["m4b","mp3","m4a","opus","ogg","flac"] as const;
export const COMIC_FORMAT_LIST = ["cbz","cbr","cb7","cbx"] as const;
export const EBOOK_FORMAT_LIST = ["epub","kepub","mobi","azw3","azw","fb2","pdf","djvu"] as const;
export const READ_STATUSES = ["unread","want_to_read","reading","on_hold","rereading","read","skimmed","abandoned"] as const;
export type ReadStatus = (typeof READ_STATUSES)[number];

// 文件引用
export type BookFileRef = { id: number; format: string | null; role: string; sizeBytes: number | null; };

// 列表卡片视图
export type BookCard = {
  id: number;
  status: string;
  coverAspectRatio: CoverAspectRatio;
  title: string | null;
  authors: string[];
  seriesId?: number | null;
  seriesName: string | null;
  seriesIndex: SeriesIndex | null;
  seriesMemberships?: BookSeriesMembership[];
  files: BookFileRef[];
  publishedDate: string | null;
  publishedYear: number | null;
  language: string | null;
  genres: string[];
  rating: number | null;
  readingProgress: number | null;
  readStatus: UserBookStatus | null;
  addedAt: string;
  updatedAt: string | null;
  metadataScore: number | null;
  hasCover: boolean;                 // ← 缺失封面判定
  hasMetadataLocks: boolean;
  lockedFields: BookMetadataLockField[];
  subtitle: string | null;
  publisher: string | null;
  pageCount: number | null;
  isbn13: string | null;
  hardcoverId?: string | null;
  narrators: string[];
  tags: string[];
  customMetadata: CustomMetadataBookValue[];
  collapsedSeries?: CollapsedSeriesInfo;
};

// 详情视图
export type BookDetailFile = {
  id: number; format: string | null; role: string; sizeBytes: number | null;
  absolutePath: string; createdAt: string; filename: string | null; durationSeconds: number | null;
};

export type BookDetail = {
  id: number;
  libraryId: number;
  libraryName: string;
  status: string;
  folderPath: string;                // ← bulk-rename 定位文件的依据
  addedAt: string;
  updatedAt: string | null;
  title: string | null;
  subtitle: string | null;
  description: string | null;
  isbn10: string | null;
  isbn13: string | null;
  publisher: string | null;
  publishedDate: string | null;
  publishedYear: number | null;
  language: string | null;
  pageCount: number | null;
  seriesId?: number | null;
  seriesName: string | null;
  seriesIndex: SeriesIndex | null;
  seriesMemberships?: BookSeriesMembership[];
  rating: number | null;
  personalNote: string | null;
  communityRatings: BookCommunityRating[];
  coverSource: "extracted" | "custom" | null;   // ← 缺失封面判定（null = 无封面）
  hardcoverEditionId: string | null;
  providerIds: ProviderIds;
  authors: { id: number; name: string; sortName: string | null }[];
  genres: string[];
  tags: string[];
  files: BookDetailFile[];           // ← absolutePath / filename（重命名对象）
  lastWrittenAt: string | null;
  metadataScore: number | null;
  readStatus: UserBookStatus | null;
  audioMetadata: AudioMetadata | null;
  formatPriority: string[];
  comicMetadata: ComicMetadataFields | null;
  customMetadata: CustomMetadataBookValue[];
  lockedFields: BookMetadataLockField[];
  collections: { id: number; name: string }[];
  fileWriteStatus?: BookFileWriteStatus;
};

export type BooksPage = { items: BookCard[]; total: number; page: number; size: number; };
```

> 关键字段：`hasCover` / `coverSource`（缺失封面）、`files[].absolutePath/filename`（重命名）、`authors[]` + `seriesName`（实体派生）、`folderPath`（定位）。

---

## 3. book-duplicates 查重（`book-duplicates.ts`）

```ts
export const BOOK_DUPLICATE_MATCH_REASONS = ["file_hash","isbn","exact_metadata","fuzzy_metadata"] as const;
export type BookDuplicateMatchReason = (typeof BOOK_DUPLICATE_MATCH_REASONS)[number];

export type CreateBookDuplicateScanRequest = { libraryId?: number; similarityPercent: number; };

export type BookDuplicateScan = {
  id: number;
  status: BookDuplicateScanStatus;
  libraryIds: number[];
  requestedLibraryId: number | null;
  similarityPercent: number;
  processedBooks: number;
  totalBooks: number | null;
  progressPercent: number | null;
  totalGroups: number | null;
  errorCode: string | null;
  createdAt: string;
  completedAt: string | null;
};

export type BookDuplicateGroup = {
  id: number;
  reasons: BookDuplicateMatchReason[];
  maxTitleSimilarity: number | null;
  books: BookDuplicateCandidate[];
  pairs: BookDuplicatePair[];
};

export type BookDuplicateGroupsResponse = { groups: BookDuplicateGroup[]; total: number; page: number; pageSize: number; };

// 同文件还定义（本契约略去字段细节，审计时对照）：
// BookDuplicateScanStatus / BookDuplicateCandidate / BookDuplicatePair / BookDuplicateFile
```

对应 REST（`client/src/features/tools/api/book-duplicates.ts`）：
- `POST   /api/v1/book-duplicates/scans`
- `GET    /api/v1/book-duplicates/scans/{scanId}`
- `GET    /api/v1/book-duplicates/scans/active`
- `GET    /api/v1/book-duplicates/scans/{scanId}/groups?page=&pageSize=&reason=`（reason 可选：`file_hash|isbn|exact_metadata|fuzzy_metadata`）
- `DELETE /api/v1/books`（body `{ bookIds: number[] }`）

---

## 4. entity-manager 实体管理（`entity-manager.ts`）

```ts
export type EntityType = "author" | "genre" | "tag" | "narrator" | "publisher" | "language" | "series";

export interface EntityInfo { id: number | string; name: string; bookCount: number; bookTitles: string[]; }

export interface BrowseEntitiesParams {
  search?: string; page?: number; pageSize?: number;
  sortBy?: BrowseEntitySortBy; sortOrder?: BrowseEntitySortOrder; bookCount?: BrowseEntityBookCountFilter;
}
export interface BrowseEntitiesResponse { items: BrowseEntityItem[]; total: number; page: number; pageSize: number; }

export interface RenameResult {
  entityId: number | string; oldName: string; newName: string;
  affectedBookCount: number; wasImplicitMerge: boolean; mergedEntityId?: number | string;
}
export interface MergeResult {
  targetId: number | string; mergedIds: (number | string)[]; affectedBookCount: number;
  imagePromoted?: boolean; fieldsResolved?: string[];
}
export interface SplitResult { originalId: number; originalName: string; newEntities: { id: number; name: string }[]; affectedBookCount: number; }
export interface DeleteResult { entityId: number | string; name: string; affectedBookCount: number; mode: "soft" | "hard" | "inline"; }
export interface BulkDeleteResult { results: DeleteResult[]; errors: { entityId: number | string; error: string }[]; }

export interface DuplicateScanResponse { entityType: EntityType; clusters: DuplicateCluster[]; totalEntities: number; total: number; page: number; pageSize: number; }
export interface DuplicateScanStatus { entityType: EntityType; state: DuplicateScanState; computedAt: string | null; totalPairs: number | null; threshold: number | null; progressPct: number | null; }
export interface DismissedPairInfo { id: number; entityType: EntityType; nameA: string; nameB: string; idA: number | string; idB: number | string; reason?: string | null; dismissedAt: string; }
```

对应 REST（`entity-manager.ts` api），`BASE = /api/v1/entity-manager`：
- `GET    /{entityType}/browse`
- `GET    /{entityType}/duplicates/scan`
- `POST   /{entityType}/merge`
- `POST   /{entityType}/rename`
- `POST   /{entityType}/delete`（mode: `soft|hard|inline`）
- `POST   /{entityType}/bulk-delete`
- `POST   /{entityType}/split`
- `POST   /{entityType}/duplicates/dismiss` | `undismiss` | `refresh`
- `GET    /{entityType}/duplicates/dismissed` | `status`
- `GET    /{entityType}/info/{entityId}`

> 本项目适配聚焦 **author / series** 两类实体（上游 `EntityType` 子集）。

---

## 5. bulk-rename 批量重命名（依赖 `library.ts` 字段）

上游依赖 `Library.fileNamingPattern` 与 `Library.fileRenameEnabled`，按 `Library` 维度对 `book.files[].filename` 做预览/执行。类型来自 `@bookorbit/types`（未在本次抓取中逐字段展开）：
- `BulkRenameExecuteRequest`（含 `excludeBookIds`；省略则重命名所有候选）
- `BulkRenamePreviewPage`（分页预览：旧名/新名候选）
- `BulkRenameStatus`

对应 REST（`bulk-rename.ts` api），`BASE = /api/v1/libraries/{libraryId}/bulk-rename`：
- `GET  /preview?page=&pageSize=&status=&search=`
- `GET  /status` → `{ running: boolean }`
- `POST /execute`（body `BulkRenameExecuteRequest`；`excludeBookIds` 用于保留部分书不被重命名）

---

## 6. missing-resources 缺失资源（`maintenance.ts`）

```ts
export const MISSING_RESOURCE_CATEGORIES = ["missing_books","broken_covers","orphaned_cover_dirs"] as const;
export type MissingResourceCategory = (typeof MISSING_RESOURCE_CATEGORIES)[number];

export const COVER_SWEEP_STATUSES = ["running","completed","failed"] as const;
export type CoverSweepStatus = (typeof COVER_SWEEP_STATUSES)[number];

export type CoverSweep = {
  status: CoverSweepStatus;
  processedBooks: number;
  totalBooks: number | null;
  progressPercent: number | null;
  brokenCovers: number;
  orphanedCoverDirs: number;
  orphanedBytes: number;
  truncated: boolean;
  errorCode: string | null;
  startedAt: string;
  completedAt: string | null;
};

export type MissingResourcesSummary = { missingBooks: number; sweep: CoverSweep | null; };

export type MissingBookEntry = {
  id: number; title: string | null; authors: string[]; libraryId: number; libraryName: string;
  folderPath: string; formats: string[]; updatedAt: string | null;
};
export type BrokenCoverEntry = {
  id: number; title: string | null; authors: string[]; libraryId: number; libraryName: string;
  coverSource: "extracted" | "custom";
};
export type OrphanedCoverDirEntry = { bookId: number; fileCount: number; sizeBytes: number; };

export type MissingResourcePage<TEntry> = { items: TEntry[]; total: number; page: number; pageSize: number; };
export type MissingResourceCleanupRequest = { bookIds?: number[]; all?: boolean; };
export type MissingResourceCleanupResult = {
  category: MissingResourceCategory; requested: number; cleaned: number;
  skipped: number; remaining: number;
};
```

对应 REST（`missing-resources.ts` api），`BASE = /api/v1/maintenance/missing-resources`：
- `GET  /`（summary） | `GET /sweep` | `POST /sweep`（start）
- `GET  /books?page=&pageSize=` | `GET /broken-covers?...` | `GET /orphaned-covers?...`
- `POST /books/clean` | `POST /broken-covers/clean` | `POST /orphaned-covers/clean`（body `MissingResourceCleanupRequest`）

> 本项目把三类缺失资源映射到：
> - `missing_books` → 零字节 / 无法解析元数据的 epub
> - `broken_covers` → `coverSource` 为 null / 封面文件缺失或不可读
> - `orphaned_cover_dirs` → 无对应书的封面目录残留（本项目视情况取舍）

---

## 7. 审计对照要点（移植四工具时使用）

1. 前端 `lib/api.ts` 的入参/出参字段名需与 `server.py` 实际返回字段一一对应（上游为 camelCase，注意本项目后端是否已统一）。
2. 实体类型子集：`author` / `series`（本项目），其余类型不要暴露。
3. 改盘安全约定（本项目既有）：`fileops.safe_path` 校验、`plan_*` 只算不改、`apply_*` 只接受前端回传并再校验、`recycle_items` 走回收目录、`library.invalidate()` 写后失效缓存。
4. 缺失封面以 `hasCover === false` 或 `coverSource === null` 表示。
5. 查重 reason 枚举：`file_hash | isbn | exact_metadata | fuzzy_metadata`。
