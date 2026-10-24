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

/** GET /api/books/{bid} */
export interface BookDetail {
  id: string;
  name: string;
  format: string;
  library_id: string;
  percent: number;
  chapters: VolumeGroup[];
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
