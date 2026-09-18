<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import BookCover from '@/components/ui/BookCover.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import PageHead from '@/components/ui/PageHead.vue'
import Segment from '@/components/ui/Segment.vue'
import { api, type AuthorDetail, type BookCard } from '@/lib/api'
import { useUiStore } from '@/stores/ui'

/** 作者详情：头像 + 传记（在线优先 / 本地覆盖可编辑）+ 名下全部书目。 */
const route = useRoute()
const router = useRouter()
const ui = useUiStore()
const name = computed(() => String(route.params.name))

const detail = ref<AuthorDetail | null>(null)
const books = ref<BookCard[]>([])
const loading = ref(true)

const sortMode = ref<'title' | 'series' | 'added'>('added')
const sortOptions = [
  { value: 'title', label: '书名' },
  { value: 'series', label: '系列' },
  { value: 'added', label: '最近添加' },
]

const bioDraft = ref('')
const editingBio = ref(false)
const busy = ref(false)
const photoFailed = ref(false)
/** 上传头像后 +1，用于给稳定的头像 URL 加版本号，避免浏览器缓存旧图 */
const photoVer = ref(0)

const sorted = computed(() => {
  const list = [...books.value]
  list.sort((a, b) => {
    if (sortMode.value === 'title') return a.title.localeCompare(b.title, 'zh')
    if (sortMode.value === 'series')
      return (a.series || '').localeCompare(b.series || '', 'zh') || a.title.localeCompare(b.title, 'zh')
    return b.mtime - a.mtime
  })
  return list
})

const latest = computed(() =>
  books.value.length ? books.value.reduce((m, b) => (b.mtime > m.mtime ? b : m)) : null,
)

const photoSrc = computed(() => {
  if (!detail.value?.has_photo || photoFailed.value) return ''
  const base = api.authorPhotoUrl(name.value)
  return `${base}${base.includes('?') ? '&' : '?'}v=${photoVer.value}`
})

const initial = computed(() => name.value.slice(0, 1))

async function load(): Promise<void> {
  loading.value = true
  photoFailed.value = false
  editingBio.value = false
  try {
    const d = await api.authorDetail(name.value)
    detail.value = d
    books.value = d.books
    bioDraft.value = d.bio
  } catch {
    detail.value = null
    books.value = []
  }
  loading.value = false
}

onMounted(load)
watch(name, load)

async function fetchOnline(): Promise<void> {
  busy.value = true
  try {
    const r = await api.fetchAuthor(name.value)
    if (r.result && r.result.ok === false) {
      ui.toast(r.result.error || '未抓取到在线资料')
    } else {
      ui.toast(r.result?.has_photo || r.has_photo ? '已更新作者资料' : '已更新传记（无头像）')
    }
    await load()
    photoVer.value += 1
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '抓取失败')
  } finally {
    busy.value = false
  }
}

async function saveBio(): Promise<void> {
  busy.value = true
  try {
    await api.setAuthorBio(name.value, bioDraft.value)
    await load()
    editingBio.value = false
    ui.toast('传记已保存')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '保存失败')
  } finally {
    busy.value = false
  }
}

async function restoreBio(): Promise<void> {
  busy.value = true
  try {
    await api.setAuthorBio(name.value, '')
    await load()
    ui.toast('已恢复为在线传记')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '恢复失败')
  } finally {
    busy.value = false
  }
}

async function onPhoto(ev: Event): Promise<void> {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  busy.value = true
  try {
    await api.uploadAuthorPhoto(name.value, file)
    photoFailed.value = false
    photoVer.value += 1
    await load()
    ui.toast('头像已更新')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '头像上传失败')
  } finally {
    busy.value = false
    input.value = ''
  }
}

async function restorePhoto(): Promise<void> {
  busy.value = true
  try {
    await api.clearAuthorPhoto(name.value)
    photoVer.value += 1
    await load()
    ui.toast('已恢复为在线头像')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '恢复失败')
  } finally {
    busy.value = false
  }
}

function openLatest(): void {
  if (latest.value) router.push(`/book/${latest.value.id}`)
}

function pickPhoto(): void {
  document.getElementById('author-photo-input')?.click()
}
</script>

