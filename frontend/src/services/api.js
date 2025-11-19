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
    if (error.response?.status === 401) {
      store.dispatch('auth/logout')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

// 包装API方法，添加请求去重功能（仅对GET请求）
const originalGet = api.get
api.get = function(url, config = {}) {
  // 只对GET请求进行去重
  const requestKey = generateRequestKey('GET', url, config.params)
  
  return dedupeRequest(requestKey, () => {
    return originalGet.call(this, url, config)
  })
}

export default api

