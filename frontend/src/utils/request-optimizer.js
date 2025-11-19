/**
 * 请求优化工具：防抖、节流、请求去重
 */

// 请求去重：防止相同请求并发执行
const pendingRequests = new Map()

/**
 * 请求去重：如果相同的请求正在执行，返回同一个Promise
 * @param {string} key - 请求唯一标识
 * @param {Function} requestFn - 请求函数
 * @returns {Promise}
 */
export function dedupeRequest(key, requestFn) {
  if (pendingRequests.has(key)) {
    return pendingRequests.get(key)
  }
  
  const promise = requestFn()
    .finally(() => {
      pendingRequests.delete(key)
    })
  
  pendingRequests.set(key, promise)
  return promise
}

// 防抖函数
export function debounce(func, wait) {
  let timeout
  return function executedFunction(...args) {
    const later = () => {
      clearTimeout(timeout)
      func(...args)
    }
    clearTimeout(timeout)
    timeout = setTimeout(later, wait)
  }
}

// 节流函数
export function throttle(func, limit) {
  let inThrottle
  return function executedFunction(...args) {
    if (!inThrottle) {
      func.apply(this, args)
      inThrottle = true
      setTimeout(() => (inThrottle = false), limit)
    }
  }
}

// 生成请求唯一键
export function generateRequestKey(method, url, params = {}) {
  const sortedParams = Object.keys(params)
    .sort()
    .map(key => `${key}=${JSON.stringify(params[key])}`)
    .join('&')
  return `${method}:${url}${sortedParams ? '?' + sortedParams : ''}`
}


