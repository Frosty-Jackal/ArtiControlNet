// 站内图片渲染（Spec17 §7.1）：<img> 无法带 Authorization 头，
// 统一用带 token 的 axios 拉 blob → objectURL。
// 模块级缓存带引用计数：同一张图在多个位置出现时只拉一次，全部卸载后才 revoke。
//
// Spec17 之前 GalleryPanel / CommunityPanel 各写了一份 objectURL 填充 + 释放逻辑，
// 聊天气泡是第三处 —— 三处共用本模块（GalleryPanel / CommunityPanel 已迁移过来）。
import { onBeforeUnmount, ref, unref, watch } from 'vue'
import { fetchGalleryFile } from '../api/chatApi'

// 缓存键必须区分来源：聊天/作品库 `gallery:<id>`，社区帖子 `community:<postId>`
// —— 两者 id 空间不同，混用一个 Map 会把 3 号作品当成 3 号帖子。
const CACHE_PREFIX = { gallery: 'gallery', community: 'community' }

// 空闲条目上限：历史长、图片多的页面里，仅靠引用计数无法回收"曾经拉过但已释放"
// 的条目（它们的 url 已被 revoke，但条目本身还挂在 Map 上）。超过上限时先清空闲项。
const IDLE_CACHE_MAX = 80

/** key → { url, missing, count, promise, loader }；url 为空串表示尚未就绪 */
const cache = new Map()

function cacheKey(prefix, id) {
  return `${CACHE_PREFIX[prefix] || prefix}:${id}`
}

/** 清掉空闲条目（count<=0），避免 Map 无界增长；正在被引用的条目一律不动。 */
function pruneIdle() {
  if (cache.size <= IDLE_CACHE_MAX) return
  for (const [key, entry] of cache) {
    if (cache.size <= IDLE_CACHE_MAX) break
    if (entry.count <= 0) {
      if (entry.url) URL.revokeObjectURL(entry.url)
      cache.delete(key)
    }
  }
}

/**
 * 取（或建立）某个 key 的缓存条目，并把引用计数 +1。
 * 首次建立时立即发起 loader()（同一 key 并发只发一次请求）。
 */
function acquireEntry(key, loader) {
  let entry = cache.get(key)
  if (!entry) {
    entry = { url: '', missing: false, count: 0, promise: null, loader }
    cache.set(key, entry)
    pruneIdle()
  }
  entry.count += 1
  if (!entry.promise && !entry.url && !entry.missing) {
    entry.promise = entry
      .loader()
      .then((resp) => {
        const url = URL.createObjectURL(resp.data)
        // 拉取途中引用已归零（组件卸载 / 列表刷新）→ 直接回收，不进缓存
        if (entry.count <= 0) {
          URL.revokeObjectURL(url)
          return
        }
        entry.url = url
      })
      .catch((e) => {
        // 404 = 图片确实已被删除（Spec17 §3.4 悬挂引用）→ 渲染「图片已删除」占位；
        // 其余错误（网络/401）不置 missing，留待下次访问重试。
        entry.missing = e && e.status === 404
      })
      .finally(() => {
        entry.promise = null
      })
  }
  return entry
}

/** 释放一个引用；计数归零即 revoke 并移除条目。 */
function releaseKey(key) {
  const entry = cache.get(key)
  if (!entry) return
  entry.count -= 1
  if (entry.count > 0) return
  cache.delete(key)
  if (entry.url) URL.revokeObjectURL(entry.url)
}

/** 切换用户 / 登出时整表清空（避免上一个账号的图片继续驻留内存）。 */
export function clearAuthedImageCache() {
  for (const entry of cache.values()) {
    if (entry.url) URL.revokeObjectURL(entry.url)
  }
  cache.clear()
}

/** idSource 允许是 ref / computed / getter；统一读成 number 或 null。 */
function readId(idSource) {
  const v = typeof idSource === 'function' ? idSource() : unref(idSource)
  if (v === null || v === undefined || v === '') return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

/**
 * 单张响应式拉取。idSource 是 ref/getter，返回 image_id 或 null。
 * 返回 { src, missing, loading }：
 *   src     可用的 objectURL；未就绪 / 失败为空串
 *   missing true = 后端返回 404（图片已被用户在「我的作品」里删除）→ 渲染占位
 */
export function useAuthedImage(idSource, { fetchFile = fetchGalleryFile, prefix = 'gallery' } = {}) {
  const src = ref('')
  const missing = ref(false)
  const loading = ref(false)
  let currentKey = null

  async function resolve(entry, key) {
    if (!entry.url && !entry.missing && entry.promise) await entry.promise
    if (currentKey !== key) return // 期间已切换 / 卸载，结果作废
    src.value = entry.url || ''
    missing.value = entry.missing
    loading.value = false
  }

  watch(
    () => readId(idSource),
    (id) => {
      if (currentKey) {
        releaseKey(currentKey)
        currentKey = null
      }
      src.value = ''
      missing.value = false
      loading.value = false
      if (id === null) return
      const key = cacheKey(prefix, id)
      currentKey = key
      const entry = acquireEntry(key, () => fetchFile(id))
      loading.value = !entry.url && !entry.missing
      resolve(entry, key)
    },
    { immediate: true }
  )

  onBeforeUnmount(() => {
    if (currentKey) {
      releaseKey(currentKey)
      currentKey = null
    }
  })

  return { src, missing, loading }
}

/**
 * 列表批量填充：给每个 item 按 getId 拉图，写入 item[key]（默认 'objectUrl'）。
 * 与单张共享同一个缓存与引用计数。
 *
 * 缓存键写回 item.__imgKey：releaseObjectUrl 由此取键，不必再推导一次 id
 * （item 常被 `{ ...item }` 复制后替换，getId 未必还能从副本上取到原 id）。
 */
export async function attachObjectUrls(
  items,
  fetchFile,
  { getId, key = 'objectUrl', prefix = 'gallery' } = {}
) {
  const list = Array.isArray(items) ? items : []
  await Promise.all(
    list.map(async (item) => {
      if (!item) return item
      const id = getId ? getId(item) : item.id
      if (id === null || id === undefined || id === '') {
        item[key] = null
        return item
      }
      const ck = cacheKey(prefix, id)
      item.__imgKey = ck
      const entry = acquireEntry(ck, () => fetchFile(id))
      if (!entry.url && !entry.missing && entry.promise) await entry.promise
      item[key] = entry.url || null
      return item
    })
  )
  return list
}

/** 释放某个 item 的引用（列表刷新 / 组件卸载时调用）。 */
export function releaseObjectUrl(item, key = 'objectUrl') {
  if (!item) return
  const ck = item.__imgKey
  if (ck) {
    releaseKey(ck)
    delete item.__imgKey
  }
  item[key] = null
}

/** 批量释放（列表整体重拉 / 组件卸载时调用）。 */
export function releaseObjectUrls(items, key = 'objectUrl') {
  ;(Array.isArray(items) ? items : []).forEach((it) => releaseObjectUrl(it, key))
}
