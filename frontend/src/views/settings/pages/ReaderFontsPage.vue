<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import { customFontFamily } from '@/lib/fonts'
import { useFontsStore } from '@/stores/fonts'
import { useUiStore } from '@/stores/ui'
import SettingsUnsupportedCard from '@/views/settings/SettingsUnsupportedCard.vue'

/**
 * 字体管理。一个组件两种形态：
 *   · `reader`（YOU → Reader → Fonts）：从「阅读时能选哪些字体」的角度
 *   · `server`（SERVER → Server Fonts）：从「服务端装了哪些字体」的角度
 *
 * 本项目是单用户部署，上游的「每用户字体」与「服务端字体」是**同一份库**，
 * 因此两页读写同一组接口，只是表述与上限口径不同（这里统一按服务端口径）。
 */
const props = withDefaults(defineProps<{ variant?: 'reader' | 'server' }>(), { variant: 'reader' })

const fonts = useFontsStore()
const ui = useUiStore()
const fileInput = ref<HTMLInputElement | null>(null)
const busy = ref(false)

onMounted(() => fonts.load())

function pick(): void {
  fileInput.value?.click()
}

async function onFiles(e: Event): Promise<void> {
  const input = e.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  input.value = '' // 清空后才能重复选同一个文件
  if (!files.length) return
  busy.value = true
  let done = 0
  const errs: string[] = []
  for (const f of files) {
    try {
      await fonts.upload(f)
      done += 1
    } catch (err) {
      errs.push(`${f.name}：${err instanceof Error ? err.message : '上传失败'}`)
    }
  }
  busy.value = false
  if (done) ui.toast(`已上传 ${done} 个字体`)
  if (errs.length) ui.toast(errs[0])
}

