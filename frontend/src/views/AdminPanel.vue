<template>
  <div class="admin-panel">
    <div class="admin-head">
      <h2>用户管理</h2>
      <button class="btn-clear" @click="emit('close')">返回聊天</button>
    </div>
    <!-- Spec19 §7.5a：原文案"无公开注册"不再成立——注册申请与审批已上线。
         待审批条数写进这一行，免得管理员每次都要滚过用户表才知道有没有活干。 -->
    <p class="admin-tip">
      当前登录：{{ auth.username }}（{{ auth.isAdmin ? '管理员' : '普通用户' }}）
      · 账号可由管理员创建，或由用户申请后审批开通
      · <b class="tip-pending">待审批注册申请 {{ pendingCount }} 条</b>
      · <b class="tip-pending">待审批充值 {{ pendingRechargeCount }} 条</b>
    </p>

    <!-- 创建账号 -->
    <form class="admin-create" @submit.prevent="create">
      <input
        v-model="newName"
        class="login-input"
        placeholder="新用户名（≥2 字符）"
        autocomplete="off"
      />
      <input
        v-model="newPass"
        type="password"
        class="login-input"
        placeholder="初始密码（≥6 位）"
        autocomplete="new-password"
      />
      <button class="btn-primary" type="submit" :disabled="creating">
        {{ creating ? '创建中…' : '创建账号' }}
      </button>
    </form>

    <p v-if="error" class="login-error">{{ error }}</p>
    <p v-if="notice" class="admin-notice">{{ notice }}</p>

    <!-- 用户表格 -->
    <div class="admin-table-wrap">
      <table class="user-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>用户名</th>
            <th>角色</th>
            <th>联系方式</th>
            <th>服务总调用次数</th>
            <th>服务限额</th>
            <th>创建时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="u in users" :key="u.id">
            <td>{{ u.id }}</td>
            <td>
              {{ u.username }}
              <span v-if="u.username === auth.username" class="me-tag">我</span>
            </td>
            <td>
              <span :class="u.is_admin ? 'role-admin' : 'role-normal'">
                {{ u.is_admin ? '管理员' : '普通' }}
              </span>
            </td>
            <!-- Spec21 §7.2：联系方式（邮箱 / 电话，都没有 → 「无」） -->
            <td class="cell-contact">{{ contactText(u) }}</td>
            <!-- Spec18 §7.5b：超额只打标记，不整行变红（那会让表格看起来全是错的） -->
            <td class="cell-quota">
              {{ u.used }}
              <span v-if="isOverQuota(u)" class="quota-over-tag">已超额</span>
            </td>
            <td class="cell-quota">
              <!-- 管理员恒不判限额（§2.1），给一个改了没用的输入框是骗人 -->
              <template v-if="u.is_admin">
                <span class="cell-muted">不受限</span>
              </template>
              <template v-else>
                {{ u.quota_limit }}
                <button class="btn-mini" :disabled="busyId === u.id" @click="editQuota(u)">
                  改限额
                </button>
              </template>
            </td>
            <!-- Spec21 §7.2：北京时间（后端另给的 created_at_beijing，created_at 本身没被改） -->
            <td class="cell-muted">{{ u.created_at_beijing }}</td>
            <td class="row-actions">
              <button class="btn-mini" :disabled="busyId === u.id" @click="resetPassword(u)">
                重置密码
              </button>
              <button
                class="btn-mini"
                :disabled="busyId === u.id"
                @click="toggleAdmin(u)"
              >
                {{ u.is_admin ? '撤销管理员' : '设为管理员' }}
              </button>
              <button
                class="btn-mini danger"
                :disabled="busyId === u.id || u.username === auth.username"
                title="不能删除自己"
                @click="remove(u)"
              >
                删除
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Spec19 §7.5b：注册申请台账。pending 在前（后端已排好序），
         已处理的原样留在下方——它们是台账，不是待办。 -->
    <section class="reg-admin">
      <h3 class="reg-admin-title">待审批注册用户</h3>
      <p v-if="requests.length === 0" class="reg-admin-empty">暂无注册申请</p>

      <div v-for="r in requests" :key="r.id" class="reg-row">
        <div class="reg-row-info">
          <span class="reg-row-user">{{ r.username }}</span>
          <!-- Spec22 §7.7：手机号那一格整行删除（库里已经没有这一列了，§5.1）——
               留一个永远显示「—」的格子比删掉更糟。邮箱现在是必填，只有 Spec22
               之前的旧申请才可能是空的（那条 pending 仍能审批，只是不发信）。 -->
          <span class="reg-row-cell">邮箱：{{ r.email || '—' }}</span>
          <span class="reg-row-cell">支付微信：{{ r.wechat }}</span>
          <span class="reg-row-cell reg-row-time">{{ r.created_at_beijing }}</span>
        </div>

        <div class="reg-row-actions">
          <template v-if="r.status === 'pending'">
            <button class="btn-mini" :disabled="busyRegId === r.id" @click="approve(r)">同意</button>
            <button class="btn-mini" :disabled="busyRegId === r.id" @click="reject(r)">拒绝</button>
          </template>
          <span v-else class="reg-row-done">
            {{ r.status === 'approved' ? '已同意' : '已拒绝' }}
          </span>
          <!-- 已处理的记录仍要能被清理，否则台账只进不出（§2.4） -->
          <button class="btn-mini danger" :disabled="busyRegId === r.id" @click="removeRequest(r)">
            删除
          </button>
        </div>
      </div>
    </section>

    <!-- Spec21 §7.2：充值台账（结构照抄上面的注册申请块）。
         同样 pending 在前、已处理的原样留在下方——它是台账，不是待办。 -->
    <section class="reg-admin">
      <h3 class="reg-admin-title">待审批充值记录</h3>
      <p v-if="recharges.length === 0" class="reg-admin-empty">暂无充值申请</p>

      <div v-for="c in recharges" :key="c.id" class="reg-row">
        <div class="reg-row-info">
          <span class="reg-row-user">{{ c.username }}</span>
          <span class="reg-row-cell">微信昵称：{{ c.wechat }}</span>
          <span class="reg-row-cell">{{ c.source === 'overdue' ? '欠费充值' : '主动充值' }}</span>
          <span v-if="c.amount !== null" class="reg-row-cell">加 {{ c.amount }} 次</span>
          <span class="reg-row-cell reg-row-time">{{ c.created_at_beijing }}</span>
        </div>

        <div class="reg-row-actions">
          <template v-if="c.status === 'pending'">
            <button class="btn-mini" :disabled="busyRechargeId === c.id" @click="approveRecharge(c)">同意</button>
            <button class="btn-mini" :disabled="busyRechargeId === c.id" @click="rejectRecharge(c)">拒绝</button>
          </template>
          <span v-else class="reg-row-done">{{ c.status === 'approved' ? '已同意' : '已拒绝' }}</span>
          <button class="btn-mini danger" :disabled="busyRechargeId === c.id" @click="removeRecharge(c)">
            删除
          </button>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import {
  approveRechargeRequest,
  approveRegisterRequest,
  createUser,
  deleteRechargeRequest,
  deleteRegisterRequest,
  deleteUser,
  listRechargeRequests,
  listRegisterRequests,
  listUsers,
  rejectRechargeRequest,
  rejectRegisterRequest,
  resetUserPassword,
  setUserAdmin,
  updateUserQuota
} from '../api/chatApi'
import { useAuthStore } from '../store/auth'

