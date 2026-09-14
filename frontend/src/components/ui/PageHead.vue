<script setup lang="ts">
/** 页头：衬线大标题 + 一行说明。BookOrbit 的标题用 Fraunces。 */
defineProps<{ title: string; desc?: string }>()
</script>

<template>
  <div class="mb-5">
    <h1 class="font-serif text-[22px] leading-tight font-semibold tracking-tight text-foreground">
      {{ title }}
    </h1>
    <p v-if="desc" class="mt-0.5 text-[12.5px] text-muted-foreground">{{ desc }}</p>
  </div>
</template>
