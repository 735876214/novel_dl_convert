<script setup lang="ts">
import Card from '@/components/ui/Card.vue'
import SettingsUnsupportedCard from '@/views/settings/SettingsUnsupportedCard.vue'
import {
  AUTHOR_COVER_SHAPE_OPTIONS,
  AUTHOR_COVER_SIZE_RANGE,
  CARD_INFO_MODE_OPTIONS,
  CARD_PRIMARY_LABEL_OPTIONS,
  CARD_SECONDARY_LABEL_OPTIONS,
  COLLAPSED_COVER_OPTIONS,
  COVER_SIZE_RANGE,
  GRID_GAP_RANGE,
  useDisplayPrefsStore,
} from '@/stores/displayPrefs'

/**
 * YOU → Display → Layout（`/settings/appearance/layout`）
 *
 * 上游这一页分 4 组：LIBRARY GRID LAYOUT / CARD INFO / SERIES DISPLAY / AUTHOR GRID /
 * LIST AND TABLE VIEWS。本项目按自身的实体情况落地（详由见 `stores/displayPrefs` 头注）：
 *
 * - 封面尺寸 / 网格间距：真的驱动书架网格（`auto-fill` 列宽 + 间距）。
 * - 卡片信息位置：真作用于书架网格卡（悬停浮层 / 封面下方 / 不显示）。
 * - 卡片主 / 次标签（第 51 期）：真作用于书架网格卡的两行文字（默认书名 + 作者）。
 * - 折叠系列封面形态（第 51 期）：真作用于书架折叠行（默认首册；堆叠 / 马赛克为多封面组合）。
 * - 作者封面尺寸 / 形状：真作用于作者页。
 * - 斑马纹：真作用于书架表格视图。
 *
 * 未支持的项集中在页尾对照卡里，**不造只动不响的控件**（防回归要点 5）。
 */
const prefs = useDisplayPrefsStore()

/** range 的 @input 取值：字符串 → 数字 */
function num(e: Event): number {
  return Number((e.target as HTMLInputElement).value)
}
</script>

