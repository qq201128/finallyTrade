import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import store from './store'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'

// 抑制 ResizeObserver 警告（这是一个已知的浏览器警告，不影响功能）
const resizeObserverLoopErrRe = /ResizeObserver/
const originalError = console.error
const originalWarn = console.warn

console.error = (...args) => {
  const errorMessage = args[0]?.toString() || ''
  if (resizeObserverLoopErrRe.test(errorMessage)) {
    return
  }
  originalError.apply(console, args)
}

console.warn = (...args) => {
  const warnMessage = args[0]?.toString() || ''
  if (resizeObserverLoopErrRe.test(warnMessage)) {
    return
  }
  originalWarn.apply(console, args)
}

// 捕获全局错误并过滤 ResizeObserver
window.addEventListener('error', (event) => {
  if (event.message && resizeObserverLoopErrRe.test(event.message)) {
    event.preventDefault()
    return false
  }
}, true)

// 捕获未处理的 Promise 拒绝
window.addEventListener('unhandledrejection', (event) => {
  if (event.reason && event.reason.toString && resizeObserverLoopErrRe.test(event.reason.toString())) {
    event.preventDefault()
    return false
  }
})

// 主题初始化：从 localStorage 读取，默认深色
const savedTheme = localStorage.getItem('theme') || 'dark'
document.documentElement.classList.add(savedTheme)

const app = createApp(App)

// 注册Element Plus图标
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.use(store)
app.use(router)
app.use(ElementPlus)
app.mount('#app')

