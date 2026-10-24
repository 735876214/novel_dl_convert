import { router } from '@kit.ArkUI';
import { Api, ApiError } from '../common/Api';
import { BookCard, BooksPage, LibraryInfo, LibraryList } from '../common/Models';
import { Cache } from '../common/Cache';
import { Session } from '../common/Session';
import { Palette, Theme } from '../common/Theme';

/** 封面没图时的色块：按书名散列挑一组，稳定不跳色 */
const COVER_PAIRS: string[][] = [
  ['#8C4A3C', '#5E2C24'],
  ['#3F5D4E', '#26382F'],
  ['#4A4F75', '#2C3049'],
  ['#7A6134', '#4C3C1F'],
  ['#6B4360', '#41263A'],
  ['#2F5A63', '#1C373D']
];

@Entry
@Component
struct ShelfPage {
  @StorageProp('skin') skin: string = 'paper';
  @State books: BookCard[] = [];
  @State libraries: LibraryInfo[] = [];
  @State libId: string = '';
  @State loading: boolean = true;
  @State offline: boolean = false;
  @State error: string = '';

  private pal(): Palette {
    return Theme.of(this.skin);
  }

  aboutToAppear(): void {
    Api.hydrate();
    if (!Session.loggedIn()) {
      router.replaceUrl({ url: 'pages/LoginPage' });
      return;
    }
    this.load();
  }

  private async load(): Promise<void> {
    this.loading = true;
    this.error = '';
    try {
      // limit=0 是「不限」——契约测试里钉死了这个语义，端上一次拿全就靠它
      const page = await Api.get<BooksPage>('/api/books?limit=0');
      this.books = page.items;
      this.offline = false;
      Cache.saveShelf(page.items);
      try {
        const libs = await Api.get<LibraryList>('/api/libraries');
        this.libraries = libs.items === undefined ? [] : libs.items;
      } catch (e) {
        // 书库列表拿不到不影响看书：只是切库条不显示
        this.libraries = [];
      }
    } catch (e) {
      const err = e as ApiError;
      if (err.code === 401) {
        Session.logout();
        router.replaceUrl({ url: 'pages/LoginPage' });
        return;
      }
      if (err.offline) {
        // 断网：退回本地缓存的书架，不显示空白页
        const cached = Cache.loadShelf();
        this.books = cached;
        this.offline = true;
        this.error = cached.length > 0
          ? ('连不上 NAS，正在看本地缓存的 ' + cached.length + ' 本')
          : ('连不上 NAS：' + err.message);
      } else {
        this.error = err.message;
      }
    } finally {
      this.loading = false;
    }
  }

  private visible(): BookCard[] {
    if (this.libId.length === 0) {
      return this.books;
    }
    // 服务端 /api/books 没有 library_id 参数，切库只能是端上本地过滤
    return this.books.filter((b: BookCard) => b.library_id === this.libId);
  }

  private pairOf(name: string): string[] {
    let h = 0;
    for (let i = 0; i < name.length; i++) {
      h = (h * 31 + name.charCodeAt(i)) % 100000;
    }
    return COVER_PAIRS[h % COVER_PAIRS.length];
  }

  private libName(): string {
    if (this.libId.length === 0) {
      return '全部书库';
    }
    for (const l of this.libraries) {
      if (l.id === this.libId) {
        return l.name;
      }
    }
    return this.libId;
  }

  @Builder
  chip(label: string, active: boolean, id: string) {
    Text(label)
      .fontSize(13)
      .fontColor(active ? (this.pal().dark ? '#16130F' : '#FFFDF9') : this.pal().ink)
      .backgroundColor(active ? this.pal().ink : this.pal().sub)
      .borderRadius(16)
      .padding({ left: 14, right: 14, top: 7, bottom: 7 })
      .margin({ right: 8 })
      .onClick(() => {
        this.libId = id;
      })
  }

