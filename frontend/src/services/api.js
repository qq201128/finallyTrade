import axios from 'axios'
import store from '@/store'
import { dedupeRequest, generateRequestKey } from '@/utils/request-optimizer'

const api = axios.create({
  baseURL: '/api',
  timeout: 10000
})

// 请求拦截器
api.interceptors.request.use(
  config => {
    const token = store.state.auth.token
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  error => {
    return Promise.reject(error)
  }
)

// 响应拦截器
api.interceptors.response.use(
  response => response,
  error => {
    // 登录接口的 401 错误不应该触发跳转（这是正常的登录失败）
    const isLoginRequest = error.config?.url?.includes('/auth/login')
    
    if (error.response?.status === 401 && !isLoginRequest) {
      // 只有在非登录接口的 401 错误才跳转到登录页（表示 token 过期或无效）
      store.dispatch('auth/logout')
      // 检查当前是否已经在登录页，避免重复跳转
      if (window.location.pathname !== '/login') {
      window.location.href = '/login'
      }
    }
    return Promise.reject(error)
  }
)

// 针对高频接口的请求去抖 + 批处理
const DEBOUNCE_ENDPOINTS = {
  '/trades/positions': 200,
  '/trades/orders': 200
}

const debounceQueues = new Map()

function enqueueDebouncedRequest(key, wait, executor) {
  if (!debounceQueues.has(key)) {
    debounceQueues.set(key, { timer: null, queue: [] })
  }
  const bucket = debounceQueues.get(key)

  return new Promise((resolve, reject) => {
    bucket.queue.push({ resolve, reject })
    clearTimeout(bucket.timer)
    bucket.timer = setTimeout(async () => {
      const queue = bucket.queue.slice()
      debounceQueues.delete(key)
      try {
        const result = await executor()
        queue.forEach(item => item.resolve(result))
      } catch (error) {
        queue.forEach(item => item.reject(error))
      }
    }, wait)
  })
}

// 包装API方法，添加请求去重 + 去抖
const originalGet = api.get
api.get = function(url, config = {}) {
  const requestKey = generateRequestKey('GET', url, config.params || {})
  const executor = () => dedupeRequest(requestKey, () => originalGet.call(this, url, config))

  if (DEBOUNCE_ENDPOINTS[url]) {
    const debounceKey = `${requestKey}:debounced`
    return enqueueDebouncedRequest(debounceKey, DEBOUNCE_ENDPOINTS[url], executor)
  }

  return executor()
}

export default api

