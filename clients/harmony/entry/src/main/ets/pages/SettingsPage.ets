import { router } from '@kit.ArkUI';
import { promptAction } from '@kit.ArkUI';
import { Cache } from '../common/Cache';
import { KEY_SKIN, Session } from '../common/Session';
import { Api } from '../common/Api';
import { Palette, Theme } from '../common/Theme';

@Entry
@Component
struct SettingsPage {
  @StorageProp('skin') skin: string = 'paper';
  @State cacheText: string = '—';

  private pal(): Palette {
    return Theme.of(this.skin);
  }

  aboutToAppear(): void {
    Api.hydrate();
    this.refreshSize();
  }

  private refreshSize(): void {
    const b = Cache.sizeBytes();
    if (b < 1024) {
      this.cacheText = b + ' B';
    } else if (b < 1024 * 1024) {
      this.cacheText = (b / 1024).toFixed(0) + ' KB';
    } else {
      this.cacheText = (b / 1024 / 1024).toFixed(1) + ' MB';
    }
  }

  private setSkin(s: string): void {
    Session.set(KEY_SKIN, s);
    Theme.apply(s);
  }

  @Builder
  section(title: string) {
    Text(title)
      .fontSize(11)
      .fontColor(this.pal().muted)
      .width('100%')
      .padding({ left: 18, top: 20, bottom: 8 })
  }

  @Builder
  skinChip(s: string) {
    Text(Theme.label(s))
      .fontSize(13)
      .fontColor(this.skin === s ? this.pal().seal : this.pal().ink)
      .padding({ left: 14, right: 14, top: 8, bottom: 8 })
      .borderRadius(8)
      .borderWidth(1)
      .borderColor(this.skin === s ? this.pal().seal : this.pal().border)
      .backgroundColor(this.pal().card)
      .margin({ right: 10 })
      .onClick(() => {
        this.setSkin(s);
      })
  }

  @Builder
  row(label: string, value: string) {
    Row() {
      Text(label)
        .fontSize(14)
        .fontColor(this.pal().ink)
      Blank()
      Text(value)
        .fontSize(13)
        .fontColor(this.pal().muted)
        .maxLines(1)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
        .constraintSize({ maxWidth: '62%' })
    }
    .width('100%')
    .padding({ left: 18, right: 18, top: 14, bottom: 14 })
    .backgroundColor(this.pal().card)
    .border({ width: { bottom: 1 }, color: this.pal().border })
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
      }
      .width('100%')
      .padding({ left: 8, top: 6 })

      Scroll() {
        Column() {
          this.section('外观')
          Row() {
            this.skinChip('paper')
            this.skinChip('night')
            this.skinChip('green')
          }
          .width('100%')
          .padding({ left: 18, right: 8 })
          .backgroundColor(this.pal().card)
          .padding({ top: 12, bottom: 12 })

          this.section('连接')
          this.row('服务器', Session.baseUrl().length > 0 ? Session.baseUrl() : '未设置')
          this.row('账号', Session.user().length > 0 ? Session.user() : '—')
          this.row('设备标识', Session.deviceId())

          this.section('离线缓存')
          this.row('已用空间', this.cacheText)
          Row() {
            Text('清空本地缓存')
              .fontSize(14)
              .fontColor(this.pal().seal)
            Blank()
          }
          .width('100%')
          .padding({ left: 18, right: 18, top: 14, bottom: 14 })
          .backgroundColor(this.pal().card)
          .border({ width: { bottom: 1 }, color: this.pal().border })
          .onClick(() => {
            Cache.clear();
            this.refreshSize();
            promptAction.showToast({ message: '已清空本地缓存' });
          })

          this.section('账号')
          Row() {
            Text('退出登录')
              .fontSize(14)
              .fontColor(this.pal().ink)
            Blank()
          }
          .width('100%')
          .padding({ left: 18, right: 18, top: 14, bottom: 14 })
          .backgroundColor(this.pal().card)
          .onClick(() => {
            Session.logout();
            router.replaceUrl({ url: 'pages/LoginPage' });
          })

          Text('书斋 1.0.0 · 侧载调试包 · 只连局域网 NAS\n书籍内容与阅读进度都存在 NAS 上，端内只留已读章节的缓存。')
            .fontSize(11)
            .fontColor(this.pal().muted)
            .width('100%')
            .padding({ left: 18, right: 18, top: 24, bottom: 40 })
        }
      }
      .layoutWeight(1)
      .scrollBar(BarState.Off)
    }
    .width('100%')
    .height('100%')
    .backgroundColor(this.pal().bg)
  }
}
