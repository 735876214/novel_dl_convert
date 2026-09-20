<script setup lang="ts">
import VChart from 'vue-echarts'

/**
 * ECharts 挂载壳：只管实例、尺寸与渲染器，option 由各图自己算。
 *
 * 抽这一层的理由：本期 10 张图若各写一遍 `<VChart>`，`init-options` 与尺寸类串
 * 就要抄 10 遍，抄漏一处就是一张不渲染的图。
 *
 * `renderer: 'svg'` **必须显式给**：ECharts 的默认渲染器是 canvas，而本项目
 * （照搬上游）只注册了 SVGRenderer，不指定就会报「未导入 canvas 渲染器」。
 * 选 SVG 的原因见 `lib/charts.ts` 文件头。
 *
 * 底下的 `:deep(svg)` 覆盖见 `<style>` 块里的注释 —— 那是本项目特有的一条坑，
 * 上游没有（上游的 base 层没有元素级 svg 尺寸规则）。
 */
withDefaults(
  defineProps<{
    /** ECharts option，一般来自各图的 computed */
    option: Record<string, unknown>
    /** 关掉自适应（少数需要固定尺寸的场景） */
    autoresize?: boolean
  }>(),
  { autoresize: true },
)
</script>

<template>
  <VChart
    class="h-full w-full"
    :option="option"
    :init-options="{ renderer: 'svg' }"
    :autoresize="autoresize"
  />
</template>

<style scoped>
/* ⚠️ 本项目特有的一坑（上游没有）：`assets/main.css:77` 有一条元素级基线规则
   `svg { width: 16px; height: 16px; flex-shrink: 0 }`，是给全站图标用的。
   ECharts 渲染出的 `<svg>` 带的是 width/height **属性**（presentation attribute），
   而**属性优先级低于任何 CSS 规则** ⇒ 整张图被压成 16×16 裁掉，症状是「卡片一片
   空白、DOM 里却躺着完整的 path 与 text」。这里按 class 优先级（编译后为
   `[data-v-x] svg`）把它拉回容器尺寸。
   改 `main.css` 那条规则的写法风险更大 —— 全站 30+ 处图标依赖它，故只在此局部收口。 */
:deep(svg) {
  width: 100%;
  height: 100%;
}
</style>