const emit = defineEmits(['close'])
const auth = useAuthStore()

const users = ref([])
const newName = ref('')
const newPass = ref('')
const error = ref('')
const notice = ref('')
const creating = ref(false)
const busyId = ref(null)

// Spec19 §7.5b：注册申请台账（pending 在前，后端已排好序）
const requests = ref([])
const busyRegId = ref(null)
const pendingCount = computed(
  () => requests.value.filter((r) => r.status === 'pending').length
)

// Spec21 §7.2：充值台账（同款：pending 在前，后端已排好序）
const recharges = ref([])
const busyRechargeId = ref(null)
const pendingRechargeCount = computed(
  () => recharges.value.filter((c) => c.status === 'pending').length
)

async function load() {
  try {
    users.value = await listUsers()
  } catch (e) {
    error.value = e.message || '加载用户列表失败'
  }
}

async function loadRequests() {
  try {
    requests.value = await listRegisterRequests()
  } catch (e) {
    error.value = e.message || '加载注册申请失败'
  }
}

async function loadRecharges() {
  try {
    recharges.value = await listRechargeRequests()
  } catch (e) {
    error.value = e.message || '加载充值记录失败'
  }
}

// Spec22 §7.7：库里已经没有任何电话了（§5.1），所以这一列只可能是邮箱或「无」。
// 「无」= 管理员手工建的号（create_user 不带 email）——**这是允许的形态**（Spec21 §3.3-6）。
function contactText(u) {
  return u.email || '无'
}

function flash(msg) {
  notice.value = msg
  setTimeout(() => (notice.value = ''), 2500)
}

async function create() {
  const name = newName.value.trim()
  const pass = newPass.value
  if (name.length < 2 || pass.length < 6) {
    error.value = '用户名至少 2 个字符，密码至少 6 位'
    return
  }
  error.value = ''
  creating.value = true
  try {
    await createUser(name, pass)
    newName.value = ''
    newPass.value = ''
    flash(`已创建账号：${name}`)
    await load()
  } catch (e) {
    error.value = e.message || '创建失败'
  } finally {
    creating.value = false
  }
}

