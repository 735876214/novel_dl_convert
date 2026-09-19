# BookOrbit 书库结构参考契约（移植四工具用）

> 来源：上游参考仓库 **`https://github.com/735876214/bookorbit`**（分支 `main` @ commit `c292d6cc`，站点版本 v2.10.0）；类型定义集中在 `@bookorbit/types` 包（`packages/types/src/`）。
> **来源更正（2026-09-19）**：本文件此前把来源写作 `https://github.com/bookorbit/bookorbit`，该路径并非上游实际地址；已更正为 `735876214/bookorbit`。
> **取证方式（2026-09-19 复核）**：只读镜像（blobless 稀疏克隆，`packages/types` + `packages/plugin-api`，落盘 76 个 `.ts`）**逐文件比对**。下文凡标注「已核对」的 TS 片段，均已与镜像中的同名文件逐字段比对通过；镜像中**不存在**的类型如实标注「未在 `packages/types` 中定义 / 未验证（源码无法确认）」，不臆测补全。
> **取证方式补记（2026-09-20，第 28 期）**：检索「某类型是否存在于 `packages/types`」**必须全目录扫符号**，按文件名猜（如「bulk-rename 的类型应在 `bulk-rename.ts`」）会漏 —— §5 原据此断言「不存在 `BulkRename*`」，实际它们在 `file-write.ts:229-274`。
> 用途：本文件是 **novel_dl_convert 移植四工具（book-duplicates / bulk-rename / entity-manager / missing-resources）** 时，前端 `lib/api.ts`、后端 `core/*` 与上游数据模型的对齐基准。
> 领域映射约定（已拍板）：
> - 「书 book」→ 转换后的小说 epub（`OUTPUT_DIR` 成品文件）+ 元数据（标题/作者/系列）
> - 「实体 entity」→ 作者 / 系列（EPUB 元数据 + 文件名解析）
> - 「重复 duplicate」→ 归一化书名+作者分组或内容哈希重复
> - 「批量重命名 bulk-rename」→ 按命名规则重出版**副本**（改副本文件名；源文件名只读，第 28 期口径）
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

> **已核对**（`packages/types/src/library.ts`，2026-09-19）：上述 `Library` 成员与镜像逐字段一致。
> 注意：上游没有 `path` / `rootDir` / `coverDir` 单字段。物理路径在 `folders[]`，封面只存宽高比。本项目已把「书库」映射为 `OUTPUT_DIR` 成品目录，对应得上。

**同文件内、本契约未展开但移植时可能用到的类型**（均已核对）：

- `LibraryStats`：`totalBooks` / `totalSizeBytes` / `formatCounts`。
- `LibraryOverviewEntry` extends `LibraryStats`：+ `libraryId` / `lastScan`——**一次请求拿全库概览**（上游 `/libraries/:id/stats` + 最近扫描合并成一批），本项目若要「库列表页显示书数与上次扫描」可直接照搬这个合并口径。
- `PrescanPathResult` / `PrescanResult`：建库前预扫描，字段 `accessible` / `fileCount` / **`overlapLibrary`** / `error`——**`overlapLibrary` 是上游对「目录重叠」的显式判定**，与本项目「成品目录不得与库根/扫描源重叠」的约束同源，可作判据措辞参考。
- `AddedAtRecomputeJob`：`addedAt` 来源重算任务（`status: running/completed/failed`，计数 `total/processed/updated/unchanged/skipped/failed`，失败样本 `file_unavailable | unsafe_path | database_error`）——上游把「加入时间」当成**可重算的派生字段**并容忍失败样本，本项目若引入同类能力可参考其错误码。
- `LibraryAccessEntry` / `DefaultLibraryAccessConfig`：按用户授权（`viewer/editor/owner`）——**多用户能力，本项目不做**。
- `DEFAULT_FORMAT_PRIORITY`（16 项，epub 起头）与 `FORMAT_LABELS`（15 项展示名）；`BookFormat` 即由 `DEFAULT_FORMAT_PRIORITY` 派生（源码：`packages/types/src/book.ts:13`，注释说明这两处曾各自维护导致 `azw`/`kepub` 掉队，故改为单一来源）。
- `normalizeCoverAspectRatio()`：非法值一律回落 `"2/3"`。

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

> **已核对**（`packages/types/src/book.ts`，2026-09-19）。两处补正：`BookCard` 另含 `hardcoverEditionId?: string | null`（本段此前漏记）；`BookDetail` 另含 `personalNoteUpdatedAt: string | null`（与 `personalNote` 配套）。
> 关键字段：`hasCover` / `coverSource`（缺失封面）、`files[].absolutePath/filename`（重命名）、`authors[]` + `seriesName`（实体派生）、`folderPath`（定位）。

**同文件内、与本项目直接相关的其他结构**（均已核对）：