  @Builder
  bookTile(b: BookCard) {
    Column() {
      Stack({ alignContent: Alignment.Bottom }) {
        Column()
          .width('100%')
          .height(118)
          .borderRadius(8)
          .linearGradient({
            angle: 135,
            colors: [[this.pairOf(b.name)[0], 0.0], [this.pairOf(b.name)[1], 1.0]]
          })
        Text(b.name.substring(0, 1))
          .fontSize(30)
          .fontColor('#FFFFFF55')
          .margin({ bottom: 8 })
      }
      .width('100%')

      Text(b.name)
        .fontSize(13)
        .fontColor(this.pal().ink)
        .maxLines(2)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
        .margin({ top: 8 })
        .width('100%')

      Row() {
        Text(Math.round(b.percent) + '%')
          .fontSize(11)
          .fontColor(this.pal().muted)
        Blank()
        if (b.annotation_count > 0) {
          Text('批注 ' + b.annotation_count)
            .fontSize(11)
            .fontColor(this.pal().muted)
        }
      }
      .width('100%')
      .margin({ top: 3 })

      Stack({ alignContent: Alignment.Start }) {
        Row()
          .width('100%')
          .height(2)
          .backgroundColor(this.pal().border)
        Row()
          .width(Math.max(2, Math.round(b.percent)) + '%')
          .height(2)
          .backgroundColor(this.pal().seal)
      }
      .width('100%')
      .margin({ top: 5 })
    }
    .width('100%')
    .onClick(() => {
      router.pushUrl({ url: 'pages/DetailPage', params: { bid: b.id } });
    })
  }

  build() {
    Column() {
      Row() {
        Column() {
          Text('书架')
            .fontSize(26)
            .fontWeight(FontWeight.Medium)
            .fontColor(this.pal().ink)
          Text(this.libName() + ' · ' + this.visible().length + ' 本')
            .fontSize(12)
            .fontColor(this.pal().muted)
            .margin({ top: 3 })
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1)

        Text('设置')
          .fontSize(13)
          .fontColor(this.pal().ink)
          .padding(8)
          .onClick(() => {
            router.pushUrl({ url: 'pages/SettingsPage' });
          })
      }
      .width('100%')
      .padding({ left: 18, right: 14, top: 14, bottom: 10 })

      if (this.libraries.length > 0) {
        Scroll() {
          Row() {
            this.chip('全部', this.libId.length === 0, '')
            ForEach(this.libraries, (l: LibraryInfo) => {
              this.chip(l.name, this.libId === l.id, l.id)
            }, (l: LibraryInfo) => l.id)
          }
        }
        .scrollable(ScrollDirection.Horizontal)
        .scrollBar(BarState.Off)
        .width('100%')
        .padding({ left: 18, right: 10 })
        .margin({ bottom: 6 })
      }

      if (this.error.length > 0) {
        Text(this.error)
          .fontSize(12)
          .fontColor(this.offline ? this.pal().muted : this.pal().seal)
          .width('100%')
          .padding({ left: 18, right: 18, top: 6, bottom: 6 })
      }

      if (this.loading) {
        Column() {
          LoadingProgress().width(36).height(36).color(this.pal().muted)
          Text('正在读 NAS 上的书目…')
            .fontSize(12)
            .fontColor(this.pal().muted)
            .margin({ top: 10 })
        }
        .layoutWeight(1)
        .justifyContent(FlexAlign.Center)
      } else if (this.visible().length === 0) {
        Column() {
          Text('这个书库还没有书')
            .fontSize(14)
            .fontColor(this.pal().ink)
          Text('在 NAS 上把书丢进收书目录就会出现在这里')
            .fontSize(12)
            .fontColor(this.pal().muted)
            .margin({ top: 6 })
        }
        .layoutWeight(1)
        .justifyContent(FlexAlign.Center)
      } else {
        // 每行 3 本：这是「封面别太大」那条需求的落点
        Grid() {
          ForEach(this.visible(), (b: BookCard) => {
            GridItem() {
              this.bookTile(b)
            }
          }, (b: BookCard) => b.id)
        }
        .columnsTemplate('1fr 1fr 1fr')
        .columnsGap(12)
        .rowsGap(18)
        .padding({ left: 18, right: 18, top: 6, bottom: 18 })
        .layoutWeight(1)
      }
    }
    .width('100%')
    .height('100%')
    .backgroundColor(this.pal().bg)
  }
}
