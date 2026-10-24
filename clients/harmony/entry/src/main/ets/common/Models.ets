/**
 * 数据形状：与 tests/test_client_contract.py 里钉住的字段面一一对应。
 * 这里只声明端上真正读到的字段 —— 多声明一个字段就等于多一处会漂的契约。
 */

/** GET /api/books 的 items[] */
export interface BookCard {
  id: string;
  name: string;
  format: string;
  library_id: string;
  has_description: boolean;
  percent: number;
  updated_at: string;
  annotation_count: number;
  collection_ids: string[];
  stars: number;
  status: string;
}

/** GET /api/books 的外壳（六个键，contract 测试钉的是精确集合） */
export interface BooksPage {
  items: BookCard[];
  total: number;
  scanning: boolean;
  limit: number;
  offset: number;
  has_more: boolean;
}

/** GET /api/libraries 的条目 */
export interface LibraryInfo {
  id: string;
  name: string;
}

export interface LibraryList {
  items: LibraryInfo[];
}

/** 详情里的章节条目：index 是 spine 序，也是 /chapter/{index} 的入参 */
export interface ChapterRef {
  title: string;
  index?: number;
}

/** 详情里的目录按卷分组 */
export interface VolumeGroup {
  volume: string;
  chapters: ChapterRef[];
}

/**
 * GET /api/books/{bid}
 *
 * ⚠️ 详情**没有** `percent`：阅读进度只在 `GET /api/books` 的卡片上
 * （server.py 的 `api_books` 用 `db.all_progress()` 现拼）和
 * `GET /api/books/{bid}/progress` 上。详情是 `library.book_detail()` 的
 * 直接产物，里面没有进度字段。
 */
export interface BookDetail {
  id: string;
  name: string;
  format: string;
  library_id: string;
  chapters: VolumeGroup[];
}

/**
 * GET /api/books/{bid}/progress —— 阅读位置的**真值源**。
 *
 * 无记录时服务端回 `{locator:0, percent:0, cfi:'', file_rel:null}`（没有 `updated_at`）。
 * `cfi` 由服务端 `core/epub_cfi.py` 生成，**端上不实现 CFI**，只用 `percent`
 * 做「回到大概哪一章」的近似定位。
 */
export interface Progress {
  locator: number;
  percent: number;
  cfi: string;
  updated_at?: number;
  file_rel: string | null;
}

/** GET /api/books/{bid}/chapter/{index} */
export interface ChapterBody {
  index: number;
  total: number;
  title: string;
  html: string;
}

/** GET /health */
export interface HealthInfo {
  status: string;
  version: string;
  problems: string[];
}

/** POST /api/auth/login */
export interface LoginResult {
  token: string;
  user: string;
}

/** 服务端错误体（FastAPI 的 detail） */
export interface ErrorBody {
  detail: string;
}

/** 页面间传参 */
export interface DetailParams {
  bid: string;
}

export interface ReaderParams {
  bid: string;
  index: number;
  name: string;
}
