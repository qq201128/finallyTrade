/**
 * WebSocket 服务
 * 用于接收实时数据更新
 */

class WebSocketService {
  constructor() {
    this.connections = new Map() // 存储多个连接，key 为 type
    this.reconnectAttempts = new Map() // 每个连接的重连次数
    this.maxReconnectAttempts = 5
    this.reconnectInterval = 3000
    this.listeners = new Map()
    this.isConnecting = new Map() // 每个连接的连接状态
  }

  /**
   * 连接 WebSocket
   * @param {string} url - WebSocket URL
   * @param {string} type - 连接类型 ('positions' 或 'orders')
   * @param {number} userId - 用户ID
   */
  connect(url, type, userId) {
    // 检查是否已有连接
    const existingWs = this.connections.get(type)
    if (this.isConnecting.get(type) || (existingWs && existingWs.readyState === WebSocket.OPEN)) {
      console.log(`WebSocket ${type} 已连接或正在连接中`)
      return
    }

    // 如果已有连接但已关闭，先关闭
    if (existingWs) {
      existingWs.close()
      this.connections.delete(type)
    }

    this.isConnecting.set(type, true)
    const wsUrl = `${url}/${type}/${userId}`
    console.log(`正在连接 WebSocket: ${wsUrl}`)

    try {
      const ws = new WebSocket(wsUrl)
      this.connections.set(type, ws)

      ws.onopen = () => {
        console.log(`WebSocket ${type} 连接成功`)
        this.isConnecting.set(type, false)
        this.reconnectAttempts.set(type, 0)
      }

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          this.handleMessage(type, data)
        } catch (error) {
          console.error(`解析 WebSocket ${type} 消息失败:`, error)
        }
      }

      ws.onerror = (error) => {
        console.error(`WebSocket ${type} 错误:`, error)
        this.isConnecting.set(type, false)
      }

      ws.onclose = () => {
        console.log(`WebSocket ${type} 连接关闭`)
        this.isConnecting.set(type, false)
        this.connections.delete(type)
        
        // 自动重连
        const attempts = this.reconnectAttempts.get(type) || 0
        if (attempts < this.maxReconnectAttempts) {
          const newAttempts = attempts + 1
          this.reconnectAttempts.set(type, newAttempts)
          console.log(`尝试重连 WebSocket ${type} (${newAttempts}/${this.maxReconnectAttempts})...`)
          setTimeout(() => {
            this.connect(url, type, userId)
          }, this.reconnectInterval)
        } else {
          console.error(`WebSocket ${type} 重连失败，已达到最大重试次数`)
          this.reconnectAttempts.delete(type)
        }
      }
    } catch (error) {
      console.error(`创建 WebSocket ${type} 连接失败:`, error)
      this.isConnecting.set(type, false)
    }
  }

  /**
   * 处理接收到的消息
   */
  handleMessage(type, data) {
    const listeners = this.listeners.get(type) || []
    listeners.forEach(listener => {
      try {
        listener(data)
      } catch (error) {
        console.error(`处理 WebSocket ${type} 消息失败:`, error)
      }
    })
  }

  /**
   * 订阅消息
   * @param {string} type - 消息类型
   * @param {Function} callback - 回调函数
   */
  subscribe(type, callback) {
    if (!this.listeners.has(type)) {
      this.listeners.set(type, [])
    }
    this.listeners.get(type).push(callback)
  }

  /**
   * 取消订阅
   * @param {string} type - 消息类型
   * @param {Function} callback - 回调函数
   */
  unsubscribe(type, callback) {
    if (this.listeners.has(type)) {
      const listeners = this.listeners.get(type)
      const index = listeners.indexOf(callback)
      if (index > -1) {
        listeners.splice(index, 1)
      }
    }
  }

  /**
   * 断开指定类型的连接
   * @param {string} type - 连接类型，如果不提供则断开所有连接
   */
  disconnect(type = null) {
    if (type) {
      const ws = this.connections.get(type)
      if (ws) {
        ws.close()
        this.connections.delete(type)
      }
      this.listeners.delete(type)
      this.reconnectAttempts.delete(type)
      this.isConnecting.delete(type)
    } else {
      // 断开所有连接
      this.connections.forEach((ws, t) => {
        ws.close()
      })
      this.connections.clear()
      this.listeners.clear()
      this.reconnectAttempts.clear()
      this.isConnecting.clear()
    }
  }
}

// 创建单例
const wsService = new WebSocketService()

export default wsService

