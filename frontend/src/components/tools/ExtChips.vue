<script setup lang="ts">
/**
 * 「允许的格式」选择器（第 40 期）—— 新建向导与编辑弹窗**共用这一个**。
 *
 * ## 为什么必须共用
 *
 * 这里的核心语义只有一条，但它很容易在第二份拷贝里走散：
 *
 * > **空列表 = 继承库类型默认**，不是「一个格式都不收」。
 *
 * 后端把库表列 `allowed_exts` 的 `''` 读作「没设过」（SQLite 的
 * `ALTER TABLE ADD COLUMN` 只接受常量默认值，没法把「按类型推导」写成列默认），
 * 读时回落到 `library._exts_for_type(type)`。所以「全不勾」这个动作在数据层
 * 表达不出「空集合」，前端就**不许**把它呈现成「空集合」的样子 ——
 * 否则用户以为自己关掉了全部格式，实际是回到了默认，这是一个会持续咬人的误解。
 *
 * 因此组件把「勾选态」拆成两个来源：
 *   · `touched = false` ⇒ 勾选集 = `defaults`（跟着类型走，换类型自动变）
 *   · `touched = true`  ⇒ 勾选集 = `modelValue`（用户自己那个集合，勾空也照实显示为空）
 * 而**发出去的永远只有 `modelValue`** —— 没动过就是 `[]` = 继承。
 *
 * ## 为什么不做「一个格式都不收」的库
 *
 * 那会是个死库：文件进不来、也没人看得见为什么。真要不收东西，正确做法是不建这个库。
 */
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    /** 用户显式设的格式集；空数组 = 继承类型默认 */
    modelValue: string[]
    /** 用户动过勾选没有（false ⇒ 显示 `defaults`） */
    touched: boolean
    /** 当前库类型的默认白名单（来自 `GET /api/libraries` 的 `types[].exts`） */
    defaults: string[]
    /** 类型的中文名，只用于提示文案 */
    typeLabel?: string
  }>(),
  { typeLabel: '' },
)

const emit = defineEmits<{
  (e: 'update:modelValue', v: string[]): void
  (e: 'update:touched', v: boolean): void
}>()

const checked = computed(() => (props.touched ? props.modelValue : props.defaults))

function toggle(ext: string): void {
  const next = new Set(checked.value)
  if (next.has(ext)) next.delete(ext)
  else next.add(ext)
  // ⚠️ 顺序不能反：先置 `touched` 再发 `modelValue`，否则父组件的 `checked`
  //    在两次 emit 之间会拿旧 `touched` + 新 `modelValue` 算出中间态并闪一下。
  emit('update:touched', true)
  emit('update:modelValue', [...next])
}

/** 手动恢复继承（等价于「没设过」） */
function reset(): void {
  emit('update:touched', false)
  emit('update:modelValue', [])
}
</script>

<template>
  <div>
    <div class="flex flex-wrap gap-1">
      <button
        v-for="e in defaults"
        :key="e"
        type="button"
        :data-test="`ext-chip-${e}`"
        :aria-pressed="checked.includes(e)"
        class="rounded-md border px-2 py-0.5 text-[11.5px] transition-colors"
        :class="
          checked.includes(e)
            ? 'border-primary bg-primary/10 text-foreground'
            : 'border-border text-muted-foreground hover:text-foreground'
        "
        @click="toggle(e)"
      >
        {{ e }}
      </button>
    </div>

    <div class="mt-1 text-[11px] text-muted-foreground">
      <template v-if="!touched">
        当前是{{ typeLabel ? `「${typeLabel}」` : '' }}库的默认格式集（未自定义）。
      </template>
      <template v-else-if="modelValue.length === 0">
        ⚠️ 一个都不勾 = <strong class="text-foreground">继承类型默认</strong>，不是「什么格式都不收」——
        <button type="button" class="underline hover:text-foreground" @click="reset">
          点此恢复继承
        </button>
      </template>
      <template v-else>已自定义 {{ modelValue.length }} 种格式。</template>
    </div>
  </div>
</template>