- **媒介判定是导出函数，不是字段**：`CONCRETE_BOOK_MEDIA_KINDS = ["ebook", "audiobook", "comic"]`，`BookMediaKind` 额外含 `"unknown"`；`getBookMediaKind(format)` 与 `getBookMediaProfile(files)`（给出 `primaryMediaKind` + `hasEbook/hasAudio/hasComic`）；`getPrimaryBookFile(files)` 按 `role === "primary"` → 首个带 format → 首个 的顺序取主文件。**「一本书可同时有多种媒介」是显式建模**（`hasEbook` 与 `hasAudio` 可同真），与本项目「有声书是目录型条目」的映射需注意口径差异。
- **阅读状态是真字段而非纯推导**：`UserBookStatus = { status: ReadStatus; source: "auto" | "manual"; startedAt; finishedAt; updatedAt }`——`source` 区分**自动推导**与**人工设定**，`startedAt` / `finishedAt` 是显式日期。本项目现状是「状态由进度推导、无起止日期」（见 `bookorbit-capability-gap.md` §3），此结构可作补齐目标。
- **阅读轮次（Reading Attempt）**：`ReadingAttempt`（`startedOn / endedOn / outcome / origin / externalProvider / externalId / totalSessions / totalSeconds`），`outcome ∈ completed|skimmed|abandoned`，`READING_ATTEMPT_ORIGINS = ["manual", "bookorbit", "kobo", "koreader", "hardcover", "migration"]`。即上游把「第几遍读、读到什么结果、来自哪个端」全部落库——比本项目单表 `reading_sessions` 更重的模型，**是否移植需单独决策**。
- **相似书推荐已在类型层存在**：`BookRecommendation` / `SeriesBookRecommendation`（`id / title / coverAspectRatio / updatedAt / hasCover / authors / readStatus / isAudiobook? / isComic?`）与 `UnscopedBookRecommendation`（无用户上下文时去掉 `readStatus`）——`bookorbit-capability-gap.md` §3 的「Similar Books」在上游是**服务端派生列表**，前端只渲染。
- **Kobo 设备态挂在书上**：`BookKoboState`（`eligibleForKoboSync` / `syncCollections` / `readingState` / `snapshots[]`），`BookKoboSnapshotState` 含 `inSnapshot / synced / pendingDelete / isNew / removedByDevice / fileHash / metadataHash`。本项目不做该集成（见 `bookorbit-capability-gap.md` §13）。

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

// 同文件其余类型（2026-09-19 补全并已核对）
export const BOOK_DUPLICATE_SCAN_STATUSES = ["queued", "running", "completed", "failed"] as const;
export type BookDuplicateScanStatus = (typeof BOOK_DUPLICATE_SCAN_STATUSES)[number];

export type BookDuplicateFile = {
  id: number; format: string | null; sizeBytes: number | null; path: string | null;
};

export type BookDuplicateCandidate = {
  id: number; title: string | null; subtitle: string | null; authors: string[];
  libraryId: number; libraryName: string; folderPath: string; status: string;
  files: BookDuplicateFile[];
  isbn10: string | null; isbn13: string | null;
  metadataScore: number | null;
  readStatus: UserBookStatus | null; readingProgress: number | null;
  collections: { id: number; name: string }[];
  addedAt: string; updatedAt: string | null; hasCover: boolean;
};

export type BookDuplicatePair = {
  bookIdA: number; bookIdB: number;
  reasons: BookDuplicateMatchReason[]; titleSimilarity: number | null;
};
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

**已核对**（`packages/types/src/entity-manager.ts`，2026-09-19）：上方代码块与镜像一致，另补四处**移植时必须知道**的结构：

1. **七类实体分两层**：`FIRST_CLASS_ENTITY_TYPES = ["author", "genre", "tag", "narrator", "series"]`；`INLINE_ENTITY_TYPES = ["publisher", "language"]`。`DeleteResult.mode` 的 `"inline"` 正是给后两者用的（它们没有独立表，只在书元数据里内联存在）。
2. **能力矩阵 `ENTITY_CAPABILITIES`**（上游靠它决定按钮显隐，移植时照搬可避免「看得见点不动」）：

| 实体 | canSplit | hasSoftDelete | hasPhoto | hasSortName |
| --- | --- | --- | --- | --- |
| author | 是 | 是 | 是 | 是 |
| genre | 是 | 是 | — | — |
| tag | 是 | 是 | — | — |
| narrator | 是 | 是 | — | 是 |
| publisher | — | — | — | — |
| language | — | — | — | — |
| series | — | — | — | — |

