import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import CommandPalette from '@/components/CommandPalette.vue'
import { useLibraryStore } from '@/stores/library'

function makeRouter(): Router {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/podcasts', component: { template: '<div />' } },
      { path: '/book/:id', component: { template: '<div />' } },
      { path: '/settings/:path(.*)*', component: { template: '<div />' } },
    ],
  })
}

describe('CommandPalette', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('筛页面并回车跳转；Esc 关闭', async () => {
    const router = makeRouter()
    await router.push('/')
    const w = mount(CommandPalette, {
      props: { open: true },
      global: { plugins: [router] },
    })
    await w.find('input[aria-label="命令面板"]').setValue('播客')
    expect(w.text()).toContain('播客')
    await w.find('input[aria-label="命令面板"]').trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/podcasts')
    expect(w.emitted('close')).toBeTruthy()

    await w.find('input[aria-label="命令面板"]').trigger('keydown', { key: 'Escape' })
    expect(w.emitted('close')!.length).toBeGreaterThanOrEqual(2)
  })

  it('书目命中 → /book/:id', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const library = useLibraryStore()
    library.books = [{ id: 'b1', title: '三体', author: '刘慈欣', name: '三体.epub' } as never]
    const router = makeRouter()
    await router.push('/')
    const w = mount(CommandPalette, {
      props: { open: true },
      global: { plugins: [router, pinia] },
    })
    await w.find('input[aria-label="命令面板"]').setValue('三体')
    await w.findAll('button').find((b) => b.text().includes('三体'))!.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/book/b1')
  })
})
