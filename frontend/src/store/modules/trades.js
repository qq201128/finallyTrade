import api from '@/services/api'
import wsService from '@/services/websocket'

const state = {
  positions: [],  // 持仓列表
  orders: [],     // 订单列表
  pnlRecords: [],  // 盈亏记录
  totalRealizedPnl: 0,  // 总已实现盈亏
  loadingPositions: false,  // 加载状态标记，防止重复请求
  loadingOrders: false
}

const mutations = {
  SET_POSITIONS(state, positions) {
    if (!Array.isArray(positions)) {
      state.positions = []
      return
    }
    // 过滤掉已平仓的持仓，只保留未平仓的
    state.positions = positions.filter(p => p.is_open !== false && p.is_open !== 0)
  },
  SET_LOADING_POSITIONS(state, loading) {
    state.loadingPositions = loading
  },
  SET_LOADING_ORDERS(state, loading) {
    state.loadingOrders = loading
  },
  UPDATE_POSITIONS(state, positions) {
    // WebSocket 推送的持仓更新（通常是部分更新）
    if (Array.isArray(positions)) {
      positions.forEach(newPos => {
        const index = state.positions.findIndex(p => p.id === newPos.id)
        
        // 如果持仓已平仓（is_open=false），从列表中移除
        if (newPos.is_open === false || newPos.is_open === 0) {
          if (index > -1) {
            state.positions.splice(index, 1)
            console.log(`持仓 ${newPos.id} 已平仓，从列表中移除`)
          }
          return
        }
        
        if (index > -1) {
          const oldPos = state.positions[index]
          const fieldsToCompare = [
            'current_price',
            'entry_price',
            'unrealized_pnl',
            'size',
            'side',
            'leverage',
            'is_open',
            'margin_used',
            'pnl_percentage'
          ]
          const hasDiff = fieldsToCompare.some(field => oldPos[field] !== newPos[field])
          if (hasDiff) {
            state.positions[index] = { ...oldPos, ...newPos }
          }
        } else {
          // 只添加未平仓的持仓
          if (newPos.is_open !== false && newPos.is_open !== 0) {
            state.positions.push(newPos)
          }
        }
      })
    } else if (positions && positions.id) {
      // 单个更新：更新特定持仓
      const index = state.positions.findIndex(p => p.id === positions.id)
      
      // 如果持仓已平仓，从列表中移除
      if (positions.is_open === false || positions.is_open === 0) {
        if (index > -1) {
          state.positions.splice(index, 1)
          console.log(`持仓 ${positions.id} 已平仓，从列表中移除`)
        }
        return
      }
      
      if (index > -1) {
        state.positions[index] = { ...state.positions[index], ...positions }
      } else {
        // 只添加未平仓的持仓
        if (positions.is_open !== false && positions.is_open !== 0) {
          state.positions.push(positions)
        }
      }
    }
  },
  SET_ORDERS(state, orders) {
    state.orders = orders
  },
  UPDATE_ORDERS(state, orders) {
    // 更新订单数据（来自 WebSocket）
    if (Array.isArray(orders)) {
      state.orders = orders
    } else {
      const index = state.orders.findIndex(o => o.id === orders.id)
      if (index > -1) {
        state.orders[index] = { ...state.orders[index], ...orders }
      } else {
        state.orders.push(orders)
      }
    }
  },
  SET_PNL_RECORDS(state, records) {
    state.pnlRecords = records
  },
  SET_TOTAL_REALIZED_PNL(state, total) {
    state.totalRealizedPnl = total
  }
}

const actions = {
  async fetchPositions({ commit, state }, fast = true) {
    // 如果正在加载，避免重复请求
    if (state.loadingPositions) {
      return Promise.resolve()
    }
    
    try {
      commit('SET_LOADING_POSITIONS', true)
      const response = await api.get('/trades/positions', { 
        params: { fast: fast } 
      })
      commit('SET_POSITIONS', response.data)
    } catch (error) {
      console.error('获取持仓失败:', error)
    } finally {
      commit('SET_LOADING_POSITIONS', false)
    }
  },
  
  async fetchOrders({ commit, state }, status = null) {
    // 如果正在加载，避免重复请求
    if (state.loadingOrders) {
      return Promise.resolve()
    }
    
    try {
      commit('SET_LOADING_ORDERS', true)
      const params = status ? { status } : {}
      const response = await api.get('/trades/orders', { params })
      commit('SET_ORDERS', response.data)
    } catch (error) {
      console.error('获取订单失败:', error)
    } finally {
      commit('SET_LOADING_ORDERS', false)
    }
  },
  
  async fetchPnLRecords({ commit }, limit = 100) {
    try {
      const response = await api.get('/trades/pnl', { params: { limit } })
      commit('SET_PNL_RECORDS', response.data)
    } catch (error) {
      console.error('获取盈亏记录失败:', error)
    }
  },
  
  async fetchTotalRealizedPnl({ commit }) {
    try {
      const response = await api.get('/trades/pnl/total')
      commit('SET_TOTAL_REALIZED_PNL', response.data.total_realized_pnl)
    } catch (error) {
      console.error('获取总已实现盈亏失败:', error)
    }
  },

  /**
   * 手动平仓
   */
  async closePosition({ commit, dispatch }, positionId) {
    try {
      const response = await api.post(`/trades/positions/${positionId}/close`)
      // 平仓成功后，刷新持仓列表
      await dispatch('fetchPositions')
      return { success: true, data: response.data }
    } catch (error) {
      console.error('平仓失败:', error)
      return { 
        success: false, 
        error: error.response?.data?.detail || error.message || '平仓失败' 
      }
    }
  },

  /**
   * 连接持仓 WebSocket
   */
  connectPositionsWebSocket({ commit, rootState }, userId) {
    // WebSocket 需要直接连接到后端，不能通过 Vue CLI 代理
    // 从环境变量或配置中获取后端地址，默认使用 localhost:8000
    const backendHost = process.env.VUE_APP_BACKEND_HOST || 'localhost:8000'
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${backendHost}/api/ws`
    
    console.log('WebSocket URL:', wsUrl)
    
    // 订阅持仓更新
    const handlePositionsUpdate = (data) => {
      console.log('收到持仓更新:', data)
      if (data && data.type === 'positions' && data.data !== undefined) {
        // 确保 data.data 是数组
        const positionsData = Array.isArray(data.data) ? data.data : []
        commit('UPDATE_POSITIONS', positionsData)
      }
    }
    
    wsService.subscribe('positions', handlePositionsUpdate)
    wsService.connect(wsUrl, 'positions', userId)
  },

  /**
   * 连接订单 WebSocket
   */
  connectOrdersWebSocket({ commit, rootState }, userId) {
    const backendHost = process.env.VUE_APP_BACKEND_HOST || 'localhost:8000'
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${backendHost}/api/ws`
    
    const handleOrdersUpdate = (data) => {
      if (data.type === 'orders' && data.data) {
        commit('UPDATE_ORDERS', data.data)
      }
    }
    
    wsService.subscribe('orders', handleOrdersUpdate)
    wsService.connect(wsUrl, 'orders', userId)
  },

  /**
   * 断开 WebSocket 连接
   */
  disconnectWebSocket() {
    wsService.disconnect()
  }
}

export default {
  namespaced: true,
  state,
  mutations,
  actions
}

