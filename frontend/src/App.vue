<template>
  <div id="app">
    <el-container>
      <el-header v-if="isAuthenticated" class="app-header">
        <div class="header-content">
          <div class="logo">
            <el-icon :size="24" style="margin-right: 8px"><TrendCharts /></el-icon>
            <span class="logo-text">交易系统</span>
          </div>
          <el-menu
            mode="horizontal"
            :default-active="activeIndex"
            router
            class="header-menu"
          >
            <el-menu-item index="/dashboard">
              <el-icon><DataBoard /></el-icon>
              <span>仪表盘</span>
            </el-menu-item>
            <el-menu-item index="/strategies">
              <el-icon><Setting /></el-icon>
              <span>策略管理</span>
            </el-menu-item>
            <el-menu-item index="/positions">
              <el-icon><Wallet /></el-icon>
              <span>持仓</span>
            </el-menu-item>
            <el-menu-item index="/orders">
              <el-icon><List /></el-icon>
              <span>订单</span>
            </el-menu-item>
          </el-menu>
          <div class="header-actions">
            <el-dropdown @command="handleCommand">
              <span class="user-dropdown">
                <el-icon><User /></el-icon>
                <span>{{ userInfo?.username || '用户' }}</span>
                <el-icon class="el-icon--right"><ArrowDown /></el-icon>
              </span>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="logout">
                    <el-icon><SwitchButton /></el-icon>
                    退出登录
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </div>
      </el-header>
      <el-main :class="{ 'main-authenticated': isAuthenticated }">
        <router-view />
      </el-main>
    </el-container>
  </div>
</template>

<script>
import { computed } from 'vue'
import { useStore } from 'vuex'
import { useRouter } from 'vue-router'
import { 
  TrendCharts, 
  DataBoard, 
  Setting, 
  Wallet, 
  List, 
  User, 
  ArrowDown,
  SwitchButton 
} from '@element-plus/icons-vue'

export default {
  name: 'App',
  components: {
    TrendCharts,
    DataBoard,
    Setting,
    Wallet,
    List,
    User,
    ArrowDown,
    SwitchButton
  },
  setup() {
    const store = useStore()
    const router = useRouter()
    
    const isAuthenticated = computed(() => store.state.auth.isAuthenticated)
    const activeIndex = computed(() => router.currentRoute.value.path)
    const userInfo = computed(() => store.state.auth.user)
    
    const handleLogout = () => {
      store.dispatch('auth/logout')
      router.push('/login')
    }
    
    const handleCommand = (command) => {
      if (command === 'logout') {
        handleLogout()
      }
    }
    
    return {
      isAuthenticated,
      activeIndex,
      userInfo,
      handleLogout,
      handleCommand
    }
  }
}
</script>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

#app {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB',
    'Microsoft YaHei', 'Helvetica Neue', Helvetica, Arial, sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  min-height: 100vh;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}

.app-header {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.1);
  padding: 0;
  height: 64px !important;
  line-height: 64px;
}

.header-content {
  display: flex;
  align-items: center;
  justify-content: space-between;
  max-width: 1400px;
  margin: 0 auto;
  padding: 0 24px;
  height: 100%;
}

.logo {
  display: flex;
  align-items: center;
  color: #fff;
  font-size: 20px;
  font-weight: 600;
  margin-right: 40px;
}

.logo-text {
  background: linear-gradient(90deg, #fff 0%, #e0e7ff 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.header-menu {
  flex: 1;
  background: transparent !important;
  border-bottom: none !important;
}

.header-menu .el-menu-item {
  color: rgba(255, 255, 255, 0.9) !important;
  border-bottom: 3px solid transparent !important;
  margin: 0 4px;
  border-radius: 4px 4px 0 0;
  transition: all 0.3s;
  position: relative;
}

.header-menu .el-menu-item:hover {
  background: rgba(255, 255, 255, 0.1) !important;
  color: #fff !important;
}

.header-menu .el-menu-item.is-active {
  color: #fff !important;
  background: rgba(255, 255, 255, 0.25) !important;
  border-bottom-color: #fff !important;
  font-weight: 600 !important;
  box-shadow: 0 2px 8px rgba(255, 255, 255, 0.2) !important;
}

.header-menu .el-menu-item.is-active::after {
  content: '';
  position: absolute;
  bottom: -3px;
  left: 50%;
  transform: translateX(-50%);
  width: 60%;
  height: 3px;
  background: #fff;
  border-radius: 2px 2px 0 0;
  box-shadow: 0 0 10px rgba(255, 255, 255, 0.8);
}

.header-actions {
  margin-left: 20px;
}

.user-dropdown {
  display: flex;
  align-items: center;
  color: #fff;
  cursor: pointer;
  padding: 8px 12px;
  border-radius: 4px;
  transition: background 0.3s;
}

.user-dropdown:hover {
  background: rgba(255, 255, 255, 0.1);
}

.user-dropdown .el-icon {
  margin-right: 6px;
}

.el-main {
  padding: 24px;
  min-height: calc(100vh - 64px);
}

.main-authenticated {
  background: #f5f7fa;
}

/* 全局卡片样式优化 */
.el-card {
  border-radius: 12px;
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.08);
  transition: all 0.3s;
  border: none;
}

.el-card:hover {
  box-shadow: 0 4px 20px 0 rgba(0, 0, 0, 0.12);
  transform: translateY(-2px);
}

/* 表格样式优化 */
.el-table {
  border-radius: 8px;
  overflow: hidden;
}

.el-table th {
  background: #fafbfc;
  color: #606266;
  font-weight: 600;
}

/* 按钮样式优化 */
.el-button {
  border-radius: 6px;
  transition: all 0.3s;
}

.el-button:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

/* 输入框样式优化 */
.el-input__wrapper {
  border-radius: 6px;
}

/* 标签页样式优化 */
.el-tabs__item {
  font-weight: 500;
}

.el-tabs__active-bar {
  height: 3px;
  border-radius: 2px;
}
</style>