<template>
  <div>
    <button
      type="button"
      class="mb-4 flex cursor-pointer items-center gap-1 text-[12px] text-muted-foreground transition-colors hover:text-primary"
      @click="router.push('/authors')"
    >
      <Icon name="arrowLeft" class="h-3.5 w-3.5" />全部作者
    </button>

    <PageHead :title="name" :desc="`共 ${books.length} 本`" />

    <div v-if="loading" class="py-20 text-center text-[13px] text-muted-foreground">加载中…</div>

    <template v-else>
      <!-- 作者资料卡：头像 + 传记（在线优先，可本地覆盖） -->
      <Card v-if="detail" padding="none" class="mb-4">
        <div class="flex gap-4 p-4">
          <div
            class="relative h-28 w-22 shrink-0 overflow-hidden rounded-md bg-muted"
            :style="{ backgroundImage: 'linear-gradient(160deg, oklch(0.62 0.16 200), oklch(0.48 0.13 240))' }"
          >
            <img
              v-if="photoSrc"
              :src="photoSrc"
              :alt="name"
              class="h-full w-full object-cover"
              @error="photoFailed = true"
            >
            <span
              v-else
              class="absolute inset-0 flex items-center justify-center font-serif text-2xl font-semibold text-white/92"
            >
              {{ initial }}
            </span>
          </div>

          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-2">
              <span
                v-if="detail.bio_overridden"
                class="rounded bg-primary/14 px-1.5 py-0.5 text-[10px] text-primary"
              >传记已本地修改</span>
              <span
                v-if="detail.photo_overridden"
                class="rounded bg-primary/14 px-1.5 py-0.5 text-[10px] text-primary"
              >头像已本地修改</span>
              <span v-if="detail.photo_source" class="text-[10.5px] text-muted-foreground">
                在线来源：{{ detail.photo_source }}
              </span>
            </div>

            <p
              class="mt-1.5 text-[12.5px] leading-relaxed whitespace-pre-wrap"
              :class="detail.bio ? 'text-foreground/90' : 'text-muted-foreground'"
            >
              {{ detail.bio || '暂无传记。点「抓取在线资料」从 OpenLibrary 获取，或点「编辑传记」手动填写。' }}
            </p>

            <div class="mt-3 flex flex-wrap items-center gap-2">
              <Button size="sm" :disabled="busy" @click="fetchOnline">
                <Icon name="download" class="mr-1.5 h-3.5 w-3.5" />抓取在线资料
              </Button>
              <Button size="sm" variant="ghost" :disabled="busy" @click="editingBio = !editingBio">
                {{ editingBio ? '取消' : '编辑传记' }}
              </Button>
              <Button size="sm" variant="ghost" :disabled="busy" @click="pickPhoto">上传头像</Button>
              <Button
                v-if="detail.photo_overridden"
                size="sm"
                variant="ghost"
                :disabled="busy"
                @click="restorePhoto"
              >
                ↺ 恢复在线头像
              </Button>
              <input
                id="author-photo-input"
                type="file"
                accept="image/jpeg,image/png,image/webp,image/gif"
                class="hidden"
                @change="onPhoto"
              >
            </div>

            <div v-if="editingBio" class="mt-3">
              <textarea
                v-model="bioDraft"
                rows="4"
                class="w-full rounded-md border border-border bg-muted px-2.5 py-2 text-[12.5px] leading-relaxed text-foreground outline-none focus:border-ring focus:bg-card"
                placeholder="填写作者简介…"
              />
              <div class="mt-2 flex items-center gap-2">
                <Button size="sm" variant="primary" :disabled="busy" @click="saveBio">保存传记</Button>
                <Button
                  v-if="detail.bio_overridden"
                  size="sm"
                  variant="ghost"
                  :disabled="busy"
                  @click="restoreBio"
                >
                  ↺ 恢复在线传记
                </Button>
              </div>
            </div>
          </div>
        </div>
      </Card>

      <div v-if="books.length" class="mb-4 flex items-center gap-2">
        <Segment
          :options="sortOptions"
          :model-value="sortMode"
          @update:model-value="(v: string) => (sortMode = v as 'title' | 'series' | 'added')"
        />
        <Button size="sm" class="ml-auto" :disabled="!latest" @click="openLatest">
          <Icon name="book" class="mr-1.5 h-3.5 w-3.5" />打开最近添加
        </Button>
      </div>

      <div
        v-if="books.length"
        class="grid grid-cols-2 gap-x-4 gap-y-5 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-6 2xl:grid-cols-8"
      >
        <button
          v-for="b in sorted"
          :key="b.id"
          type="button"
          class="group cursor-pointer text-left"
          @click="router.push(`/book/${b.id}`)"
        >
          <BookCover :book="b" />
          <div class="mt-2 truncate text-[12.5px] font-medium text-foreground">{{ b.title }}</div>
          <div class="truncate text-[11.5px] text-muted-foreground">{{ b.series || '独立作品' }}</div>
        </button>
      </div>

      <EmptyState v-else icon="users" title="这位作者名下的书被移除了" desc="书目可能已不在导出目录。" />
    </template>
  </div>
</template>
