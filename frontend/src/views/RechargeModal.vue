<template>
  <div class="reg-overlay" @click.self="close">
    <div class="reg-card" role="dialog" aria-modal="true" aria-label="余额与充值">
      <button class="reg-close" title="关闭" @click="close">×</button>

      <!-- 提交成功：整卡换成结果面板，用户自己关掉（不自动关，让他看清提示）。
           **零分支**：首次提交与幂等命中（冷却期过后的重复提交）显示同一句话，前端不区分。
           冷却期内的重复提交走不到这里——那是 40905，只有一句 window.alert（见 submit）。 -->
      <template v-if="done">
        <h2 class="reg-title">充值申请已提交</h2>
        <p class="reg-done-text">
          充值金额会在30秒内到账。
        </p>
        <button class="btn-primary reg-submit" @click="close">关闭</button>
      </template>

      <template v-else>
        <h2 class="reg-title">余额与充值</h2>

        <!-- 余额行：仅 mode="user"（欠费面板拿不到余额，它连 token 都没有） -->
        <p v-if="mode !== 'overdue' && balance !== null" class="rc-balance">
          当前余额 <b>{{ balance }}</b> 元
        </p>

        <form class="reg-form" @submit.prevent="submit">
          <!-- 收款码：两个模式的图与备注都来自后端，前端零副本。
               裂图（部署时忘了放 Server/payment.jpg → 40410）不额外处理，
               用户照常能提交申请，线下联系时再收款（Spec21 §7.3）。 -->
          <div class="reg-pay">
            <img v-if="qrUrl" class="reg-qr rc-qr" :src="qrUrl" alt="收款码" />
            <!-- Spec23 §2.8：参考价改成"排版片段"。片段里的 strike 为真时套一层 <s>
                 （删除线）——划线位置是**后端给的数据**，不是前端在前缀里找 "0.9"。
                 没有 v-html：那是个 XSS 面，而这句话里有服务端可控的数字。 -->
            <p v-if="priceLine.length" class="reg-pay-title rc-note">
              <template v-for="(seg, i) in priceLine" :key="i"
                ><s v-if="seg.strike">{{ seg.text }}</s><template v-else>{{ seg.text }}</template></template>
            </p>
          </div>

          <!-- 账号输入框：仅 mode="overdue"。登录页被踢出来的场景由 App.vue
               把 auth.username 带过来预填，全新浏览器打开时手工填 -->
          <template v-if="mode === 'overdue'">
            <label class="reg-label">账号 <b class="reg-star">*</b></label>
            <input v-model="account" class="login-input" placeholder="要充值的账号" autocomplete="off" />
          </template>

          <!-- 标签直接用完整的那句话（用户后来的口径）：原标题「支付备注」太笼统，
               而它本来就要靠占位提示才说得清——两行说同一件事，不如把话说全在标签上，
               占位提示随之删掉（留一个输入框，光标进去就能打字）。 -->
          <label class="reg-label">用于支付的微信昵称（便于我们核对） <b class="reg-star">*</b></label>
          <input v-model="wechat" class="login-input" autocomplete="off" />

          <p v-if="error" class="login-error">{{ error }}</p>
          <button class="btn-primary reg-submit" type="submit" :disabled="loading">
            {{ loading ? '提交中…' : '我已完成充值' }}
          </button>
        </form>
      </template>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { getRechargeInfo, getRegisterConfig, submitOverdueRecharge, submitRecharge } from '../api/chatApi'

const props = defineProps({
  // 'user'    = 顶部「余额与充值」按钮（带 token，能拿余额）
  // 'overdue' = 登录页的欠费充值面板（没 token，数据源换成公开的 register-config）
  mode: { type: String, default: 'user' },
  // 仅 mode="overdue" 用：预填的账号（被强制退出时由 App.vue 带过来）
  username: { type: String, default: '' }
})
const emit = defineEmits(['close'])

const account = ref(props.username)
const wechat = ref('')
const balance = ref(null)
const qrUrl = ref('')
// 参考价两个模式**故意不同**（Spec21 §7.3）：前者出自需求 4 的原话，后者出自需求 6 的原话。
// Spec23 §2.8：两边都是"排版片段数组"（形状一致，所以下面两个分支共用一份渲染），
// 只有 /api/recharge/info 那份带一个 strike 片段。
// 两句都来自后端，前端一个字的文案副本都不放。
const priceLine = ref([])
const error = ref('')
const loading = ref(false)
const done = ref(false)

function close() {
  // 关闭不重置 done：再来一次就重开一个组件（父级的 v-if 已经保证）
  emit('close')
}

onMounted(async () => {
  try {
    if (props.mode === 'overdue') {
      // 复用**已有的**公开端点：不用写死 /api/auth/payment-qr 路径，也不用抄一份文案。
      // register-config 永远返回 200（即使 REGISTER_ENABLED=false），欠费用户拿得到。
      const cfg = await getRegisterConfig()
      qrUrl.value = cfg.qr_url
      priceLine.value = cfg.price_line
    } else {
      const info = await getRechargeInfo()
      qrUrl.value = info.qr_url
      priceLine.value = info.price_line
      balance.value = info.balance
    }
  } catch (e) {
    error.value = e.message || '加载失败'
  }
})

async function submit() {
  // 只拦"必填"——那是 * 号承诺的东西，本地拦能立刻给反馈。
  // 昵称长度等规则**不在前端复制**：它们在 40018/40019 各有一份中文 message（Spec21 §7.3）。
  const acct = account.value.trim()
  const wx = wechat.value.trim()
  if (props.mode === 'overdue' && (!acct || !wx)) {
    error.value = '请填写账号与微信昵称'
    return
  }
  if (!wx) {
    error.value = '请填写微信昵称'
    return
  }
  error.value = ''
  loading.value = true
  try {
    if (props.mode === 'overdue') await submitOverdueRecharge(acct, wx)
    else await submitRecharge(wx)
    done.value = true
  } catch (e) {
    // 冷却期内又点了一次（40905）：**跳出告警**，不写红色提示行。
    // 这里与登录页那处刻意相反——那边删 alert 是因为它会挡住背后的充值面板；
    // 这里没有"背后的东西"要护着，而这句话本身就是"先别急"的强提醒，alert 正合适。
    // 文案来自后端（前端零副本）：`e.message` 就是 config 里那句。
    if (e.code === 40905) {
      window.alert(e.message)
      return
    }
    error.value = e.message || '提交失败'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
/* Spec21 §7.3 的布局指定收款码 max-height 220px（.reg-qr 是固定 width: 200px） */
.rc-qr {
  max-height: 220px;
  object-fit: contain;
}

/* 备注排在收款码**下方**（与 RegisterModal 的上下相反，按 Spec21 §7.3 的布局图） */
.rc-note {
  margin-top: 10px;
}

.rc-balance {
  text-align: center;
  font-size: 14px;
  color: var(--text-secondary);
  margin-bottom: 8px;
}

.rc-balance b {
  font-size: 18px;
  color: var(--purple-300);
}
</style>
