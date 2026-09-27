<script setup lang="ts">
/**
 * 星级评分（0–5）。抽出前全仓有三份各写一遍的实现：`ReadingRecord.vue` 的可编辑版、
 * 详情页 hero 的只读版、书卡角标的 `'★'.repeat(n)`（第 63 期归并前两者）。
 *
 * `readonly` 时**不渲染 button**，只渲染 span —— 只读场景下键盘用户不该 Tab 进一串
 * 点不动的星星。清零由调用方给独立入口（与归并前的 ReadingRecord 一致：那里是一个
 * 「清除」按钮，不是「再点一次当前星」）。
 */
const props = withDefaults(
  defineProps<{
    modelValue: number
    readonly?: boolean
    size?: 'sm' | 'md'
  }>(),
  { readonly: false, size: 'md' },
)

const emit = defineEmits<{ 'update:modelValue': [number] }>()

const SIZE: Record<string, string> = {
  sm: 'text-[13px]',
  md: 'text-[18px]',
}

function pick(n: number): void {
  if (props.readonly) return
  emit('update:modelValue', n)
}
</script>

<template>
  <div class="inline-flex items-center gap-0.5 leading-none" :class="SIZE[size]">
    <component
      :is="readonly ? 'span' : 'button'"
      v-for="n in 5"
      :key="n"
      :type="readonly ? undefined : 'button'"
      :aria-label="`${n} 星`"
      class="leading-none"
      :class="[
        n <= modelValue ? 'text-warning' : 'text-muted-foreground/30',
        readonly ? 'cursor-default' : 'cursor-pointer transition-transform hover:scale-110',
      ]"
      @click="pick(n)"
    >
      ★
    </component>
  </div>
</template>
