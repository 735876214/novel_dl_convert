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