async function resetPassword(u) {
  const pass = window.prompt(`为「${u.username}」设置新密码（至少 6 位）：`)
  if (!pass) return
  if (pass.length < 6) {
    error.value = '密码至少 6 位'
    return
  }
  error.value = ''
  busyId.value = u.id
  try {
    await resetUserPassword(u.id, pass)
    flash(`已重置「${u.username}」的密码`)
  } catch (e) {
    error.value = e.message || '重置失败'
  } finally {
    busyId.value = null
  }
}

// Spec21 §5.7：判据与后端一致（used > quota_limit），管理员恒不超额。
// 注意是 `>` 不是 `>=`：限额用满（used == limit）还能再用一次（Spec21 §2.8）。
function isOverQuota(u) {
  return !u.is_admin && u.used > u.quota_limit
}

// Spec18 §7.5：改服务限额（window.prompt，与隔壁「重置密码」同款交互）
async function editQuota(u) {
  const input = window.prompt(
    `为「${u.username}」设置服务限额（累计可用次数，当前 ${u.quota_limit}）：`,
    String(u.quota_limit)
  )
  if (input === null) return                  // 取消
  const raw = input.trim()
  const n = Number(raw)
  // raw 为空必须单独拦：Number('') === 0，是个整数——不拦的话"清空输入框直接确定"
  // 会把限额静默设成 0（= 禁用该账号）
  // 用 Number.isInteger 而非 parseInt：parseInt("25abc") 会静默变成 25，
  // 静默纠正用户的输入是坏事。
  // 上限（QUOTA_LIMIT_MAX）不在前端校验——它由后端 40017 的 message 显示在 error 行，
  // 前端复制一份就多一个会漂移的常量。
  if (!raw || !Number.isInteger(n) || n < 0) {
    error.value = '限额需为不小于 0 的整数'
    return
  }
  error.value = ''
  busyId.value = u.id
  try {
    await updateUserQuota(u.id, n)
    flash(`已将「${u.username}」的服务限额设为 ${n} 次`)
    await load()
  } catch (e) {
    error.value = e.message || '设置限额失败'
  } finally {
    busyId.value = null
  }
}

async function toggleAdmin(u) {
  const next = !u.is_admin
  if (next && !window.confirm(`确定将「${u.username}」设为管理员？`)) return
  if (!next && !window.confirm(`确定撤销「${u.username}」的管理员权限？`)) return
  error.value = ''
  busyId.value = u.id
  try {
    await setUserAdmin(u.id, next)
    flash(next ? `已将「${u.username}」设为管理员` : `已撤销「${u.username}」管理员`)
    await load()
    // 若操作的是自己，向后端同步最新权限
    if (u.username === auth.username) await auth.refresh()
  } catch (e) {
    error.value = e.message || '操作失败'
  } finally {
    busyId.value = null
  }
}

async function remove(u) {
  if (u.username === auth.username) return
  if (!window.confirm(`确定删除用户「${u.username}」？此操作不可撤销。`)) return
  error.value = ''
  busyId.value = u.id
  try {
    await deleteUser(u.id)
    flash(`已删除用户「${u.username}」`)
    await load()
  } catch (e) {
    error.value = e.message || '删除失败'
  } finally {
    busyId.value = null
  }
}

// ---- Spec19 §7.5c：注册申请的三个处理动作 ----

// 同意 = 弹框填限额（与「改限额」逐字同款交互）。
// **不传 prompt 的第二个参数**（不给默认值）：前端拿不到 QUOTA_DEFAULT_LIMIT
// （那是后端的建号默认值，没在公开配置里），写死 25 就是复制一个会漂移的常量
// ——与 Spec18 §7.5 对 QUOTA_LIMIT_MAX 的处理同一个理由。管理员填多少由他跟
// 用户的实际付款决定，本来就不该被一个前端默认值暗示。
async function approve(r) {
  // Spec22 §7.7：先说清"按下去会给申请者发一封信"这个副作用（§2.12）。
  // ⚠️ confirm 必须在 prompt **之前**——反过来的话，管理员填完额度再点"取消 confirm"，
  // 前面那次输入就白填了。请求逻辑一个字没动（两条 approve 路由的响应与错误码不变）。
  if (!window.confirm(
    `确认通过 ${r.username} 的注册申请？通过后会向 ${r.email || '（该申请没有邮箱）'} 发送一封通知邮件。`
  )) return
  const input = window.prompt(
    `同意「${r.username}」的注册申请，并设置服务限额（累计可用次数）：`
  )
  if (input === null) return                       // 取消
  const raw = input.trim()
  const n = Number(raw)
  // 与 editQuota 同样的三个坑：raw 为空必须单独拦（Number('') === 0 会让
  // "清空直接确定"静默变成限额 0 = 禁用该账号）；用 Number.isInteger 而非
  // parseInt（parseInt('25abc') 会静默变成 25）；上限交给后端 40017 报。
  if (!raw || !Number.isInteger(n) || n < 0) {
    error.value = '限额需为不小于 0 的整数'
    return
  }
  error.value = ''
  busyRegId.value = r.id
  try {
    await approveRegisterRequest(r.id, n)
    flash(`已开通账号：${r.username}`)
    // 本文件里唯一一个影响两处数据的动作：申请列表少一条待办，用户表格多一行
    await loadRequests()
    await load()
  } catch (e) {
    error.value = e.message || '审批失败'
  } finally {
    busyRegId.value = null
  }
}

