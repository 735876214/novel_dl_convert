import { router } from '@kit.ArkUI';
import { Api, ApiError } from '../common/Api';
import { BookDetail, ChapterRef, DetailParams, Progress, VolumeGroup } from '../common/Models';
import { Palette, Theme } from '../common/Theme';

@Entry
@Component
struct DetailPage {
  @StorageProp('skin') skin: string = 'paper';
  @State detail: BookDetail | null = null;
  @State progress: Progress | null = null;
  @State loading: boolean = true;
  @State error: string = '';
  private bid: string = '';

  private pal(): Palette {
    return Theme.of(this.skin);
  }

  /**
   * 已读百分比：**只来自** `GET /api/books/{bid}/progress`。
   *
   * 曾经这里读的是 `detail.percent` —— 详情接口根本没有这个字段（见
   * `Models.BookDetail` 的注释），于是 `undefined` 一路传到
   * `Math.floor(len * undefined / 100)` 变成 `NaN`，`list[NaN]` 是
   * `undefined`，点「继续阅读」直接崩（真机日志：
   * `TypeError: Cannot read property index of undefined` @ DetailPage.ets:135）。
   */
  private pct(): number {
    const p = this.progress;
    if (p === null) {
      return 0;
    }
    const v = p.percent;
    if (typeof v !== 'number' || !Number.isFinite(v) || v < 0) {
      return 0;
    }
    return v > 100 ? 100 : v;
  }

  aboutToAppear(): void {
    Api.hydrate();
    const p = router.getParams() as DetailParams;
    this.bid = p.bid;
    this.load();
  }

  private async load(): Promise<void> {
    this.loading = true;
    try {
      this.detail = await Api.get<BookDetail>('/api/books/' + this.bid);
    } catch (e) {
      const err = e as ApiError;
      if (err.code === 401) {
        router.replaceUrl({ url: 'pages/LoginPage' });
        return;
      }
      this.error = err.message;
    } finally {
      this.loading = false;
    }
    // 进度单独取：拿不到不影响看目录（进度只是「接着读」用的）
    try {
      this.progress = await Api.get<Progress>('/api/books/' + this.bid + '/progress');
    } catch (e) {
      this.progress = null;
    }
  }

  private chapters(): ChapterRef[] {
    const d = this.detail;
    if (d === null || d.chapters === undefined) {
      return [];
    }
    const out: ChapterRef[] = [];
    for (const g of d.chapters) {
      for (const c of g.chapters) {
        if (c.index !== undefined) {
          out.push(c);
        }
      }
    }
    return out;
  }

  private open(index: number): void {
    const d = this.detail;
    const name = d === null ? '' : d.name;
    router.pushUrl({
      url: 'pages/ReaderPage',
      params: { bid: this.bid, index: index, name: name }
    });
  }

  build() {
    Column() {
      Row() {
        Text('‹ 书架')
          .fontSize(14)
          .fontColor(this.pal().ink)
          .padding(8)
          .onClick(() => {
            router.back();
          })
        Blank()
      }
      .width('100%')
      .padding({ left: 10, right: 10, top: 8 })

      if (this.loading) {
        Column() {
          LoadingProgress().width(36).height(36).color(this.pal().muted)
        }
        .layoutWeight(1)
        .justifyContent(FlexAlign.Center)
      } else if (this.detail === null) {
        Column() {
          Text(this.error.length > 0 ? this.error : '这本书打不开')
            .fontSize(13)
            .fontColor(this.pal().seal)
        }
        .layoutWeight(1)
        .justifyContent(FlexAlign.Center)
      } else {
        Scroll() {
          Column() {
            Text(this.detail.name)
              .fontSize(24)
              .fontWeight(FontWeight.Medium)
              .fontColor(this.pal().ink)
              .width('100%')
            Text(this.detail.format.toUpperCase() + ' · ' + this.chapters().length + ' 章')
              .fontSize(12)
              .fontColor(this.pal().muted)
              .width('100%')
              .margin({ top: 6, bottom: 16 })

            Row() {
              Column() {
                Text('已读')
                  .fontSize(11)
                  .fontColor(this.pal().muted)
                Text(Math.round(this.pct()) + '%')
                  .fontSize(20)
                  .fontColor(this.pal().ink)
                  .margin({ top: 2 })
              }
              .alignItems(HorizontalAlign.Start)
              .layoutWeight(1)
              Button('继续阅读')
                .height(40)
                .fontSize(14)
                .fontColor(this.pal().dark ? '#16130F' : '#FFFDF9')
                .backgroundColor(this.pal().ink)
                .borderRadius(10)
                .onClick(() => {
                  const list = this.chapters();
                  if (list.length === 0) {
                    return;
                  }
                  // 回到上次读到的章：percent→章节只是**近似定位**，
                  // 精确位置由服务端 progress 的 locator / cfi 决定，端上不重算。
                  // 下标必须夹在 [0, len-1]：percent 为 NaN / 负数 / >100 时
                  // 直接取下标会拿到 undefined（真机崩溃的成因）。
                  let i = Math.floor(list.length * this.pct() / 100);
                  if (!Number.isFinite(i) || i < 0) {
                    i = 0;
                  }
                  if (i > list.length - 1) {
                    i = list.length - 1;
                  }
                  const ch: ChapterRef | undefined = list[i];
                  if (ch !== undefined && ch.index !== undefined) {
                    this.open(ch.index);
                  }
                })
            }
            .width('100%')
            .padding(14)
            .backgroundColor(this.pal().card)
            .borderRadius(12)
            .borderWidth(1)
            .borderColor(this.pal().border)
            .margin({ bottom: 18 })

            ForEach(this.detail.chapters, (g: VolumeGroup) => {
              Column() {
                Text(g.volume)
                  .fontSize(12)
                  .fontColor(this.pal().muted)
                  .width('100%')
                  .padding({ top: 10, bottom: 8 })
                ForEach(g.chapters, (c: ChapterRef) => {
                  Row() {
                    Text(c.title)
                      .fontSize(14)
                      .fontColor(this.pal().ink)
                      .layoutWeight(1)
                      .maxLines(1)
                      .textOverflow({ overflow: TextOverflow.Ellipsis })
                    if (c.index !== undefined) {
                      Text('' + c.index)
                        .fontSize(11)
                        .fontColor(this.pal().muted)
                    }
                  }
                  .width('100%')
                  .padding({ top: 11, bottom: 11 })
                  .border({ width: { bottom: 1 }, color: this.pal().border })
                  .onClick(() => {
                    if (c.index !== undefined) {
                      this.open(c.index);
                    }
                  })
                }, (c: ChapterRef) => c.title + '_' + c.index)
              }
              .alignItems(HorizontalAlign.Start)
              .width('100%')
            }, (g: VolumeGroup) => g.volume)
          }
          .padding({ left: 18, right: 18, bottom: 40 })
        }
        .layoutWeight(1)
        .scrollBar(BarState.Off)
      }
    }
    .width('100%')
    .height('100%')
    .backgroundColor(this.pal().bg)
  }
}
