import { router } from '@kit.ArkUI';
import { webview } from '@kit.ArkWeb';
import { Api } from '../common/Api';
import { ChapterBody, ReaderParams } from '../common/Models';
import { Cache } from '../common/Cache';
import { Palette, Theme } from '../common/Theme';

/**
 * 阅读面 = ArkWeb 载入 NAS 上已有的 SPA。
 *
 * 为什么不在端上重写排版：书内版式、批注锚定、四套子阅读器都在
 * frontend/src/views/ReaderView.vue 那 141KB 里，重写一遍就是第二份实现。
 * 端上只负责「把令牌在首帧前塞进去」和「把正文缓存下来」。
 */
@Entry
@Component
struct ReaderPage {
  @StorageProp('skin') skin: string = 'paper';
  @State src: string = '';
  @State note: string = '';
  @State offline: boolean = false;
  private controller: webview.WebviewController = new webview.WebviewController();
  private bid: string = '';
  private index: number = 0;
  /** 0 = 还没注入令牌，1 = 已注入 */
  private stage: number = 0;

  private pal(): Palette {
    return Theme.of(this.skin);
  }

  aboutToAppear(): void {
    Api.hydrate();
    const p = router.getParams() as ReaderParams;
    this.bid = p.bid;
    this.index = p.index;
    this.boot();
  }

  private targetUrl(): string {
    // SPA 是 hash 路由；?chapter=<spine index> 是阅读器认的直达参数
    return Api.baseUrl + '/static/v2/index.html#/read/' + this.bid + '?chapter=' + this.index;
  }

  private async boot(): Promise<void> {
    try {
      await Api.health();
      this.offline = false;
      this.stage = 0;
      // 先加载同源的 /health，再注入 localStorage：SPA 首帧就要读 nf_token，
      // 直接加载阅读页会先闪一次 401。
      this.src = Api.join('/health');
    } catch (e) {
      this.offline = true;
      const view = Cache.buildOfflineView(this.bid, this.index, this.skin);
      if (view.length > 0) {
        this.src = view;
        this.note = '离线 · 显示已缓存的这一回';
      } else {
        this.note = '连不上 NAS，这一回还没缓存到本机';
      }
    }
  }

  private onPageEnd(): void {
    if (this.offline) {
      return;
    }
    if (this.stage === 0) {
      const token = Api.token.replace(/'/g, "\\'");
      this.controller.runJavaScript("localStorage.setItem('nf_token','" + token + "')",
        (err, res) => {
          this.stage = 1;
          this.controller.loadUrl(this.targetUrl());
        });
      return;
    }
    // 阅读页已加载：顺手把这一回正文与位置存到本机
    this.saveCurrent();
  }

  private async saveCurrent(): Promise<void> {
    try {
      const c = await Api.get<ChapterBody>('/api/books/' + this.bid + '/chapter/' + this.index);
      Cache.saveChapter(this.bid, this.index, c.title, c.total, c.html);
      this.note = '已缓存 · ' + c.title;
    } catch (e) {
      // 缓存失败不影响正在进行的阅读
    }
  }

  build() {
    Column() {
      Row() {
        Text('‹ 返回')
          .fontSize(14)
          .fontColor(this.pal().ink)
          .padding(8)
          .onClick(() => {
            router.back();
          })
        Blank()
        if (this.note.length > 0) {
          Text(this.note)
            .fontSize(11)
            .fontColor(this.offline ? this.pal().seal : this.pal().muted)
            .maxLines(1)
        }
      }
      .width('100%')
      .padding({ left: 8, right: 14, top: 6, bottom: 6 })
      .backgroundColor(this.pal().bg)

      if (this.src.length > 0) {
        Web({ src: this.src, controller: this.controller })
          .javaScriptAccess(true)
          .domStorageAccess(true)
          .fileAccess(true)
          .onPageEnd(() => {
            this.onPageEnd();
          })
          .layoutWeight(1)
      } else {
        Column() {
          LoadingProgress().width(32).height(32).color(this.pal().muted)
        }
        .layoutWeight(1)
        .justifyContent(FlexAlign.Center)
      }
    }
    .width('100%')
    .height('100%')
    .backgroundColor(this.pal().bg)
  }
}