async function reject(r) {
  if (!window.confirm(`确定拒绝「${r.username}」的注册申请？`)) return
  error.value = ''
  busyRegId.value = r.id
  try {
    await rejectRegisterRequest(r.id)
    flash(`已拒绝「${r.username}」的注册申请`)
    await loadRequests()
  } catch (e) {
    error.value = e.message || '操作失败'
  } finally {
    busyRegId.value = null
  }
}

async function removeRequest(r) {
  // 确认文案里**不提"账号"**：删除记录不动账号，别让管理员误会会删号
  if (!window.confirm('确定删除这条申请记录？此操作不可撤销。')) return
  error.value = ''
  busyRegId.value = r.id
  try {
    await deleteRegisterRequest(r.id)
    flash('已删除该条申请记录')
    await loadRequests()
  } catch (e) {
    error.value = e.message || '删除失败'
  } finally {
    busyRegId.value = null
  }
}

// ---- Spec21 §7.2：充值的三个处理动作 ----

// 同意 = 弹框填次数（与「同意注册申请」逐字同款交互）。
// **不传 prompt 的第二个参数**（不给默认值）：次数该由管理员按实收金额决定，
// 写死任何数字都是复制一个会漂移的常量（与 Spec19 §7.5c 同款理由）。
async function approveRecharge(c) {
  // Spec22 §7.7：先确认，并在确认里说明"通过后会向该用户邮箱发一封到账通知"。
  // 同样 confirm 在 prompt 之前（理由见 approve）。请求逻辑一个字没动。
  if (!window.confirm(
    `确认通过这笔充值（${c.username}）？通过后会向该用户邮箱发送一封到账通知。`
  )) return
  const input = window.prompt(
    `同意「${c.username}」的充值申请，并填写加多少次服务额度：`
  )
  if (input === null) return                       // 取消
  const raw = input.trim()
  const n = Number(raw)
  // 与 editQuota / approve 同样的三个坑（Spec19 §7.5c）：raw 为空必须单独拦
  // （Number('') === 0 是整数）；用 Number.isInteger 而非 parseInt
  // （parseInt('10abc') 会静默变成 10）；上限交给后端 40017 报。
  // 下界是 **1 不是 0**：加 0 次是一次无意义的点击，几乎必然是手滑（§2.5）。
  if (!raw || !Number.isInteger(n) || n < 1) {
    error.value = '充值次数需为不小于 1 的整数'
    return
  }
  error.value = ''
  busyRechargeId.value = c.id
  try {
    await approveRechargeRequest(c.id, n)
    flash(`已为「${c.username}」充值 ${n} 次`)
    // 影响两处数据：台账少一条待办，用户表格那一行的额度变了
    await loadRecharges()
    await load()
  } catch (e) {
    error.value = e.message || '充值失败'
  } finally {
    busyRechargeId.value = null
  }
}

async function rejectRecharge(c) {
  if (!window.confirm(`确定拒绝「${c.username}」的充值申请？`)) return
  error.value = ''
  busyRechargeId.value = c.id
  try {
    await rejectRechargeRequest(c.id)
    flash(`已拒绝「${c.username}」的充值申请`)
    await loadRecharges()
  } catch (e) {
    error.value = e.message || '操作失败'
  } finally {
    busyRechargeId.value = null
  }
}

async function removeRecharge(c) {
  // 确认文案必须点明"不收回额度"——删记录 ≠ 撤销充值（Spec21 §2.6）
  if (!window.confirm('确定删除这条充值记录？此操作不可撤销，且不会收回已加的服务额度。')) return
  error.value = ''
  busyRechargeId.value = c.id
  try {
    await deleteRechargeRequest(c.id)
    flash('已删除该条充值记录')
    await loadRecharges()
  } catch (e) {
    error.value = e.message || '删除失败'
  } finally {
    busyRechargeId.value = null
  }
}

// 并行拉三张表
onMounted(() => {
  load()
  loadRequests()
  loadRecharges()
})
</script>
