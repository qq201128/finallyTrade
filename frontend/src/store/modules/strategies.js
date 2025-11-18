import api from '@/services/api'

const state = {
  strategies: [],
  userStrategies: [],
  strategyFiles: [],
  exchanges: []  // 可用交易所列表
}

const mutations = {
  SET_STRATEGIES(state, strategies) {
    state.strategies = strategies
  },
  SET_USER_STRATEGIES(state, userStrategies) {
    state.userStrategies = userStrategies
  },
  SET_STRATEGY_FILES(state, files) {
    state.strategyFiles = files
  },
  SET_EXCHANGES(state, exchanges) {
    state.exchanges = exchanges
  },
  ADD_USER_STRATEGY(state, strategy) {
    state.userStrategies.push(strategy)
  },
  UPDATE_USER_STRATEGY(state, strategy) {
    const index = state.userStrategies.findIndex(s => s.id === strategy.id)
    if (index !== -1) {
      state.userStrategies[index] = strategy
    }
  },
  REMOVE_USER_STRATEGY(state, id) {
    state.userStrategies = state.userStrategies.filter(s => s.id !== id)
  }
}

const actions = {
  async fetchStrategies({ commit }) {
    try {
      const response = await api.get('/strategies/')
      commit('SET_STRATEGIES', response.data)
    } catch (error) {
      console.error('获取策略列表失败:', error)
    }
  },
  
  async fetchStrategyFiles({ commit }) {
    try {
      const response = await api.get('/strategies/files')
      commit('SET_STRATEGY_FILES', response.data)
    } catch (error) {
      console.error('获取策略文件失败:', error)
    }
  },
  
  async fetchExchanges({ commit }) {
    try {
      const response = await api.get('/strategies/exchanges')
      commit('SET_EXCHANGES', response.data)
    } catch (error) {
      console.error('获取交易所列表失败:', error)
    }
  },
  
  async fetchUserStrategies({ commit }) {
    try {
      const response = await api.get('/strategies/user')
      commit('SET_USER_STRATEGIES', response.data)
    } catch (error) {
      console.error('获取用户策略失败:', error)
    }
  },
  
  async createUserStrategy({ commit }, strategyData) {
    try {
      const response = await api.post('/strategies/user', strategyData)
      commit('ADD_USER_STRATEGY', response.data)
      return { success: true, data: response.data }
    } catch (error) {
      return { success: false, error: error.response?.data?.detail || '创建失败' }
    }
  },
  
  async updateUserStrategy({ commit }, { id, data }) {
    try {
      const response = await api.put(`/strategies/user/${id}`, data)
      commit('UPDATE_USER_STRATEGY', response.data)
      return { success: true }
    } catch (error) {
      return { success: false, error: error.response?.data?.detail || '更新失败' }
    }
  },
  
  async deleteUserStrategy({ commit }, id) {
    try {
      await api.delete(`/strategies/user/${id}`)
      commit('REMOVE_USER_STRATEGY', id)
      return { success: true }
    } catch (error) {
      return { success: false, error: error.response?.data?.detail || '删除失败' }
    }
  }
}

export default {
  namespaced: true,
  state,
  mutations,
  actions
}

