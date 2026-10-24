import { AbilityConstant, UIAbility, Want } from '@kit.AbilityKit';
import { window } from '@kit.ArkUI';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { Session } from '../common/Session';
import { Cache } from '../common/Cache';
import { Theme } from '../common/Theme';

const DOMAIN: number = 0x0001;
const TAG: string = 'NovelForge';

export default class EntryAbility extends UIAbility {
  onCreate(want: Want, launchParam: AbilityConstant.LaunchParam): void {
    hilog.info(DOMAIN, TAG, 'onCreate');
  }

  async onWindowStageCreate(windowStage: window.WindowStage): Promise<void> {
    // 会话与离线缓存的根目录都要在首个页面渲染前就绪：
    // 页面一进 aboutToAppear 就要读 baseUrl / token / 缓存清单。
    await Session.init(this.context);
    Cache.init(this.context);
    Theme.apply(Session.get('skin'));

    windowStage.loadContent('pages/LoginPage', (err) => {
      if (err.code) {
        hilog.error(DOMAIN, TAG, 'loadContent failed: %{public}s', JSON.stringify(err));
      }
    });
  }

  onWindowStageDestroy(): void {
    hilog.info(DOMAIN, TAG, 'onWindowStageDestroy');
  }

  onDestroy(): void {
    hilog.info(DOMAIN, TAG, 'onDestroy');
  }
}
