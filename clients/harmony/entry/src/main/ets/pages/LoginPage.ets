import { router } from '@kit.ArkUI';
import { promptAction } from '@kit.ArkUI';
import { Api, ApiError } from '../common/Api';
import { HealthInfo, LoginResult } from '../common/Models';
import { KEY_BASE, KEY_TOKEN, KEY_USER, Session } from '../common/Session';
import { Palette, Theme } from '../common/Theme';

@Entry
@Component
struct LoginPage {
  @StorageProp('skin') skin: string = 'paper';
  @State baseUrl: string = '';
  @State user: string = '';
  @State pin: string = '';
  @State probing: boolean = false;
  @State probeText: string = '';
  @State probeOk: boolean = false;
  @State busy: boolean = false;
  @State error: string = '';
  @State serverVersion: string = '';

  private pal(): Palette {
    return Theme.of(this.skin);
  }

  aboutToAppear(): void {
    Api.hydrate();
    this.baseUrl = Session.baseUrl().length > 0 ? Session.baseUrl() : 'http://192.168.1.20:8992';
    this.user = Session.user().length > 0 ? Session.user() : 'admin';
    if (Session.loggedIn()) {
      router.replaceUrl({ url: 'pages/ShelfPage' });
    }
  }

  /** 用户可能只输 192.168.1.20:8992，补上 http:// 再试 */
  private normalize(input: string): string {
    let v = input.trim();
    if (v.length === 0) {
      return '';
    }
    if (!v.startsWith('http://') && !v.startsWith('https://')) {
      v = 'http://' + v;
    }
    return v;
  }

  private async probe(): Promise<void> {
    const url = this.normalize(this.baseUrl);
    if (url.length === 0) {
      this.probeText = '先填服务器地址';
      this.probeOk = false;
      return;
    }
    this.probing = true;
    this.probeText = '正在连 NAS…';
    this.probeOk = false;
    Api.baseUrl = url;
    Api.token = '';
    try {
      const h = await Api.health();
      this.serverVersion = h.version;
      const problems = h.problems === undefined ? [] : h.problems;
      if (problems.length > 0) {
        this.probeText = '已连上 · ' + h.version + ' · 但服务端报告：' + problems.join(' / ');
        this.probeOk = false;
      } else {
        this.probeText = '已连上 · ' + h.version + ' · ' + h.status;
        this.probeOk = true;
      }
    } catch (e) {
      const err = e as ApiError;
      this.probeText = err.offline ? '连不上：' + err.message : ('预检失败：' + err.message);
      this.probeOk = false;
    } finally {
      this.probing = false;
    }
  }

  private async doLogin(): Promise<void> {
    if (this.busy) {
      return;
    }
    const url = this.normalize(this.baseUrl);
    if (url.length === 0 || this.pin.length === 0) {
      this.error = '服务器地址和口令都要填';
      return;
    }
    this.busy = true;
    this.error = '';
    Api.baseUrl = url;
    Api.token = '';
    try {
      const r: LoginResult = await Api.login(this.user, this.pin);
      Session.set(KEY_BASE, url);
      Session.set(KEY_TOKEN, r.token);
      Session.set(KEY_USER, r.user);
      Api.hydrate();
      promptAction.showToast({ message: '已连接 ' + url });
      router.replaceUrl({ url: 'pages/ShelfPage' });
    } catch (e) {
      const err = e as ApiError;
      this.error = err.message;
    } finally {
      this.busy = false;
    }
  }

  build() {
    Column() {
      Column() {
        Text('书斋')
          .fontSize(38)
          .fontWeight(FontWeight.Medium)
          .fontFamily('HarmonyOS Sans SC')
          .fontColor(this.pal().ink)
        Text('连到你自己 NAS 上的书库')
          .fontSize(13)
          .fontColor(this.pal().muted)
          .margin({ top: 6 })
      }
      .alignItems(HorizontalAlign.Start)
      .width('100%')
      .margin({ bottom: 28 })

      Text('服务器')
        .fontSize(12)
        .fontColor(this.pal().muted)
        .width('100%')
      TextInput({ text: this.baseUrl, placeholder: 'http://192.168.1.20:8992' })
        .onChange((v: string) => {
          this.baseUrl = v;
        })
        .fontSize(15)
        .height(46)
        .margin({ top: 6, bottom: 14 })
        .backgroundColor(this.pal().card)
        .borderRadius(10)
        .borderWidth(1)
        .borderColor(this.pal().border)
        .padding({ left: 12, right: 12 })

      Text('账号')
        .fontSize(12)
        .fontColor(this.pal().muted)
        .width('100%')
      TextInput({ text: this.user, placeholder: 'admin' })
        .onChange((v: string) => {
          this.user = v;
        })
        .fontSize(15)
        .height(46)
        .margin({ top: 6, bottom: 14 })
        .backgroundColor(this.pal().card)
        .borderRadius(10)
        .borderWidth(1)
        .borderColor(this.pal().border)
        .padding({ left: 12, right: 12 })

      Text('口令')
        .fontSize(12)
        .fontColor(this.pal().muted)
        .width('100%')
      TextInput({ text: this.pin, placeholder: '登录口令' })
        .type(InputType.Password)
        .onChange((v: string) => {
          this.pin = v;
        })
        .fontSize(15)
        .height(46)
        .margin({ top: 6, bottom: 10 })
        .backgroundColor(this.pal().card)
        .borderRadius(10)
        .borderWidth(1)
        .borderColor(this.pal().border)
        .padding({ left: 12, right: 12 })

      Row() {
        Button(this.probing ? '连接中…' : '测试连接')
          .fontSize(13)
          .height(34)
          .backgroundColor(Color.Transparent)
          .fontColor(this.pal().ink)
          .borderWidth(1)
          .borderColor(this.pal().border)
          .borderRadius(8)
          .enabled(!this.probing)
          .onClick(() => {
            this.probe();
          })
        Text(this.probeText)
          .fontSize(12)
          .fontColor(this.probeOk ? this.pal().ink : this.pal().seal)
          .layoutWeight(1)
          .margin({ left: 10 })
          .maxLines(2)
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)
      .margin({ bottom: 18 })

      Button(this.busy ? '登录中…' : '进入书架')
        .width('100%')
        .height(48)
        .fontSize(16)
        .fontColor(this.pal().dark ? '#16130F' : '#FFFDF9')
        .backgroundColor(this.busy ? this.pal().muted : this.pal().ink)
        .borderRadius(12)
        .enabled(!this.busy)
        .onClick(() => {
          this.doLogin();
        })

      if (this.error.length > 0) {
        Text(this.error)
          .fontSize(12)
          .fontColor(this.pal().seal)
          .width('100%')
          .margin({ top: 12 })
      }

      Blank()

      Text(this.serverVersion.length > 0 ? ('服务端版本 ' + this.serverVersion) : '这个 App 只连局域网里的 NAS')
        .fontSize(11)
        .fontColor(this.pal().muted)
        .margin({ bottom: 8 })
    }
    .width('100%')
    .height('100%')
    .padding({ left: 24, right: 24, top: 64, bottom: 24 })
    .backgroundColor(this.pal().bg)
  }
}
