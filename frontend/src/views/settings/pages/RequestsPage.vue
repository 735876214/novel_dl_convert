<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import Badge from '@/components/ui/Badge.vue'
import Card from '@/components/ui/Card.vue'
import Icon from '@/components/ui/Icon.vue'
import { api, type RequestsConfig } from '@/lib/api'
import { useUiStore } from '@/stores/ui'

/**
 * SERVER → Requests（`/settings/admin/requests`）
 *
 * 依据 `docs/bookorbit-capability-gap.md` §9：**页面与接口保留、功能后置**。
 * 三段结构（Sources / Download clients / Automation）按上游真实结构搭，
 * 配置项可见，但每一项都明确标注「功能待实现」。
 *
 * ⚠️ 本页**零后端写入**：后端接口是只读的，整页也没有任何保存 / 提交按钮。
 *    给一个存不下去的「保存」按钮就是假交互（§15 执行约定 1）。
 *    本页也不呈现为「未支持」占位 —— 它是有真实接口、真实结构的骨架页。
 */
const ui = useUiStore()
const data = ref<RequestsConfig | null>(null)
const loading = ref(true)

onMounted(async () => {
  try {
    data.value = await api.requestsConfig()
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '求书配置加载失败')
  }
  loading.value = false
})
</script>

<template>
  <div>
    <div class="mb-3 flex flex-wrap items-baseline gap-2">
      <h2 class="text-[14px] font-semibold text-foreground">求书</h2>
      <span class="font-mono text-[11.5px] text-muted-foreground">Requests</span>
      <Badge tone="accent">功能后置</Badge>
      <span class="text-[11.5px] text-muted-foreground">页面与接口已保留，具体能力排在后期</span>
    </div>
    <p class="mb-3 text-[11.5px] leading-relaxed text-muted-foreground">
      上游的求书是「登记需求 → 等待索引器匹配 → 交给下载客户端 → 自动入库」。
      本项目保留该页的结构与接口，但真正的求书流程尚未实现，因此下方配置项<strong>均不可编辑、也不会写入后端</strong>。
    </p>

    <div v-if="loading" class="py-16 text-center text-[13px] text-muted-foreground">加载中…</div>

    <template v-else-if="data">
      <!-- 未配置搜索源的引导（对应上游「No search sources are set up…」） -->
      <Card v-if="data.alternative.guidance" class="mb-4" padding="none">
        <div class="flex flex-wrap items-center gap-3 px-4 py-3.5">
          <span class="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-warning/14 text-warning">
            <Icon name="alert" class="h-4 w-4" />
          </span>
          <div class="min-w-0 flex-1">
            <div class="text-[12.5px] font-medium text-foreground">尚无可用搜索源</div>
            <div class="mt-0.5 text-[11.5px] leading-relaxed text-muted-foreground">
              {{ data.alternative.guidance }}
            </div>
          </div>
          <RouterLink :to="data.alternative.settings_link">
            <span class="text-[11.5px] underline">前往网络与下载</span>
          </RouterLink>
          <RouterLink :to="data.alternative.tools_link">
            <span class="text-[11.5px] underline">书源管理</span>
          </RouterLink>
        </div>
      </Card>

      <!-- 三段结构（照上游） -->
      <Card v-for="s in data.sections" :key="s.key" padding="none" class="mb-4">
        <div class="border-b border-border px-4 py-3">
          <div class="flex flex-wrap items-baseline gap-2">
            <h3 class="text-[13px] font-semibold text-foreground">{{ s.label }}</h3>
            <span class="font-mono text-[11px] text-muted-foreground">{{ s.key }}</span>
            <span class="ml-auto text-[10.5px] text-muted-foreground">功能待实现</span>
          </div>
          <p class="mt-1 text-[11.5px] leading-relaxed text-muted-foreground">{{ s.desc }}</p>
        </div>

        <div
          v-for="(it, idx) in s.items"
          :key="idx"
          class="flex items-start gap-3 border-b border-border/60 px-4 py-2.5 last:border-b-0"
        >
          <span class="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-muted-foreground/50" />
          <span class="shrink-0 text-[12.5px] text-foreground">{{ it.label }}</span>
          <span class="min-w-0 flex-1 text-[11.5px] leading-relaxed text-muted-foreground">{{ it.detail }}</span>
        </div>
      </Card>

      <!-- 本项目的替代路径：如实说明形态不同，不假装有等价能力 -->
      <Card padding="none">
        <div class="border-b border-border px-4 py-3">
          <h3 class="text-[13px] font-semibold text-foreground">{{ data.alternative.label }}</h3>
          <p class="mt-1 text-[11.5px] leading-relaxed text-muted-foreground">{{ data.alternative.desc }}</p>
        </div>
        <dl class="grid grid-cols-1 gap-1.5 px-4 py-3 sm:grid-cols-3">
          <div>
            <dt class="text-[11px] text-muted-foreground">下载功能</dt>
            <dd class="text-[12.5px]" :class="data.alternative.download_enabled ? 'text-success' : 'text-muted-foreground'">
              {{ data.alternative.download_enabled ? '已开启' : '已关闭' }}
            </dd>
          </div>
          <div>
            <dt class="text-[11px] text-muted-foreground">仅公版源</dt>
            <dd class="text-[12.5px] text-foreground">{{ data.alternative.public_only ? '是' : '否' }}</dd>
          </div>
          <div>
            <dt class="text-[11px] text-muted-foreground">书源规则数</dt>
            <dd class="font-mono text-[12.5px] text-foreground">{{ data.alternative.source_count }}</dd>
          </div>
        </dl>
      </Card>

      <Card class="mt-4" padding="sm">
        <div class="flex gap-2 text-[11.5px] leading-relaxed text-muted-foreground">
          <Icon name="alert" class="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
            本页为只读骨架：后端接口 <span class="font-mono">GET /api/requests/config</span> 返回明确空态（不是 404），
            但<strong>没有任何写入接口</strong>。求书本体（插件式索引器、Torznab/Newznab 接入、下载客户端对接、下载后自动化）
            排在后期实现。
          </span>
        </div>
      </Card>
    </template>
  </div>
</template>
