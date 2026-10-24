import { fileIo } from '@kit.CoreFileKit';
import { common } from '@kit.AbilityKit';
import { BookCard } from './Models';

const ROOT_NAME: string = 'reader-cache';
const MANIFEST: string = 'shelf.json';

interface ChapterMeta {
  title: string;
  total: number;
  savedAt: number;
}

interface ShelfManifest {
  savedAt: number;
  books: BookCard[];
}

/**
 * 离线缓存。只缓存「已经读到过」的章节正文 + 书架清单。
 *
 * 落盘位置：<filesDir>/reader-cache/<bid>/<index>.html
 * 离线兜底渲染：把缓存的正文包成一个自包含 HTML 写 <index>.view.html，
 * 用 Web 组件以 file:// 打开 —— 复用同一个渲染内核，不写第二套排版。
 */
export class Cache {
  private static root: string = '';

  static init(ctx: common.UIAbilityContext): void {
    Cache.root = ctx.filesDir + '/' + ROOT_NAME;
    if (!fileIo.accessSync(Cache.root)) {
      fileIo.mkdirSync(Cache.root, true);
    }
  }

  private static bookDir(bid: string): string {
    const d = Cache.root + '/' + bid;
    if (!fileIo.accessSync(d)) {
      fileIo.mkdirSync(d, true);
    }
    return d;
  }

  private static write(path: string, text: string): void {
    const f = fileIo.openSync(path,
      fileIo.OpenMode.READ_WRITE | fileIo.OpenMode.CREATE | fileIo.OpenMode.TRUNC);
    try {
      fileIo.writeSync(f.fd, text);
    } finally {
      fileIo.closeSync(f);
    }
  }

  private static read(path: string): string {
    if (!fileIo.accessSync(path)) {
      return '';
    }
    try {
      return fileIo.readTextSync(path);
    } catch (e) {
      return '';
    }
  }

  static saveChapter(bid: string, index: number, title: string, total: number, html: string): void {
    try {
      const d = Cache.bookDir(bid);
      Cache.write(d + '/' + index + '.html', html);
      const meta: ChapterMeta = { title: title, total: total, savedAt: Date.now() };
      Cache.write(d + '/' + index + '.meta.json', JSON.stringify(meta));
    } catch (e) {
      // 缓存失败不能影响阅读：静默即可，下次再试。
    }
  }

  static hasChapter(bid: string, index: number): boolean {
    return fileIo.accessSync(Cache.root + '/' + bid + '/' + index + '.html');
  }

  /** 造一份自包含的离线视图，返回 file:// 路径；没有缓存返回空串 */
  static buildOfflineView(bid: string, index: number, skin: string): string {
    const d = Cache.root + '/' + bid;
    const html = Cache.read(d + '/' + index + '.html');
    if (html.length === 0) {
      return '';
    }
    let title = '第 ' + (index + 1) + ' 回';
    try {
      const meta = JSON.parse(Cache.read(d + '/' + index + '.meta.json')) as ChapterMeta;
      if (meta.title !== undefined && meta.title.length > 0) {
        title = meta.title;
      }
    } catch (e) {
      // 元信息缺失时用兜底标题，不编造章节名。
    }
    const bg = skin === 'night' ? '#16130F' : (skin === 'green' ? '#EDF3E9' : '#F7F3EC');
    const ink = skin === 'night' ? '#EFE8DC' : (skin === 'green' ? '#22301F' : '#2B2622');
    const muted = skin === 'night' ? '#A79E90' : (skin === 'green' ? '#66735E' : '#7A7168');
    const page = '<!doctype html><html><head><meta charset="utf-8">'
      + '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
      + '<style>html,body{margin:0;background:' + bg + ';color:' + ink + '}'
      + 'body{padding:18px 20px 56px;font:17px/1.85 "Songti SC","Noto Serif CJK SC",serif}'
      + '.bar{position:sticky;top:0;margin:-18px -20px 14px;padding:10px 20px;background:' + bg
      + ';border-bottom:1px solid ' + muted + '33;font:12px/1.4 system-ui;color:' + muted + '}'
      + 'p{text-indent:2em;margin:0 0 .85em}h1{font-size:17px;margin:0 0 16px}'
      + 'img{max-width:100%;height:auto}</style></head><body>'
      + '<div class="bar">离线 · 本地缓存 · ' + title + '</div>'
      + '<h1>' + title + '</h1>' + html + '</body></html>';
    try {
      const p = d + '/' + index + '.view.html';
      Cache.write(p, page);
      return 'file://' + p;
    } catch (e) {
      return '';
    }
  }

  static saveShelf(books: BookCard[]): void {
    try {
      const m: ShelfManifest = { savedAt: Date.now(), books: books };
      Cache.write(Cache.root + '/' + MANIFEST, JSON.stringify(m));
    } catch (e) {
      // 同上：缓存失败不阻断
    }
  }

  static loadShelf(): BookCard[] {
    const text = Cache.read(Cache.root + '/' + MANIFEST);
    if (text.length === 0) {
      return [];
    }
    try {
      const m = JSON.parse(text) as ShelfManifest;
      return m.books === undefined ? [] : m.books;
    } catch (e) {
      return [];
    }
  }

  /** 缓存占用（字节），给设置页显示 */
  static sizeBytes(): number {
    let total = 0;
    try {
      const books = fileIo.listFileSync(Cache.root);
      for (const b of books) {
        try {
          const files = fileIo.listFileSync(Cache.root + '/' + b);
          for (const f of files) {
            const st = fileIo.statSync(Cache.root + '/' + b + '/' + f);
            total += st.size;
          }
        } catch (e) {
          // 单个目录读不到就跳过
        }
      }
    } catch (e) {
      return 0;
    }
    return total;
  }

  static clear(): void {
    try {
      if (fileIo.accessSync(Cache.root)) {
        fileIo.rmdirSync(Cache.root);
      }
    } catch (e) {
      // 清不掉就下次再清
    }
    if (!fileIo.accessSync(Cache.root)) {
      fileIo.mkdirSync(Cache.root, true);
    }
  }
}
