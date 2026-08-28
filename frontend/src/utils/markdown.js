// 助手文本的 Markdown 渲染（marked 解析 + DOMPurify 清洗，防 XSS）
//
// 注意：marked 自 v4 起不内置 sanitize，模型输出不可信，
// 必须先解析再经 DOMPurify 过滤后才能 v-html。

import { marked } from 'marked'
import DOMPurify from 'dompurify'

marked.setOptions({
  gfm: true, // GitHub 风格（表格、删除线、任务列表）
  breaks: true, // 单换行 → <br>，适合聊天流式输出
  langPrefix: 'language-'
})

// 链接统一新标签打开 + noopener，防 tab-nabbing
DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName === 'A') {
    node.setAttribute('target', '_blank')
    node.setAttribute('rel', 'noopener noreferrer')
  }
})

/** 模型文本 → 安全 HTML；空串原样返回。 */
export function renderMarkdown(text) {
  if (!text) return ''
  return DOMPurify.sanitize(marked.parse(text))
}
