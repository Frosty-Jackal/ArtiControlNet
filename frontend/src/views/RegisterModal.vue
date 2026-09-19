<template>
  <div class="reg-overlay" @click.self="close">
    <div class="reg-card" role="dialog" aria-modal="true" aria-label="新用户注册">
      <button class="reg-close" title="关闭" @click="close">×</button>

      <!-- 提交成功：整卡换成结果面板，用户自己关掉（不自动关，让他看清提示） -->
      <template v-if="done">
        <h2 class="reg-title">申请已提交</h2>
        <p class="reg-done-text">
          已通知管理员，在30秒内会通过短信/邮件告知您注册结果。
        </p>
        <button class="btn-primary reg-submit" @click="close">关闭</button>
      </template>

      <template v-else>
        <h2 class="reg-title">新用户注册</h2>

        <form class="reg-form" @submit.prevent="submit">
          <label class="reg-label">账号 <b class="reg-star">*</b></label>
          <input v-model="username" class="login-input" placeholder="2~32 个字符" autocomplete="off" />

          <label class="reg-label">密码 <b class="reg-star">*</b></label>
          <input v-model="password" type="password" class="login-input"
                 placeholder="至少 6 位" autocomplete="new-password" />

          <label class="reg-label">联系方式 <b class="reg-star">*</b></label>
          <p class="reg-hint">手机号与邮箱至少填一项，注册成功会联系到您</p>
          <input v-model="phone" class="login-input" placeholder="手机号（11 位数字）" autocomplete="off" />
          <input v-model="email" class="login-input" placeholder="邮箱" autocomplete="off" />

          <div class="reg-pay">
            <p class="reg-pay-title">{{ config.price_notice }}</p>
            <img class="reg-qr" :src="config.qr_url" alt="收款码" />
          </div>

          <!-- 标签直接用完整的那句话（与 RechargeModal 同一次改版），占位提示随之删掉。
               注意此处用词是「以便后台核对」，充值面板那份是「便于我们核对」——
               两处**故意不同**，是用户分别给的原文，别顺手"统一"。 -->
          <label class="reg-label">用于支付的微信昵称（以便后台核对） <b class="reg-star">*</b></label>
          <input v-model="wechat" class="login-input" autocomplete="off" />

          <p class="reg-note">{{ config.daily_notice }}</p>
          <p v-if="error" class="login-error">{{ error }}</p>
          <button class="btn-primary reg-submit" type="submit" :disabled="loading">
            {{ loading ? '提交中…' : '提交申请' }}
          </button>
        </form>
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { submitRegisterRequest } from '../api/chatApi'

defineProps({
  // 来自 GET /api/auth/register-config：客服邮箱与两句提示语**零副本**，
  // 一律显示后端回传的值（与 Spec18 的 QUOTA_EXCEEDED_MESSAGE 同一原则）
  config: { type: Object, required: true }
})
const emit = defineEmits(['close'])

const username = ref('')
const password = ref('')
const phone = ref('')
const email = ref('')
const wechat = ref('')
const error = ref('')
const loading = ref(false)
const done = ref(false)

function close() {
  // 关闭不重置 done：再来一次就重开一个组件（父级的 v-if 已经保证）
  emit('close')
}

async function submit() {
  // 只拦"必填"与"二选一"——那是 * 号承诺的东西，本地拦能立刻给反馈。
  // 手机号 11 位、邮箱 @ 位置这些**不在前端复制**：它们各有自己的中文 message，
  // 已经在后端（40018）实现了一份，前端再抄一份就是第二个会漂移的副本。
  if (!username.value.trim() || !password.value || !wechat.value.trim()) {
    // 跟标签走：那个字段已经不叫「支付备注」了，报错文案不能还叫旧名字
    error.value = '请填写账号、密码与微信昵称'
    return
  }
  if (!phone.value.trim() && !email.value.trim()) {
    error.value = '手机号与邮箱请至少填写一项'
    return
  }
  error.value = ''
  loading.value = true
  try {
    await submitRegisterRequest({
      username: username.value.trim(),
      password: password.value,
      phone: phone.value.trim(),
      email: email.value.trim(),
      wechat: wechat.value.trim()
    })
    done.value = true
  } catch (e) {
    error.value = e.message || '提交失败'
  } finally {
    loading.value = false
  }
}
</script>
