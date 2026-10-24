/**
 * 外观主题：三档，与 NAS 上 SPA 的 tokens.css 同源同值。
 *
 * 为什么用十六进制而不是 oklch：ArkUI 的 Color 不认 oklch()，
 * 这里的值是 tokens.css 里 oklch 折算后的近似十六进制，唯一真值源仍是
 * novelforge/../frontend/src/assets/theme/tokens.css。改色请先改那边再回来折算，
 * 不要在这里凭感觉调。
 */
export class Palette {
  /** 页面底 */
  bg: string = '#F7F3EC';
  /** 卡片底 */
  card: string = '#FFFDF9';
  /** 更浅一层的表面（分组条、输入框） */
  sub: string = '#F1EBE0';
  /** 边框 */
  border: string = '#E3DACA';
  /** 正文墨色 */
  ink: string = '#2B2622';
  /** 次级文字 */
  muted: string = '#7A7168';
  /** 朱砂：只用于「当前章 / 选中」这一类强调 */
  seal: string = '#B4472E';
  /** 是否深色（决定状态栏文字颜色） */
  dark: boolean = false;
}

const PAPER: Palette = {
  bg: '#F7F3EC',
  card: '#FFFDF9',
  sub: '#F1EBE0',
  border: '#E3DACA',
  ink: '#2B2622',
  muted: '#7A7168',
  seal: '#B4472E',
  dark: false
};

const NIGHT: Palette = {
  bg: '#16130F',
  card: '#1E1A15',
  sub: '#272218',
  border: '#332C23',
  ink: '#EFE8DC',
  muted: '#A79E90',
  seal: '#D4614A',
  dark: true
};

const GREEN: Palette = {
  bg: '#EDF3E9',
  card: '#F7FAF4',
  sub: '#E3EBDD',
  border: '#CFDCC6',
  ink: '#22301F',
  muted: '#66735E',
  seal: '#B4472E',
  dark: false
};

export class Theme {
  /** 写 AppStorage，页面用 @StorageProp('skin') 跟随 */
  static apply(skin: string): void {
    AppStorage.setOrCreate<string>('skin', Theme.normalize(skin));
  }

  static normalize(skin: string): string {
    if (skin === 'night' || skin === 'green' || skin === 'paper') {
      return skin;
    }
    return 'paper';
  }

  static of(skin: string): Palette {
    const s = Theme.normalize(skin);
    if (s === 'night') {
      return NIGHT;
    }
    if (s === 'green') {
      return GREEN;
    }
    return PAPER;
  }

  static label(skin: string): string {
    const s = Theme.normalize(skin);
    if (s === 'night') {
      return '夜间';
    }
    if (s === 'green') {
      return '护眼';
    }
    return '纸色';
  }
}