3. **对 series 的影响（本项目的关键判据）**：`series` **不支持拆分、不支持软删除、无图片、无排序名**，与 `genre`/`tag`/`narrator` 的能力档不同。因此移植 series 实体管理时，可用动作只有 **browse / rename / merge / delete(hard) / duplicates**——**不要给 series 提供 split 入口，也不要做「已删除实体恢复」**。
4. `BrowseEntityBookCountFilter = "any" | "empty"`——可筛「没有任何书的空实体」，本项目清理空作者/空系列时可照搬此口径。另：`EntityInfo`（弹窗书单预览，带 `bookTitles`）、`ClusterEntity`（另带 `sortName` / `hasPhoto`）、`PairDetail.reasons` 是**字符串数组而非枚举**（前端直接展示，不走映射）。

> 本项目适配聚焦 **author / series** 两类实体（上游 `EntityType` 子集）；其中 `series` 按上表**只做 browse / rename / merge / delete(hard) / duplicates**。

---

## 5. bulk-rename 批量重命名（依赖 `library.ts` 字段）

上游依赖 `Library.fileNamingPattern`（**已核对**，`library.ts:72`）与 `Library.fileRenameEnabled`（**已核对**，`library.ts:87`），按 `Library` 维度对 `book.files[].filename` 做预览/执行。

> ✅ **更正（2026-09-20，第 28 期）**：本节 2026-09-19 的更正**本身是错的**，现撤掉。当时写「对 `packages/types/src` 全目录检索 `BulkRename`，**没有任何 `BulkRename*` 类型定义**」——实际**有**，就在 `packages/types/src/file-write.ts:229-274`（与 `FileRenameResult` / `BookWriteAndRenameResult` 同段）。当时漏检的原因应是检索按「文件名像 bulk-rename」找而没全目录扫符号；**教训：取证要扫符号，不要按文件名猜**。
> 下面各类型均已与镜像逐字段比对通过（**已核对**）。

```ts
// packages/types/src/file-write.ts:228-274
export type BulkRenameStatus = "will_rename" | "unchanged" | "collision" | "no_pattern" | "error";

export interface BulkRenamePreviewItem {
  bookId: number;
  title: string;
  currentPath: string;
  newPath: string | null;
  status: BulkRenameStatus;
  reason?: string;
}

export interface BulkRenamePreviewPage {
  items: BulkRenamePreviewItem[];
  total: number;
  totalByStatus: Record<BulkRenameStatus, number>;
  /** 预览所依据的命名规则 —— 让客户端能把「变了的路径段」归因到产出它的规则段 */
  pattern: string;
}

/** `excludeBookIds` = 「除这些之外全改」（默认复审流）；`includeBookIds` = 「只改这些」（从空选开始的流）。
 *  两个都传会被拒；都不传 = 改全部候选。两侧都不整份传：候选可上万而客户端只持有已加载的页。 */
export interface BulkRenameExecuteRequest {
  excludeBookIds?: number[];
  includeBookIds?: number[];
}

/** `started` 在任何慢活之前发出，好让响应头立刻 flush、客户端显示真进度；
 *  它的 `total` 是**服务端收窄后**的数，才是权威值。 */
export type BulkRenameProgressEvent =
  | { started: true; total: number }
  | { bookId: number; status: "success" | "failed" | "skipped"; reason?: string }
  | { done: true; processed: number; succeeded: number; failed: number; skipped: number };
```

相邻的动作名 / 通知文案（**已核对**，不是数据结构）：`audit.ts:44` `LibraryBulkRename = "library.bulk_rename"`；`notification.ts:27-28` `BulkRenameCompleted` / `BulkRenameFailed`。

对应 REST（`bulk-rename.ts` api），`BASE = /api/v1/libraries/{libraryId}/bulk-rename`：
- `GET  /preview?page=&pageSize=&status=&search=`
- `GET  /status` → `{ running: boolean }`
- `POST /execute`（body `BulkRenameExecuteRequest`，见上）

### 5.1 本项目现状与**刻意分流**（第 28 期）

| 上游 | 本项目（第 28 期起） | 说明 |
| --- | --- | --- |
| 改 `book.files[].filename`（**源文件真改名**） | **只改硬链接副本名**，源文件名无任何入口可改 | 与本项目「源文件只读」硬约束直接冲突，属**刻意分流**而非缺口 |
| 入口 `/tools/rename` 独立工具页 | 并入刮削面板「命名规则」区块（`core/scrape.py` 的 `plan_naming` / `republish`） | 规则唯一、写点唯一；`/tools/rename` 与 `/api/rename/*` 已删（有 404 防回归断言） |
| `BulkRenamePreviewItem.{currentPath,newPath,status}` | `NamingItem.{old_rel,new_rel,changed,conflict,reason}` | 语义对应；`conflict` 分 `occupied`（落点被别人的文件占着）/ `dup`（同批内重名） |
| `BulkRenamePreviewPage.pattern` / `totalByStatus` | `NamingPlan.{pattern,stats:{total,changed,conflict,ready}}` | 同上，本项目用四档统计 |
| `BulkRenameExecuteRequest`（include / exclude 二选一） | `POST /api/naming/apply` 的 `book_ids`（**只能收窄**，不可扩） | 我们只保留 include 一侧：客户端给不出「去改哪本书」，要改哪些由服务端按规则自算 |
| `BulkRenameProgressEvent`（流式进度） | **无**（同步返回 `{total,done,failed,skipped,items}`） | 串行跑在 `asyncio.to_thread`；进度靠转换日志的轮询看板，不新开流式端点 |
| `scope` 是书库 | `scope` 是**扩展名筛选**（`naming.scope`） | 上游按 `Library` 维度；本项目的书库维度另有入口，见 `docs/bookorbit-capability-gap.md` §5 |