<template>
  <div>
    <div class="mb-4 flex flex-wrap items-baseline gap-2">
      <h2 class="text-[14px] font-semibold text-foreground">布局</h2>
      <span class="font-mono text-[11.5px] text-muted-foreground">Layout</span>
    </div>

    <!-- LIBRARY GRID LAYOUT -->
    <div class="mb-1.5 text-[11.5px] font-semibold tracking-wider text-muted-foreground uppercase">
      书库网格
    </div>
    <Card padding="none" class="mb-5">
      <div class="border-b border-border px-4 py-3.5 md:flex md:items-center md:gap-4">
        <div class="min-w-0 flex-1">
          <div class="text-[13px] font-medium text-foreground">封面尺寸</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">
            书架网格里封面的最小宽度 —— 书架按它自动决定每行放几本，屏幕越宽放得越多
          </div>
        </div>
        <div class="mt-3 w-full md:mt-0 md:w-72">
          <div class="mb-1.5 flex items-center justify-between gap-3">
            <span class="text-xs text-muted-foreground">封面尺寸</span>
            <span class="text-xs font-medium text-foreground tabular-nums">
              {{ prefs.prefs.coverSize }}px
            </span>
          </div>
          <input
            type="range"
            :min="COVER_SIZE_RANGE.min"
            :max="COVER_SIZE_RANGE.max"
            :step="COVER_SIZE_RANGE.step"
            :value="prefs.prefs.coverSize"
            class="w-full cursor-pointer accent-primary"
            aria-label="封面尺寸"
            @input="prefs.patch({ coverSize: num($event) })"
          />
        </div>
      </div>

      <div class="px-4 py-3.5 md:flex md:items-center md:gap-4">
        <div class="min-w-0 flex-1">
          <div class="text-[13px] font-medium text-foreground">网格间距</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">
            书架网格里封面之间的横纵留白，作者页的行距也跟着它走
          </div>
        </div>
        <div class="mt-3 w-full md:mt-0 md:w-72">
          <div class="mb-1.5 flex items-center justify-between gap-3">
            <span class="text-xs text-muted-foreground">网格间距</span>
            <span class="text-xs font-medium text-foreground tabular-nums">
              {{ prefs.prefs.gridGap }}px
            </span>
          </div>
          <input
            type="range"
            :min="GRID_GAP_RANGE.min"
            :max="GRID_GAP_RANGE.max"
            :step="GRID_GAP_RANGE.step"
            :value="prefs.prefs.gridGap"
            class="w-full cursor-pointer accent-primary"
            aria-label="网格间距"
            @input="prefs.patch({ gridGap: num($event) })"
          />
        </div>
      </div>
    </Card>

    <!-- CARD INFO -->
    <div class="mb-1.5 text-[11.5px] font-semibold tracking-wider text-muted-foreground uppercase">
      卡片信息
    </div>
    <Card padding="none" class="mb-5">
      <div class="px-4 py-3.5 md:flex md:items-center md:gap-4">
        <div class="min-w-0 flex-1">
          <div class="text-[13px] font-medium text-foreground">信息位置</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">
            书名与作者放在哪。显示**多少**由书架页的「信息密度」控制，两者互不影响
          </div>
        </div>
        <div
          class="mt-3 grid w-full gap-1 rounded-lg border border-border bg-muted/50 p-1 sm:w-auto sm:grid-cols-3 md:mt-0"
        >
          <button
            v-for="o in CARD_INFO_MODE_OPTIONS"
            :key="o.value"
            type="button"
            class="flex min-w-0 cursor-pointer items-center gap-1.5 rounded-md px-3 py-1.5 text-left text-xs font-medium transition-colors"
            :class="prefs.prefs.cardInfoMode === o.value
              ? 'bg-card text-foreground shadow-xs'
              : 'text-muted-foreground hover:text-foreground'"
            @click="prefs.patch({ cardInfoMode: o.value })"
          >
            <span class="min-w-0">
              <span class="block truncate">{{ o.label }}</span>
              <span class="block truncate text-[10px] font-normal opacity-75">{{ o.hint }}</span>
            </span>
          </button>
        </div>
      </div>
    </Card>

    <!-- AUTHOR GRID -->
    <div class="mb-1.5 text-[11.5px] font-semibold tracking-wider text-muted-foreground uppercase">
      作者网格
    </div>
    <Card padding="none" class="mb-5">
      <div class="border-b border-border px-4 py-3.5 md:flex md:items-center md:gap-4">
        <div class="min-w-0 flex-1">
          <div class="text-[13px] font-medium text-foreground">封面尺寸</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">
            作者页每张封面的最小宽度（与书库网格各调各的）
          </div>
        </div>
        <div class="mt-3 w-full md:mt-0 md:w-72">
          <div class="mb-1.5 flex items-center justify-between gap-3">
            <span class="text-xs text-muted-foreground">封面尺寸</span>
            <span class="text-xs font-medium text-foreground tabular-nums">
              {{ prefs.prefs.authorCoverSize }}px
            </span>
          </div>
          <input
            type="range"
            :min="AUTHOR_COVER_SIZE_RANGE.min"
            :max="AUTHOR_COVER_SIZE_RANGE.max"
            :step="AUTHOR_COVER_SIZE_RANGE.step"
            :value="prefs.prefs.authorCoverSize"
            class="w-full cursor-pointer accent-primary"
            aria-label="作者封面尺寸"
            @input="prefs.patch({ authorCoverSize: num($event) })"
          />
        </div>
      </div>

      <div class="px-4 py-3.5 md:flex md:items-center md:gap-4">
        <div class="min-w-0 flex-1">
          <div class="text-[13px] font-medium text-foreground">封面形状</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">
            有抓到头像的作者按此裁剪；没头像的作者用书封占位，也跟着这个形状
          </div>
        </div>
        <div
          class="mt-3 grid w-full gap-1 rounded-lg border border-border bg-muted/50 p-1 sm:w-auto sm:grid-cols-2 md:mt-0"
        >
          <button
            v-for="o in AUTHOR_COVER_SHAPE_OPTIONS"
            :key="o.value"
            type="button"
            class="flex min-w-0 cursor-pointer items-center gap-1.5 rounded-md px-3 py-1.5 text-left text-xs font-medium transition-colors"
            :class="prefs.prefs.authorCoverShape === o.value
              ? 'bg-card text-foreground shadow-xs'
              : 'text-muted-foreground hover:text-foreground'"
            @click="prefs.patch({ authorCoverShape: o.value })"
          >
            <span class="min-w-0">
              <span class="block truncate">{{ o.label }}</span>
              <span class="block truncate text-[10px] font-normal opacity-75">{{ o.hint }}</span>
            </span>
          </button>
        </div>
      </div>
    </Card>

    <!-- CARD INFO（第 51 期补充：主 / 次标签）与 SERIES DISPLAY（折叠封面形态） -->
    <div class="mb-1.5 text-[11.5px] font-semibold tracking-wider text-muted-foreground uppercase">
      系列显示
    </div>
    <Card padding="none" class="mb-5">
      <div class="border-b border-border px-4 py-3.5 md:flex md:items-center md:gap-4">
        <div class="min-w-0 flex-1">
          <div class="text-[13px] font-medium text-foreground">主标签</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">
            卡片第一行显示什么。取不到值的书会回退成书名，不会留空行
          </div>
        </div>
        <div class="mt-3 flex flex-wrap gap-1.5 md:mt-0">
          <button
            v-for="o in CARD_PRIMARY_LABEL_OPTIONS"
            :key="o.value"
            type="button"
            class="cursor-pointer rounded-full px-3 py-1 text-[12px] font-medium transition-colors"
            :class="prefs.prefs.primaryLabel === o.value
              ? 'bg-primary text-primary-foreground'
              : 'bg-muted text-muted-foreground hover:text-foreground'"
            @click="prefs.patch({ primaryLabel: o.value })"
          >
            {{ o.label }}
          </button>
        </div>
      </div>

      <div class="border-b border-border px-4 py-3.5 md:flex md:items-center md:gap-4">
        <div class="min-w-0 flex-1">
          <div class="text-[13px] font-medium text-foreground">次标签</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">
            卡片第二行显示什么。取不到值会回退成作者，作者也缺则显示「未知作者」
          </div>
        </div>
        <div class="mt-3 flex flex-wrap gap-1.5 md:mt-0">
          <button
            v-for="o in CARD_SECONDARY_LABEL_OPTIONS"
            :key="o.value"
            type="button"
            class="cursor-pointer rounded-full px-3 py-1 text-[12px] font-medium transition-colors"
            :class="prefs.prefs.secondaryLabel === o.value
              ? 'bg-primary text-primary-foreground'
              : 'bg-muted text-muted-foreground hover:text-foreground'"
            @click="prefs.patch({ secondaryLabel: o.value })"
          >
            {{ o.label }}
          </button>
        </div>
      </div>

      <div class="px-4 py-3.5">
        <div class="text-[13px] font-medium text-foreground">折叠系列的封面形态</div>
        <div class="mt-0.5 text-[11.5px] text-muted-foreground">
          书架折叠同系列时用哪张封面；「堆叠」「马赛克」用系列内前几册拼合（纯 CSS，不额外请求）
        </div>
        <div class="mt-2.5 flex flex-wrap gap-1.5">
          <button
            v-for="o in COLLAPSED_COVER_OPTIONS"
            :key="o.value"
            type="button"
            class="cursor-pointer rounded-full px-3 py-1 text-[12px] font-medium transition-colors"
            :class="prefs.prefs.collapsedCover === o.value
              ? 'bg-primary text-primary-foreground'
              : 'bg-muted text-muted-foreground hover:text-foreground'"
            @click="prefs.patch({ collapsedCover: o.value })"
          >
            {{ o.label }}
          </button>
        </div>
        <div class="mt-2 text-[11.5px] text-muted-foreground">
          {{ COLLAPSED_COVER_OPTIONS.find((o) => o.value === prefs.prefs.collapsedCover)?.hint }}
        </div>
      </div>
    </Card>

    <!-- LIST AND TABLE VIEWS -->
    <div class="mb-1.5 text-[11.5px] font-semibold tracking-wider text-muted-foreground uppercase">
      列表与表格
    </div>
    <Card padding="none">
      <div class="flex items-center gap-4 px-4 py-3.5">
        <div class="min-w-0 flex-1">
          <div class="text-[13px] font-medium text-foreground">表格隔行底色</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">
            书架切到表格视图时，偶数行铺一层浅底色，横向读数不串行
          </div>
        </div>
        <input
          type="checkbox"
          class="h-4 w-4 shrink-0 cursor-pointer accent-primary"
          :checked="prefs.prefs.zebraStriping"
          aria-label="表格隔行底色"
          @change="prefs.patch({ zebraStriping: ($event.target as HTMLInputElement).checked })"
        />
      </div>
    </Card>

    <p class="mt-3 text-[11.5px] leading-relaxed text-muted-foreground">
      这几项属于「外观」，跟着账号在设备之间同步（与主题、点缀色同一份载荷）——改完书架页与
      作者页立即生效，不用刷新。
    </p>

    <SettingsUnsupportedCard
      label="Layout"
      :groups="['LIBRARY GRID LAYOUT']"
      :items="[
        '封面尺寸行为（全部同步 / 各视图独立）—— 本项目书架只有一套网格，没有第二个视图可供联动，做出来就是个空开关。',
        '方形封面尺寸与方形网格间距 —— 本项目三种视图一律用竖版 3:4 封面，没有方形缩略图这一实体。',
      ]"
      note="上面两项是上游有、本项目没有对应实体（主动不做），不制造只动不响的控件。卡片主 / 次标签与折叠系列封面五形态已于第 51 期补齐。"
    />
  </div>
</template>
