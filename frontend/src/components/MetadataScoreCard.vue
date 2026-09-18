<script setup lang="ts">
import { onMounted, ref } from 'vue'

import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import { api, type MetadataScoreResponse } from '@/lib/api'
import { useUiStore } from '@/stores/ui'

/**
 * 元数据完整度评分（Confidence Score，对应上游「书库 → 元数据 → Confidence Score」）。
 *
 * 自取数据（`GET /api/metadata-score`）：权重模型与分位聚合都在后端 core/metascore.py，
 * 这里只负责把「分布 / 权重表 / 最该补的书」画出来。模型是代码定义的，
 * 没有上游的「Reset to defaults」—— 所以只提供「重新计算」（绕过后端缓存重算）。
 */
const ui = useUiStore()
const data = ref<MetadataScoreResponse | null>(null)
const loading = ref(false)

async function load(force = false): Promise<void> {
  loading.value = true
  try {
    data.value = await api.metadataScore(force)
    if (force) ui.toast('已重新计算元数据完整度')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '计算失败')
  } finally {
    loading.value = false
  }
}

/** 分档 → 进度条颜色（与分档语义一致：低分告警、高分通过） */
const BAND: Record<string, string> = {
  lt50: 'bg-destructive',
  '50_69': 'bg-warning',
  '70_89': 'bg-primary',
  gte90: 'bg-success',
}

onMounted(() => {
  void load()
})
</script>

<template>
  <div>
    <!-- 分布总览 -->
    <Card padding="none">
      <div class="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
        <span class="text-[13px] font-medium text-foreground">元数据完整度</span>
        <span class="text-[11.5px] text-muted-foreground">
          每本书按字段权重算 0–100 分，这里是全库分布
        </span>
        <Button size="sm" class="ml-auto" :disabled="loading" @click="load(true)">
          {{ loading ? '计算中…' : '重新计算' }}
        </Button>
      </div>

      <template v-if="data && data.total">
        <div class="grid grid-cols-2 gap-x-4 gap-y-3 px-4 py-3.5 sm:grid-cols-5">
          <div>
            <div class="text-[11px] text-muted-foreground">平均分</div>
            <div class="mt-0.5 text-[15px] font-semibold tabular-nums text-foreground">{{ data.avg }}</div>
          </div>
          <div>
            <div class="text-[11px] text-muted-foreground">中位 P50</div>
            <div class="mt-0.5 text-[15px] font-semibold tabular-nums text-foreground">{{ data.p50 }}</div>
          </div>
          <div>
            <div class="text-[11px] text-muted-foreground">P90</div>
            <div class="mt-0.5 text-[15px] font-semibold tabular-nums text-foreground">{{ data.p90 }}</div>
          </div>
          <div>
            <div class="text-[11px] text-muted-foreground">区间</div>
            <div class="mt-0.5 text-[15px] font-semibold tabular-nums text-foreground">{{ data.min }}–{{ data.max }}</div>
          </div>
          <div>
            <div class="text-[11px] text-muted-foreground">样本</div>
            <div class="mt-0.5 text-[15px] font-semibold tabular-nums text-foreground">{{ data.total }} 本</div>
          </div>
        </div>

        <div class="space-y-2 border-t border-border px-4 py-3.5">
          <div v-for="b in data.buckets" :key="b.key" class="flex items-center gap-3">
            <span class="w-14 shrink-0 text-[11.5px] text-muted-foreground">{{ b.label }}</span>
            <div class="h-2 flex-1 overflow-hidden rounded-full bg-muted">
              <div
                class="h-full rounded-full transition-[width] duration-500"
                :class="BAND[b.key] ?? 'bg-primary'"
                :style="{ width: `${b.percent}%` }"
              />
            </div>
            <span class="w-20 shrink-0 text-right text-[11.5px] tabular-nums text-muted-foreground">
              {{ b.count }} · {{ b.percent }}%
            </span>
          </div>
        </div>
      </template>

      <EmptyState
        v-else-if="data"
        class="m-4"
        dashed
        title="书库里还没有可评分的书"
        desc="导出目录里有成品后，这里会显示完整度分布。"
      />
      <div v-else class="px-4 py-8 text-center text-[12.5px] text-muted-foreground">
        正在计算元数据完整度…
      </div>
    </Card>

    <!-- 计分字段与权重 -->
    <Card v-if="data" padding="none" class="mt-4">
      <div class="border-b border-border px-4 py-3 text-[13px] font-medium text-foreground">
        计分字段与权重
      </div>
      <div
        v-for="g in data.groups"
        :key="g.key"
        class="border-b border-border px-4 py-3 last:border-b-0"
      >
        <div class="flex flex-wrap items-center gap-2">
          <span class="text-[12.5px] font-medium text-foreground">{{ g.zh }}</span>
          <span class="font-mono text-[11px] text-muted-foreground">{{ g.label }}</span>
          <span class="ml-auto text-[11.5px] tabular-nums text-muted-foreground">
            权重 {{ g.weight }} · 覆盖 {{ g.coverage }}%
          </span>
        </div>
        <div class="mt-2 space-y-1.5">
          <div v-for="f in g.fields" :key="f.key" class="flex items-center gap-3">
            <span class="w-20 shrink-0 text-[12px] text-foreground">{{ f.label }}</span>
            <span class="w-24 shrink-0 font-mono text-[10.5px] text-muted-foreground">{{ f.key }}</span>
            <div class="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
              <div
                class="h-full rounded-full bg-primary/70"
                :style="{ width: `${f.coverage}%` }"
              />
            </div>
            <span class="w-24 shrink-0 text-right text-[11px] tabular-nums text-muted-foreground">
              {{ f.weight }} · {{ f.coverage }}%
            </span>
          </div>
        </div>
      </div>
    </Card>

    <!-- 最该补的书 -->
    <Card v-if="data && data.lowest.length" padding="none" class="mt-4">
      <div class="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
        <span class="text-[13px] font-medium text-foreground">最该补元数据的书</span>
        <span class="text-[11.5px] text-muted-foreground">缺的字段按权重从高到低排 —— 先补前面的收益最大</span>
      </div>
      <div
        v-for="b in data.lowest"
        :key="b.id || b.name"
        class="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border px-4 py-2.5 last:border-b-0"
      >
        <span class="w-12 shrink-0 text-[13px] font-semibold tabular-nums text-foreground">{{ b.score }}</span>
        <div class="min-w-0 flex-1">
          <div class="truncate text-[12.5px] text-foreground" :title="b.name">{{ b.title || b.name }}</div>
          <div class="truncate text-[11px] text-muted-foreground">
            缺：{{ b.missing.map((m) => m.label).join('、') || '无' }}
          </div>
        </div>
        <span class="shrink-0 text-[11px] text-muted-foreground">{{ b.format }}</span>
      </div>
    </Card>

    <!-- 不计分 + 口径说明 -->
    <Card v-if="data" class="mt-4">
      <div class="text-[12.5px] font-medium text-foreground">口径说明</div>
      <ul class="mt-2 list-disc space-y-1 pl-5 text-[11.5px] leading-relaxed text-muted-foreground">
        <li v-for="n in data.notes" :key="n">{{ n }}</li>
        <li>
          不参与计分：<span class="text-foreground">{{ data.not_scored.map((n) => n.label).join('、') }}</span>
          （{{ data.not_scored.map((n) => n.why).join('；') }}）
        </li>
      </ul>
    </Card>
  </div>
</template>
