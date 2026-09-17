<script setup lang="ts">
import { onMounted, ref } from 'vue'

import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
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

      <div
        v-for="f in fonts.items"
        :key="f.id"
        class="flex items-center gap-3 border-b border-border/60 px-4 py-2.5 last:border-b-0"
      >
        <div class="min-w-0 flex-1">
          <div class="truncate text-[13px] text-foreground" :style="{ fontFamily: `'NF-${f.id}', serif` }">
            {{ f.name }}
          </div>
          <div class="truncate text-[11px] text-muted-foreground">
            {{ f.style }} · {{ f.format.toUpperCase() }} · {{ fmtSize(f.size) }}
          </div>
        </div>
        <button
          type="button"
          class="shrink-0 cursor-pointer text-[12px] text-muted-foreground transition-colors hover:text-destructive"
          @click="remove(f.id, f.name)"
        >
          删除
        </button>
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
      :items="[
        '按字重/斜体派生变体（Regular / Bold / Italic 自动匹配）',
        '字体预览大图（上游展示字形样本，本项目只显示族名）',
      ]"
      note="本项目已实现：字体上传 / 列表 / 删除 / 在阅读器中选用（族名从字体 name 表解析，解析不出时回落文件名）。"
    />
  </div>
</template>