> 因此 bulk-rename 的契约**不以本项目接口为对齐基准、也不再以上游类型反推**：上游类型已核实如上，
> 本项目的对应物以 `core/scrape.py` + `frontend/src/lib/api.ts` 为准（见 §7）。

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

**已核对**（`packages/types/src/maintenance.ts`，2026-09-19）：上方类型与镜像逐字段一致。两处**注释里带的业务语义**必须保留（否则会误用接口）：

- `CoverSweep.truncated`：**结果列表触达保留上限时为 `true`，但各项计数仍是全量**——「列表被截断 ≠ 统计不准」。本项目若做同类 sweep 需照此区分。
- `MissingResourceCleanupResult.remaining`：清理 `all` 是**分轮次的**，每轮只处理有界数量，需**重复调用至 `remaining === 0`**；`skipped` 指「到清理时才复核出已不再符合条件」的条目。这解释了上游页面上「清理」为何可能需要多次触发。

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
3. 改盘安全约定（本项目既有）：`fileops.safe_path` 校验、`plan_*` 只算不改、`recycle_items` 走回收目录、`library.invalidate()` 写后失效缓存。
   **`apply_*` 的目标一律由服务端自己算**（第 28 期收紧，原文写「只接受前端回传并再校验」）：客户端给的 `book_ids` 只当**收窄**条件，预览条目里的旧名/新名仅供参考，不作为落盘依据 —— 预览过期也不会改错书。
   推论：**源文件名没有任何可写入口**（唯一的落盘路径是「按命名规则重出版副本」；仅「同名冲突修复」与「库布局整理」还改 basename，因为它们改的就是这件事本身，且都成对调用 `db.remap_book_id`）。
4. 缺失封面以 `hasCover === false` 或 `coverSource === null` 表示。
5. 查重 reason 枚举：`file_hash | isbn | exact_metadata | fuzzy_metadata`（**已核对**）；扫描状态枚举 `queued | running | completed | failed`（**已核对**，本段此前漏记）。
6. **系列序号（`series-index.ts`，已核对）**：`SeriesIndex` 是**字符串**类型，形状受 `SERIES_INDEX_PATTERN = /^\d+(?:\.\d+)?$/` 与 `SERIES_INDEX_MAX_LENGTH = 20` 约束（`isValidSeriesIndex` / `parseSeriesIndex` 校验，非法即 `null`）。
   - **排序必须用 `compareSeriesIndices`**（分段整数比较：`1.10 > 1.9`；无小数的 `2` 排在 `2.5` 之前），**不要用字符串排序**（否则 `10` 会排在 `2` 前面）。
   - **展示用 `formatSeriesIndex`**：整段**补零到 2 位**（`1` → `01`，`1.5` → `01.5`）。本项目第 6 期起展示 `#序号`，如与上游口径对齐需注意补零规则。
7. **实体动作必须受 `EntityCapabilities` 约束**（见 §4 能力矩阵）：`series` 无 split、无软删除、无图片、无排序名——前端不要渲染这些入口。
8. 上游 `BookMediaKind` 允许**一本书同时是多种媒介**（`hasEbook` 与 `hasAudio` 可同真）；本项目按「单个成品文件 / 目录」建模，映射时需明确「主媒介」口径。
9. **bulk-rename 的预览/执行/进度三组 DTO 已核实**（`file-write.ts:229-274`，见 §5）：`BulkRenamePreviewPage.pattern` 与 `totalByStatus`（按 `BulkRenameStatus` 五档计数）在上游是**响应自带**的，本项目对应 `NamingPlan.{pattern,stats}`；上游 `POST /execute` 用 `excludeBookIds` / `includeBookIds` **二选一**（都传则拒），本项目只保留 include 一侧且**只能收窄**。
10. **分页响应的键名上游自身不统一**：`BooksPage` 用 `size`（`book.ts`），而 `BookDuplicateGroupsResponse` / `BrowseEntitiesResponse` / `MissingResourcePage` / `ReadingAttemptListResponse` 用 `pageSize`。本项目对齐时建议**统一选一套**，不要照抄这种不一致。
