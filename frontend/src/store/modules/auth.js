import api from '@/services/api'

const state = {
  token: localStorage.getItem('token') || '',
  user: null,
  isAuthenticated: !!localStorage.getItem('token')
}

const mutations = {
  SET_TOKEN(state, token) {
    state.token = token
    state.isAuthenticated = !!token
    if (token) {
      localStorage.setItem('token', token)
    } else {
      localStorage.removeItem('token')
    }
  },
  SET_USER(state, user) {
    state.user = user
  }
}

const actions = {
  async login({ commit }, { username, password }) {
    try {
      const formData = new FormData()
      formData.append('username', username)
      formData.append('password', password)
      
      console.log('发送登录请求:', { username })
      
      const response = await api.post('/auth/login', formData, {
        headers: {
          'Content-Type': 'multipart/form-data'
        }
      })
      
      console.log('登录响应:', response.data)
      
      commit('SET_TOKEN', response.data.access_token)
      
      // 获取用户信息
      const userResponse = await api.get('/auth/me')
      commit('SET_USER', userResponse.data)
      
      return { success: true }
    } catch (error) {
      console.error('登录错误详情:', {
        status: error.response?.status,
        data: error.response?.data,
        message: error.message
      })
      // 错误信息映射为中文
      let errorMessage = error.response?.data?.detail || error.message || '登录失败'
      // 如果后端返回的是英文，映射为中文
      if (errorMessage === 'Incorrect username or password') {
        errorMessage = '用户名或密码错误'
      } else if (errorMessage.includes('Login failed')) {
        errorMessage = errorMessage.replace('Login failed', '登录失败')
      }
      return { success: false, error: errorMessage }
    }
  },
  
  async register({ commit }, { username, email, password }) {
    try {
      await api.post('/auth/register', { username, email, password })
      return { success: true }
    } catch (error) {
      console.error('注册错误详情:', error.response?.data)
      // 处理验证错误
      if (error.response?.data?.errors && Array.isArray(error.response.data.errors)) {
        const errorMessages = error.response.data.errors.map(e => `${e.field}: ${e.message}`).join(', ')
        return { success: false, error: errorMessages || '注册失败' }
      }
      return { success: false, error: error.response?.data?.detail || error.message || '注册失败' }
    }
  },
  
  async fetchUser({ commit }) {
    try {
      const response = await api.get('/auth/me')
      commit('SET_USER', response.data)
    } catch (error) {
      console.error('获取用户信息失败:', error)
    }
  },
  
  logout({ commit }) {
    commit('SET_TOKEN', '')
    commit('SET_USER', null)
  }
}

export default {
  namespaced: true,
  state,
  mutations,
  actions
}

