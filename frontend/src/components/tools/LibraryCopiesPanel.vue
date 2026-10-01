<script setup lang="ts">
/**
 * 副本与容器（第 87 期），与「同名冲突」面板并列长在书库管理页。
 *
 * ① **待展开的压缩包**：`.zip` 里装的是别的书（EPUB / PDF …）⇒ 没法直接阅读。
 *    按内容分派得出形态的那些（图片档）已被归一成 `CBZ`、能直接读，**不会出现在这里**。
 *    展开是它们唯一的出路：容器本身就是改了后缀的 EPUB 就**整份另存为 `.epub`**，
 *    里面是文档就**逐个提取**。
 *    ⚠️ 一个按钮对应一次**显式动作**，不做自动展开 —— 它会往用户的库目录里写字，
 *    必须由人按下去；界面也不提供「展开后删源」（不可逆动作不进便捷路径）。
 * ② **同一本书的副本**：`X.zip` 与 `X (2).zip`、破折号 / 全角半角差异的那几份。
 *    它们是同一本书（**没撞 id、不需要改名**），用户要决定的是「多出来的那份删不删」。
 *    本面板**只列不动** —— 删除不可逆，走别处的删除入口。
 */
import { computed, ref } from 'vue'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import { api, type ContainerItem, type CopyGroup } from '@/lib/api'
import { useUiStore } from '@/stores/ui'

const emit = defineEmits<{ (e: 'changed'): void }>()
const ui = useUiStore()

const copies = ref<CopyGroup[]>([])
const containers = ref<ContainerItem[]>([])
const loading = ref(false)
/** 正在展开的条目 id（空 = 没在忙）：同一时刻只允许一个，免得并发写同一个目录 */
const busy = ref('')

async function load(): Promise<void> {
  loading.value = true
  try {
    const [c, k] = await Promise.all([api.libraryCopies(), api.libraryContainers()])
    copies.value = c.items
    containers.value = k.items
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '读取副本 / 容器清单失败')
    copies.value = []
    containers.value = []
  } finally {
    loading.value = false
  }
}

void load()
defineExpose({ reload: load })

const hasAny = computed(() => copies.value.length > 0 || containers.value.length > 0)

async function unpack(item: ContainerItem): Promise<void> {
  busy.value = item.id
  try {
    const res = await api.unpackBook(item.id)
    const failed = res.actions.filter((a) => !a.ok)
    ui.toast(
      res.ok
        ? `已展开 ${res.actions.length - failed.length} 个文件${
            failed.length ? `，${failed.length} 条未处理` : ''
          }`
        : res.reason || '展开失败',
    )
    // 逐条失败原因如实抛给用户（撞名 / 读不到 / 写失败）—— 不整批失败、也不静默
    for (const f of failed.slice(0, 3)) ui.toast(`${f.dest}：${f.note}`)
    emit('changed')
    await load()
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '展开失败')
  } finally {
    busy.value = ''
  }
}
</script>

<template>
  <div v-if="loading && !hasAny" class="px-4 py-6 text-[12.5px] text-muted-foreground">检查中…</div>
  <div v-else-if="!hasAny" class="px-4 py-6 text-[12.5px] text-muted-foreground">
    没有副本，也没有待展开的压缩包
  </div>
  <template v-else>
    <div v-if="containers.length" class="border-b border-border px-4 py-3">
      <div class="flex flex-wrap items-center gap-2">
        <span class="text-[13px] font-medium text-foreground">待展开的压缩包</span>
        <Badge>{{ containers.length }} 个</Badge>
      </div>
      <div class="mt-0.5 text-[11.5px] leading-relaxed text-muted-foreground">
        这些 zip 里装的是别的书（EPUB / PDF 等），没法直接阅读。展开会把里面的文件
        原样落到同一个目录：不覆盖已有文件、也不删源文件。
      </div>
      <div
        v-for="it in containers"
        :key="it.id"
        class="mt-2 flex flex-wrap items-center gap-2 text-[11.5px]"
      >
        <code class="min-w-0 flex-1 truncate text-foreground" :title="it.name">{{ it.name }}</code>
        <span v-if="it.targets.length" class="shrink-0 text-muted-foreground">
          → {{ it.targets.join('、') }}
        </span>
        <Button v-if="it.unpackable" size="sm" :disabled="busy === it.id" @click="unpack(it)">
          {{ busy === it.id ? '展开中…' : '展开' }}
        </Button>
        <span v-else class="shrink-0 text-muted-foreground">{{ it.reason }}</span>
      </div>
    </div>

    <div v-if="copies.length" class="px-4 py-3">
      <div class="flex flex-wrap items-center gap-2">
        <span class="text-[13px] font-medium text-foreground">同一本书的副本</span>
        <Badge>{{ copies.length }} 组</Badge>
      </div>
      <div class="mt-0.5 text-[11.5px] leading-relaxed text-muted-foreground">
        名字只差副本后缀 / 破折号 / 全角半角 —— 它们是同一本书，不影响阅读，只是白占空间。
        这里只列不动：删哪一份由你决定。
      </div>
      <div v-for="g in copies" :key="`${g.library_id}|${g.dir}|${g.key}`" class="mt-2">
        <div class="flex flex-wrap items-center gap-2 text-[11.5px] text-muted-foreground">
          <Badge>{{ g.count }} 份</Badge>
          <span class="truncate" :title="g.dir">{{ g.dir || '库根目录' }}</span>
        </div>
        <div
          v-for="it in g.items"
          :key="it.name"
          class="mt-1 flex flex-wrap items-center gap-2 text-[11.5px]"
        >
          <Badge v-if="it.keep">建议保留</Badge>
          <code
            class="min-w-0 flex-1 truncate"
            :class="it.keep ? 'text-foreground' : 'text-muted-foreground'"
          >
            {{ it.name }}
          </code>
        </div>
      </div>
    </div>
  </template>
</template>
