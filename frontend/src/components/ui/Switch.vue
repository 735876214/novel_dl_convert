<script setup lang="ts">
/**
 * 开关（胶囊）—— **全站唯一实现**（第 70 期）。
 *
 * 在此之前：同一颗小胶囊在 8 个文件里各写了一份（`h-[18px] w-8` + 14px 滑块），另外还有
 * 一处写成了大胶囊（`h-5 w-9` + `transition-[left]` + `shadow-xs`）。改一次配色要改九处，
 * 而「漏掉一处」在界面上几乎看不出来 —— 只有那一个开关颜色不对。
 *
 * 为什么用 `<button role="switch">` 而不是 `input[type=checkbox]`：
 *   · 空格 / 回车切换由原生按钮保证，不必再自己补键盘处理；
 *   · 复选框要做成胶囊得 `appearance: none` 再手写全部视觉，焦点环与禁用态反而更难统一。
 *
 * 配色（第 75 期口径）：
 *   · **轨道**随主题走 —— 开 `--primary` / 关 `--muted`；这两色深浅两套 token 不同，
 *     写死必然在其中一套里糊掉。
 *   · ⚠️ **圆点（滑块）是刻意的例外：固定白色**（用户口径「圆点要与主题色不一致，默认白色」）。
 *     白色圆点在深色轨道上对比极强，浅色轨道上偏弱 ⇒ 再补一圈**半透明黑细边**
 *     `border-black/15` 勾出轮廓。此前用 `bg-card`，浅色主题下与 `--muted` 只差 ~2% 明度，
 *     同样要靠这道边才看得清 —— 换成白色后这道边更不能省。
 *   · 除「圆点白色 + 半透明黑细边」外，本组件**不再有第二处写死色值**。
 * 焦点环由全局 `:focus-visible`（`assets/main.css`）统一提供，这里**不另写一套**。
 */
const props = withDefaults(
  defineProps<{
    /** 开 / 关（配合 `v-model` 使用） */
    modelValue: boolean
    disabled?: boolean
    /** 悬停提示（如「启用」/「停用」）。不传则不加 `title` */
    title?: string
    /** 读屏名字。外层已有可见文字标签时可以不传 */
    ariaLabel?: string
  }>(),
  { disabled: false, title: '', ariaLabel: '' },
)

const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()
</script>

<template>
  <button
    type="button"
    role="switch"
    :aria-checked="modelValue"
    :aria-label="ariaLabel || undefined"
    :title="title || undefined"
    :disabled="disabled"
    class="relative h-[18px] w-8 shrink-0 cursor-pointer rounded-full transition-colors duration-200 disabled:cursor-not-allowed disabled:opacity-40"
    :class="modelValue ? 'bg-primary' : 'bg-muted'"
    @click="emit('update:modelValue', !props.modelValue)"
  >
    <span
      class="pointer-events-none absolute top-[2px] left-0 h-[14px] w-[14px] rounded-full border border-black/15 bg-white shadow-xs transition-transform duration-200"
      :class="modelValue ? 'translate-x-[16px]' : 'translate-x-[2px]'"
    />
  </button>
</template>
