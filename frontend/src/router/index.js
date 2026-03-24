import { createRouter, createWebHistory } from 'vue-router'
import DrawingWorkspace from '../views/DrawingWorkspace.vue'

const routes = [
  {
    path: '/',
    name: 'DrawingWorkspace',
    component: DrawingWorkspace
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
