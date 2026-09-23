<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { useRouter } from 'vue-router'

import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import Icon from '@/components/ui/Icon.vue'
import { useLibraryStore } from '@/stores/library'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ 'update:open': [boolean] }>()

const library = useLibraryStore()
const router = useRouter()

/**
 * 引导词**跟着真实状态走**（第 38 期）。
 *
 * 原来第一步张口就是「你的书库按格式自动归库：电子书、漫画、有声书各自成列」——
 * 可第 37 期起全新部署**一个书库都没有**，此时这句话描述的是一套还不存在的东西，
 * 用户看完仍然不知道第一步该干什么（实测：首屏全站没有一处说「先建书库」）。
 *
 * 所以 0 库时把第一步换成建库指引并给出口；有库时保持原样 —— 引导不许对用户说假话。
 */
interface TourStep {
  icon: string
  title: string
  body: string
  /** 该步自带的可选出口；没有就只显示正文 */
  cta?: { label: string; to: string }
}

const STEPS = computed<TourStep[]>(() => {
  const first = library.hasNoLibraries
    ? {
        icon: 'plus',
        title: '先建一个书库',
        body: '书要落进书库才有位置。新建一个书库并指定它的来源目录，之后的下载、上传与投递才有地方可放 —— 在此之前它们会被拒收。',
        cta: { label: '新建书库', to: '/settings/libraries?new=1' },
      }
    : {
        icon: 'library',
        title: '书架',
        body: '你的书库按格式自动归库：电子书、漫画、有声书各自成列。支持拖拽投递与「设置 → 书库管理」做跨库整理、按子目录或关键词自动归库。',
      }
  return [
    first,
    {
      icon: 'book',
      title: '阅读器',
      body: '打开任意一本书即可阅读。EPUB 可调主题、字体与排版；PDF 与漫画支持缩放、翻页与阅读方向；有声书可调速、跳进退与睡眠定时。',
    },
    {
      icon: 'settings',
      title: '设置同步',
      body: '外观与阅读偏好可存成「模式」供多设备套用，每台设备也能各用各的。改动即时生效并自动同步——离线照常可用，恢复后重推。',
    },
  ]
})

const i = ref(0)
const step = computed(() => STEPS.value[i.value])
const last = computed(() => i.value === STEPS.value.length - 1)

/** 步骤自带的出口（目前只有 0 库时的「新建书库」）：点了就关掉引导再去，不叠两层浮层 */
function goCta(to: string): void {
  close()
  void router.push(to)
}

function close(): void {
  emit('update:open', false)
  i.value = 0
}
function next(): void {
  if (last.value) close()
  else i.value += 1
}
function prev(): void {
  if (i.value > 0) i.value -= 1
}

function onKey(e: KeyboardEvent): void {
  if (e.key === 'Escape' && props.open) close()
}
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))

// 每次打开重置到第一步
watch(
  () => props.open,
  (v) => {
    if (v) i.value = 0
  },
)
</script>

<template>
  <div
    v-if="open"
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
    @click.self="close"
  >
    <Card class="w-full max-w-md overflow-hidden">
      <div class="flex items-center gap-3 px-5 pt-5">
        <span class="grid h-9 w-9 place-items-center rounded-full bg-primary/10 text-primary">
          <Icon :name="step.icon" class="h-4 w-4" />
        </span>
        <div class="min-w-0 flex-1">
          <div class="text-[13px] font-semibold text-foreground">{{ step.title }}</div>
          <div class="text-[11px] text-muted-foreground">新手引导 · {{ i + 1 }} / {{ STEPS.length }}</div>
        </div>
        <button
          type="button"
          class="cursor-pointer text-muted-foreground transition-colors hover:text-foreground"
          aria-label="关闭"
          @click="close"
        >
          <Icon name="x" class="h-4 w-4" />
        </button>
      </div>

      <p class="px-5 py-4 text-[12.5px] leading-relaxed text-muted-foreground">{{ step.body }}</p>

      <!-- 步骤自带的出口（0 库时的「新建书库」）：引导的落点是**做那件事**，
           不是让用户记住一句话然后自己找入口 -->
      <div v-if="step.cta" class="px-5 pb-4">
        <Button size="sm" variant="primary" @click="goCta(step.cta.to)">{{ step.cta.label }}</Button>
      </div>

      <div class="flex items-center gap-2 border-t border-border px-5 py-3">
        <Button size="sm" variant="ghost" @click="close">跳过</Button>
        <div class="flex flex-1 justify-center gap-1.5">
          <span
            v-for="(s, n) in STEPS"
            :key="s.title"
            class="h-1.5 w-1.5 rounded-full transition-colors"
            :class="n === i ? 'bg-primary' : 'bg-border'"
          />
        </div>
        <Button v-if="i > 0" size="sm" variant="ghost" @click="prev">上一步</Button>
        <Button size="sm" variant="primary" @click="next">{{ last ? '完成' : '下一步' }}</Button>
      </div>
    </Card>
  </div>
</template>
