<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import BookCover from '@/components/ui/BookCover.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import AudioPlayer from '@/components/reader/AudioPlayer.vue'
import { api, type AudioTrack, type BookDetail } from '@/lib/api'

/**
 * 有声书播放页 `/listen/:id`。
 *
 * 轨道清单优先用详情里随附的 `audio_tracks`（省一次往返），
 * 老后端 / 深链兜底时再单独请求 `/audio`。
 */
const route = useRoute()
const router = useRouter()
const bookId = computed(() => String(route.params.id))

const book = ref<BookDetail | null>(null)
const tracks = ref<AudioTrack[]>([])
const loading = ref(true)
const error = ref('')

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const d = await api.bookDetail(bookId.value)
    book.value = d
    if ((d.format || '').toUpperCase() !== 'AUDIO') {
      error.value = '这不是有声书'
      loading.value = false
      return
    }
    if (d.audio_tracks?.length) {
      tracks.value = d.audio_tracks
    } else {
      tracks.value = (await api.audioTracks(bookId.value)).items
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
    book.value = null
  }
  loading.value = false
}

onMounted(load)
watch(bookId, load)

const totalSize = computed(() =>
  tracks.value.reduce((n, t) => n + (t.size || 0), 0),
)

function fmtSize(n: number): string {
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`
}
</script>

<template>
  <div>
    <button
      type="button"
      class="mb-4 flex cursor-pointer items-center gap-1 text-[12px] text-muted-foreground transition-colors hover:text-primary"
      @click="router.push(`/book/${bookId}`)"
    >
      <Icon name="arrowLeft" class="h-3.5 w-3.5" />返回详情
    </button>

    <div v-if="loading" class="py-20 text-center text-[13px] text-muted-foreground">加载中…</div>

    <EmptyState
      v-else-if="error || !book"
      icon="alert"
      :title="error || '找不到这本有声书'"
      desc="它可能已被移除，或不是有声书。"
    >
      <template #action>
        <button
          type="button"
          class="cursor-pointer rounded-md bg-primary px-3 py-1.5 text-[12.5px] text-primary-foreground"
          @click="router.push(`/book/${bookId}`)"
        >
          返回详情
        </button>
      </template>
    </EmptyState>

    <template v-else>
      <Card padding="none" class="mb-4">
        <div class="flex gap-4 p-4">
          <div class="w-24 shrink-0">
            <BookCover :book="book" :show-title="true" :interactive="false" />
          </div>
          <div class="min-w-0 flex-1">
            <h1 class="truncate text-[16px] font-semibold text-foreground">{{ book.title }}</h1>
            <p class="mt-0.5 truncate text-[12.5px] text-muted-foreground">
              {{ book.author || '未知作者' }}
            </p>
            <p v-if="book.narrators && book.narrators.length" class="mt-0.5 truncate text-[12.5px] text-muted-foreground">
              演播：{{ book.narrators.join('、') }}
            </p>
            <div class="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11.5px] text-muted-foreground tabular-nums">
              <span>{{ tracks.length }} 轨</span>
              <span v-if="totalSize">{{ fmtSize(totalSize) }}</span>
              <span v-if="book.year">{{ book.year }}</span>
            </div>
          </div>
        </div>
      </Card>

      <Card v-if="tracks.length" padding="none">
        <div class="p-4">
          <AudioPlayer :book-id="bookId" :tracks="tracks" />
        </div>
      </Card>

      <EmptyState
        v-else
        icon="alert"
        title="这本有声书没有可用音轨"
        desc="目录里没有找到音频文件（支持的格式：mp3 / m4a / m4b / flac / opus / ogg / aac / wav）。"
      />
    </template>
  </div>
</template>
