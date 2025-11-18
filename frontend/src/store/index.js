import { createStore } from 'vuex'
import auth from './modules/auth'
import strategies from './modules/strategies'
import trades from './modules/trades'

export default createStore({
  modules: {
    auth,
    strategies,
    trades
  }
})

