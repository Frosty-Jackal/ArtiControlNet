// Spec24 §2.4：未登录游客被拦下时，把他"正要发出的东西"暂存下来，
// 登录成功（或从登录层返回）后由 App.vue 回填进输入框。
//
// 两处存储，各存各的、各失败各的：
//   localStorage → 文本 + 元数据（同步、快；配额约 5MB，只放字符串）
//   IndexedDB    → 图片 Blob（localStorage 装不下：输入框收 ≤10MB 的图，
//                  转 base64 还要涨 33%，而配额只有约 5MB —— 大部分真实照片会静默写失败）
//
// **任何一步失败都降级，绝不抛**：拿不到图就只回填文字；两处都拿不到就当作没暂存过。
// 私有模式 / 禁用存储的浏览器里这两个 API 都可能直接抛，所以每一步都包了 try/catch。

const TEXT_KEY = 'artcn_pending_request'
const TTL_MS = 3 * 60 * 1000 // Spec24 §2.5：暂存有效期 3 分钟

const DB_NAME = 'artcn_drafts'
const DB_VERSION = 1
const STORE = 'blobs'
const BLOB_KEY = 'pending'

// ---------- localStorage：文本 + 元数据 ----------

function readMeta() {
  try {
    const raw = localStorage.getItem(TEXT_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null // 隐私模式下 getItem 也可能抛
  }
}

function writeMeta(meta) {
  try {
    localStorage.setItem(TEXT_KEY, JSON.stringify(meta))
    return true
  } catch {
    return false // 配额满 / 隐私模式
  }
}

function clearMeta() {
  try {
    localStorage.removeItem(TEXT_KEY)
  } catch {
    /* 同上 */
  }
}

// ---------- IndexedDB：图片 Blob ----------

// 连接缓存：一次失败就永久降级（IDB 不可用时重试也不会成功）。
// 不主动 close —— 页面卸载时浏览器自己收。
let dbPromise = null

// ⚠️ Spec24 终审 F2b：`open()` **没有"永远不回调"这个失败模式的对策**——策略弹窗没人点、
// 另一个标签页压着旧版本导致 upgrade 卡住，两种情况下三个回调一个都不来，Promise 永不 settle。
// 那不只是"图存不下"：`takeRequest` 会连文本一起卡死（它在读图之后还要 await clearRequest），
// 于是登录成功后输入框永远不回填。所以这里给一个上限，超时就当作"这台机器没有 IDB"——
// 与 onerror/onblocked 走同一条降级路径（只回填文字），代价是慢机器上可能少回填一张图。
const DB_OPEN_TIMEOUT_MS = 1500

function openDbOnce() {
  return new Promise((resolve) => {
    let settled = false
    const done = (v) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      resolve(v)
    }
    const timer = setTimeout(() => done(null), DB_OPEN_TIMEOUT_MS)

    let req
    try {
      req = indexedDB.open(DB_NAME, DB_VERSION)
    } catch {
      return done(null)
    }
    if (!req) return done(null)
    req.onupgradeneeded = () => {
      const db = req.result
      if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE)
    }
    req.onsuccess = () => done(req.result)
    // 配额满 / 被策略禁用 / 被另一个标签页占着旧版本 → 一律当作"没有 IDB"
    req.onerror = () => done(null)
    req.onblocked = () => done(null)
  })
}

function openDb() {
  if (!dbPromise) dbPromise = openDbOnce()
  return dbPromise
}

function idbWrite(mode, fn) {
  return openDb().then((db) => new Promise((resolve) => {
    if (!db) return resolve(null)
    try {
      const tx = db.transaction(STORE, mode)
      const req = fn(tx.objectStore(STORE))
      // ⚠️ 这里**不能**统一写成 `req.result ?? true`（Spec24 终审 F1）。`req.result` 三种含义：
      // put → 键（真值）、delete → undefined、get → 值或 undefined。落到 get 上，"键不存在"
      // 会被 `?? true` 补成真值，takeRequest 的 `if (blob)` 于是放行一个不存在的图，
      // 再由 `new File([true], ...)` 造出浏览器里 4 字节的假 File —— §14 陷阱 6 的护栏白设。
      // 成功与否由"有没有走 onerror / onabort"决定，不靠 req.result 的真假。
      tx.oncomplete = () => resolve(req.result ?? (mode === 'readonly' ? null : true))
      tx.onerror = () => resolve(null)
      tx.onabort = () => resolve(null)
    } catch {
      resolve(null)
    }
  }))
}

const idbPut = (blob) => idbWrite('readwrite', (s) => s.put(blob, BLOB_KEY))
const idbTake = () => idbWrite('readonly', (s) => s.get(BLOB_KEY))
const idbDrop = () => idbWrite('readwrite', (s) => s.delete(BLOB_KEY))

// ---------- 对外三个函数 ----------

/** 暂存一条待发送内容。返回 true 表示"至少文字存下了"。 */
export async function stashRequest(text, file) {
  // ⚠️ 顺序是刻意的，**别改回 `await clearRequest()`**（Spec24 终审 F2）。
  // clearRequest() 里带着一次 `indexedDB.open`（冷启动还要走 onupgradeneeded），
  // await 它等于让"文字落盘"排在一个可能**永远不 settle** 的 IDB 打开操作后面——
  // 而 App.vue 的 onSend 要在 await stashRequest 之后才 openLogin()。真挂住的话，
  // 游客点发送就是：输入框已被 ChatInput.submit() 清空、登录层不出现、控制台没有任何报错。
  // 文本走 localStorage 是**同步**的，所以它必须先落盘；IDB 只做尾巴上的尽力而为。
  clearMeta() // 旧 meta 同步清掉 —— 同一次暂存只该有一份

  const meta = { text: text || '', ts: Date.now(), file: null }
  if (file) meta.file = { name: file.name || 'image', type: file.type || 'image/png' }

  // 到这一行为止全是同步的：函数返回时这几个字节已经在盘上了。
  if (!writeMeta(meta)) return false // 文字都没落盘 → 不留半截状态

  if (file) {
    const ok = await idbPut(file)
    // ⚠️ Spec24 §14 陷阱 6：图没存下时必须把 meta.file **抹掉**，
    // 否则 takeRequest 会去 IDB 找一个不存在的 Blob。抹掉这一步在 await 之后，
    // 所以它只保证"最终一致"——真正的护栏是上面 F1 那条（读不到就降级成 null）。
    if (!ok) writeMeta({ ...meta, file: null })
  } else {
    // 这次没有图 → 顺手清掉上一次留下的孤儿 Blob，否则它会一直躺在那
    await idbDrop()
  }
  return true
}

/**
 * 取出暂存内容并清空（读完即清）。
 * 过期 / 不存在 / 解析失败 → 一律返回 null。
 * @returns {Promise<{text: string, file: File|null}|null>}
 */
export async function takeRequest() {
  const meta = readMeta()
  if (!meta) return null

  if (typeof meta.ts !== 'number' || Date.now() - meta.ts > TTL_MS) {
    await clearRequest() // Spec24 §2.5：过期即清，不给下一次机会
    return null
  }

  let file = null
  if (meta.file) {
    const blob = await idbTake()
    if (blob) {
      try {
        file = new File([blob], meta.file.name, { type: meta.file.type })
      } catch {
        file = null // 老浏览器没有 File 构造器 → 降级成只回填文字
      }
    }
  }

  await clearRequest()
  return { text: meta.text || '', file }
}

/** 清空暂存（两处都清）。任何失败都吞掉。 */
export async function clearRequest() {
  clearMeta()
  await idbDrop()
}