async function remove(id: string, name: string): Promise<void> {
  if (!window.confirm(`删除字体「${name}」？使用它的阅读偏好会回落内置字体。`)) return
  try {
    await fonts.remove(id)
    ui.toast('已删除')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '删除失败')
  }
}

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`
}

const MAX_MB = () => Math.round(fonts.maxBytes / 1024 / 1024)

// ---------------- 行内预览：用真实字体文件渲染样例文本 ----------------
/** 选中的字体 id；空串时回落到列表第一条（避免删除后预览区空掉） */
const selectedId = ref('')
const previewSize = ref(20)
const RESET_SIZE = 20
/** 预览目标：选中项优先，否则第一条；一条都没有时为 null */
const current = computed(
  () => fonts.items.find((f) => f.id === selectedId.value) ?? fonts.items[0] ?? null,
)
/** 字体按族分组：同一 family_key 的变体（Regular / Bold…）聚到一起，族名只显示一次。
 *  解析不出族名（family_key 为空）的文件各自成组（单条）。 */
const groups = computed(() => {
  const map = new Map<string, typeof fonts.items>()
  for (const f of fonts.items) {
    const key = f.family_key || `__${f.id}`
    if (!map.has(key)) map.set(key, [])
    map.get(key)!.push(f)
  }
  return [...map.entries()].map(([key, items]) => ({
    key,
    name: items[0].name,
    grouped: items.length > 1 && !!items[0].family_key,
    items,
  }))
})
/** 样例文本覆盖中文/拉丁/数字/标点，便于判断字形的完整度 */
const SAMPLE =
  '永和九年，岁在癸丑，暮春之初，会于会稽山阴之兰亭。' +
  'The quick brown fox jumps over the lazy dog. 0123456789 !?;:「」（）、。'
</script>

<template>
  <div>
    <div class="mb-3 flex flex-wrap items-baseline gap-2">
      <h2 class="text-[14px] font-semibold text-foreground">{{ props.variant === 'server' ? '服务端字体' : 'Fonts' }}</h2>
      <span class="font-mono text-[11.5px] text-muted-foreground">{{ props.variant === 'server' ? 'Server Fonts' : 'Fonts' }}</span>
      <span class="text-[11.5px] text-muted-foreground">
        {{ props.variant === 'server'
          ? '装在服务器上的字体，这台机器上的所有阅读器都能用'
          : '阅读时可选用的字体' }}
      </span>
      <Button size="sm" class="ml-auto" :disabled="busy" @click="pick">
        {{ busy ? '上传中…' : '上传字体' }}
      </Button>
      <input
        ref="fileInput"
        type="file"
        multiple
        accept=".ttf,.otf,.woff,.woff2"
        class="hidden"
        @change="onFiles"
      >
    </div>

    <Card padding="none">
      <div class="flex items-center justify-between border-b border-border px-4 py-3">
        <span class="text-[13px] font-medium text-foreground">
          已有字体 <span class="tabular-nums text-muted-foreground">{{ fonts.items.length }}</span>
          <span class="text-[11.5px] text-muted-foreground">/ {{ fonts.maxCount }}</span>
        </span>
        <span class="text-[11.5px] text-muted-foreground">
          TTF / OTF / WOFF / WOFF2 · 单个 ≤ {{ MAX_MB() }} MB
        </span>
      </div>

      <p v-if="fonts.loading && !fonts.items.length" class="px-4 py-6 text-center text-[12.5px] text-muted-foreground">
        加载中…
      </p>
      <p v-else-if="fonts.error" class="px-4 py-6 text-center text-[12.5px] text-destructive">{{ fonts.error }}</p>
      <p v-else-if="!fonts.items.length" class="px-4 py-8 text-center text-[12.5px] text-muted-foreground">
        还没有字体。上传后即可在阅读器的「字体」里选用。
      </p>

      <template v-for="g in groups" :key="g.key">
        <!-- 同族多变体（Regular / Bold / Italic…）：族名只显示一次，下面列出每个变体文件 -->
        <div v-if="g.grouped" class="border-b border-border/60 px-4 py-2.5">
          <div class="flex items-center gap-2">
            <span
              class="truncate text-[13px] font-medium text-foreground"
              :style="{ fontFamily: `'NF-${g.items[0].family_key}', serif` }"
            >{{ g.name }}</span>
            <span class="shrink-0 text-[10.5px] text-muted-foreground">{{ g.items.length }} 变体</span>
          </div>
          <div
            v-for="f in g.items"
            :key="f.id"
            role="button"
            tabindex="0"
            class="mt-1.5 flex cursor-pointer items-center gap-3 rounded-md px-2 py-1.5 transition-colors"
            :class="current?.id === f.id ? 'bg-muted/60' : 'hover:bg-muted/40'"
            @click="selectedId = f.id"
            @keydown.enter="selectedId = f.id"
          >
            <div class="min-w-0 flex-1">
              <div class="truncate text-[12.5px] text-foreground">{{ f.style || '（默认样式）' }}</div>
              <div class="truncate text-[11px] text-muted-foreground">{{ f.format.toUpperCase() }} · {{ fmtSize(f.size) }}</div>
            </div>
            <button
              type="button"
              class="shrink-0 cursor-pointer text-[12px] text-muted-foreground transition-colors hover:text-destructive"
              @click.stop="remove(f.id, f.name)"
            >
              删除
            </button>
          </div>
        </div>
        <!-- 单文件（无变体 / 未解析出族名）：保持改造前的一行卡片，按文件名显示 -->
        <div
          v-else
          role="button"
          tabindex="0"
          class="flex cursor-pointer items-center gap-3 border-b border-border/60 px-4 py-2.5 transition-colors last:border-b-0 hover:bg-muted/40"
          :class="current?.id === g.items[0].id ? 'bg-muted/60' : ''"
          @click="selectedId = g.items[0].id"
          @keydown.enter="selectedId = g.items[0].id"
        >
          <div class="min-w-0 flex-1">
            <div class="truncate text-[13px] text-foreground" :style="{ fontFamily: `'NF-${g.items[0].family_key || g.items[0].id}', serif` }">
              {{ g.items[0].name }}
            </div>
            <div class="truncate text-[11px] text-muted-foreground">
              {{ g.items[0].style }} · {{ g.items[0].format.toUpperCase() }} · {{ fmtSize(g.items[0].size) }}
            </div>
          </div>
          <button
            type="button"
            class="shrink-0 cursor-pointer text-[12px] text-muted-foreground transition-colors hover:text-destructive"
            @click.stop="remove(g.items[0].id, g.items[0].name)"
          >
            删除
          </button>
        </div>
      </template>
    </Card>

    <!-- 行内预览：用 store 已注入的 @font-face 实时渲染样例文本（零额外请求） -->
    <Card class="mt-4" padding="none">
      <div class="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
        <span class="text-[13px] font-medium text-foreground">字体预览</span>
        <span class="text-[11.5px] text-muted-foreground">
          {{ current ? `用「${current.name}」渲染` : '上传字体后可预览' }}
        </span>
        <div class="ml-auto flex items-center gap-2">
          <label class="flex items-center gap-2 text-[11.5px] text-muted-foreground">
            字号
            <input
              v-model.number="previewSize"
              type="range"
              min="14"
              max="40"
              step="1"
              aria-label="预览字号"
              class="h-1 w-28 cursor-pointer accent-primary"
            >
            <span class="w-9 text-right tabular-nums">{{ previewSize }}px</span>
          </label>
          <Button
            size="sm"
            variant="ghost"
            :disabled="previewSize === RESET_SIZE"
            @click="previewSize = RESET_SIZE"
          >
            重置
          </Button>
        </div>
      </div>
      <div class="px-4 py-4">
        <p v-if="!current" class="text-center text-[12.5px] text-muted-foreground">
          还没有字体可预览。上传后点上方任一字体即可在这里看字形。
        </p>
        <template v-else>
          <p
            class="break-words text-foreground"
            :style="{
              fontFamily: `'${customFontFamily(current.id)}', serif`,
              fontSize: `${previewSize}px`,
              lineHeight: 1.6,
            }"
          >
            {{ SAMPLE }}
          </p>
          <p class="mt-2 text-[11.5px] text-muted-foreground">
            预览用的是字体文件本身；阅读器里选中它后，正文即按此字形渲染。
          </p>
        </template>
      </div>
    </Card>

    <p class="mt-3 text-[11.5px] text-muted-foreground">
      <template v-if="props.variant === 'server'">
        说明：本项目是单用户部署，上游的「阅读字体（每用户）」与「服务端字体」在此为同一份库，
        两页看到的是同一批字体。
      </template>
      <template v-else>
        上传的字体请在「设置 → 阅读器 → 电子书」的「字体」中选择；选中后在阅读器里即时生效。
      </template>
    </p>

    <SettingsUnsupportedCard
      label="Fonts"
      :groups="['UPLOAD FONTS', 'YOUR FONTS']"
      :items="['预览大图（上游独立预览弹层）—— 本项目以行内样例文本替代']"
      note="本项目已实现：字体上传 / 列表 / 删除 / 在阅读器中选用（族名从字体 name 表解析，解析不出时回落文件名）；第 52 期起同族字体的 Regular / Bold / Italic 变体会按字重 / 斜体归组并注入对应的 @font-face，阅读器套用「加粗 / 斜体」时命中真实变体文件而非浏览器合成；并支持行内字体预览（第 50 期：选中任一字体即用字体文件本身渲染样例文本并可调字号）。"
    />
  </div>
</template>
