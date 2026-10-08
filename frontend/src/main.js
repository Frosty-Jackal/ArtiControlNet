import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import './assets/styles/main.css'

// index.html 的 #app 里有一段静态开场内容（给搜索引擎爬虫看的，见那边的注释）。
// Vue 3 挂载时**不会**清空容器里的既有 DOM（runtime 里没有 innerHTML = ''，
// 唯一的 container.innerHTML 用法只对无 render 函数的 in-DOM 模板生效），
// 不清掉的话那段开场屏会永远留在页面顶部。必须在挂载前手动清。
const container = document.getElementById('app')
container.innerHTML = ''

createApp(App).use(createPinia()).mount(container)
