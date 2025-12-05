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
            <el-button class="theme-toggle" circle @click="toggleTheme">
              <el-icon><Moon v-if="isDark" /><Sunny v-else /></el-icon>
            </el-button>
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
import { ref, computed } from 'vue'
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
  SwitchButton,
  Sunny,
  Moon
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
    SwitchButton,
    Sunny,
    Moon
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

    // 主题切换
    const isDark = ref(document.documentElement.classList.contains('dark'))
    const toggleTheme = () => {
      const html = document.documentElement
      if (html.classList.contains('dark')) {
        html.classList.remove('dark')
        html.classList.add('light')
        localStorage.setItem('theme', 'light')
        isDark.value = false
      } else {
        html.classList.remove('light')
        html.classList.add('dark')
        localStorage.setItem('theme', 'dark')
        isDark.value = true
      }
    }

    return {
      isAuthenticated,
      activeIndex,
      userInfo,
      handleLogout,
      handleCommand,
      isDark,
      toggleTheme
    }
  }
}
</script>

<style>
/* Apple 风格主题 */
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

/* 亮色主题 */
html.light {
  color-scheme: light;
  --apple-bg-primary: #f5f5f7;
  --apple-bg-secondary: #ffffff;
  --apple-bg-tertiary: #f5f5f7;
  --apple-bg-elevated: #ffffff;
  --apple-text-primary: #1d1d1f;
  --apple-text-secondary: rgba(0, 0, 0, 0.6);
  --apple-text-tertiary: rgba(0, 0, 0, 0.4);
  --apple-separator: rgba(0, 0, 0, 0.1);
  --apple-accent: #007aff;
  --apple-accent-hover: #0056b3;
  --apple-green: #34c759;
  --apple-red: #ff3b30;
  --apple-orange: #ff9500;
  --apple-blur-bg: rgba(255, 255, 255, 0.8);
  --el-bg-color: #ffffff;
  --el-bg-color-overlay: #f5f5f7;
  --el-text-color-primary: #1d1d1f;
  --el-text-color-regular: rgba(0, 0, 0, 0.85);
  --el-text-color-secondary: rgba(0, 0, 0, 0.65);
  --el-border-color: rgba(0, 0, 0, 0.1);
  --el-fill-color-blank: #ffffff;
}

/* 深色主题 */
html.dark {
  color-scheme: dark;
  --apple-bg-primary: #000000;
  --apple-bg-secondary: #1c1c1e;
  --apple-bg-tertiary: #2c2c2e;
  --apple-bg-elevated: #1c1c1e;
  --apple-text-primary: #ffffff;
  --apple-text-secondary: rgba(255, 255, 255, 0.7);
  --apple-text-tertiary: rgba(255, 255, 255, 0.5);
  --apple-separator: rgba(255, 255, 255, 0.1);
  --apple-accent: #0a84ff;
  --apple-accent-hover: #409eff;
  --apple-green: #30d158;
  --apple-red: #ff453a;
  --apple-orange: #ff9f0a;
  --apple-blur-bg: rgba(28, 28, 30, 0.8);
  --el-bg-color: #1c1c1e;
  --el-bg-color-overlay: #2c2c2e;
  --el-text-color-primary: #ffffff;
  --el-text-color-regular: rgba(255, 255, 255, 0.85);
  --el-text-color-secondary: rgba(255, 255, 255, 0.65);
  --el-border-color: rgba(255, 255, 255, 0.1);
  --el-fill-color-blank: #2c2c2e;
}

#app {
  font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'SF Pro Text',
    'Helvetica Neue', Helvetica, Arial, sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  min-height: 100vh;
  background: var(--apple-bg-primary);
  color: var(--apple-text-primary);
}

.app-header {
  background: var(--apple-blur-bg);
  backdrop-filter: saturate(180%) blur(20px);
  -webkit-backdrop-filter: saturate(180%) blur(20px);
  border-bottom: 1px solid var(--apple-separator);
  padding: 0;
  height: 52px !important;
  line-height: 52px;
  position: sticky;
  top: 0;
  z-index: 100;
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
  color: var(--apple-text-primary);
  font-size: 18px;
  font-weight: 600;
  margin-right: 40px;
  letter-spacing: -0.3px;
}

.logo-text {
  color: var(--apple-text-primary);
}

.header-menu {
  flex: 1;
  background: transparent !important;
  border-bottom: none !important;
}

.header-menu .el-menu-item {
  color: var(--apple-text-secondary) !important;
  border-bottom: none !important;
  margin: 0 2px;
  padding: 0 16px;
  border-radius: 8px;
  transition: all 0.2s ease;
  font-size: 14px;
  font-weight: 500;
  height: 36px;
  line-height: 36px;
}

.header-menu .el-menu-item:hover {
  background: rgba(255, 255, 255, 0.08) !important;
  color: var(--apple-text-primary) !important;
}

.header-menu .el-menu-item.is-active {
  color: var(--apple-text-primary) !important;
  background: rgba(255, 255, 255, 0.12) !important;
  font-weight: 600 !important;
}

.header-actions {
  margin-left: 20px;
  display: flex;
  align-items: center;
  gap: 12px;
}

.theme-toggle {
  background: rgba(255, 255, 255, 0.1) !important;
  border: none !important;
  color: var(--apple-text-primary) !important;
  transition: all 0.2s ease;
}

.theme-toggle:hover {
  background: rgba(255, 255, 255, 0.2) !important;
  transform: rotate(15deg);
}

.user-dropdown {
  display: flex;
  align-items: center;
  color: var(--apple-text-secondary);
  cursor: pointer;
  padding: 6px 12px;
  border-radius: 8px;
  transition: all 0.2s ease;
  font-size: 14px;
}

.user-dropdown:hover {
  background: rgba(255, 255, 255, 0.08);
  color: var(--apple-text-primary);
}

.user-dropdown .el-icon {
  margin-right: 6px;
}

.el-main {
  padding: 24px;
  min-height: calc(100vh - 52px);
  background: var(--apple-bg-primary);
}

.main-authenticated {
  background: var(--apple-bg-primary);
}

/* 全局卡片样式 - Apple 风格 */
.el-card {
  border-radius: 16px;
  background: var(--apple-bg-secondary);
  border: 1px solid var(--apple-separator);
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.4);
  transition: all 0.3s ease;
}

.el-card:hover {
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
  transform: translateY(-2px);
}

.el-card__header {
  border-bottom: 1px solid var(--apple-separator);
  padding: 16px 20px;
  color: var(--apple-text-primary);
  font-weight: 600;
}

.el-card__body {
  padding: 20px;
  color: var(--apple-text-primary);
}

/* 表格样式 - Apple 风格 */
.el-table {
  background: transparent !important;
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: transparent;
  --el-table-row-hover-bg-color: rgba(255, 255, 255, 0.05);
  --el-table-border-color: var(--apple-separator);
  border-radius: 12px;
  overflow: hidden;
}

.el-table th.el-table__cell {
  background: rgba(255, 255, 255, 0.03) !important;
  color: var(--apple-text-secondary) !important;
  font-weight: 500;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  border-bottom: 1px solid var(--apple-separator) !important;
}

.el-table td.el-table__cell {
  color: var(--apple-text-primary);
  border-bottom: 1px solid var(--apple-separator) !important;
}

.el-table--enable-row-hover .el-table__body tr:hover > td.el-table__cell {
  background: rgba(255, 255, 255, 0.05) !important;
}

/* 按钮样式 - Apple 风格 */
.el-button {
  border-radius: 10px;
  font-weight: 500;
  transition: all 0.2s ease;
  border: none;
}

.el-button--primary {
  background: var(--apple-accent);
  color: #fff;
}

.el-button--primary:hover {
  background: var(--apple-accent-hover);
  transform: scale(1.02);
}

.el-button--default {
  background: var(--apple-bg-tertiary);
  color: var(--apple-text-primary);
  border: 1px solid var(--apple-separator);
}

.el-button--default:hover {
  background: rgba(255, 255, 255, 0.1);
}

/* 输入框样式 - Apple 风格 */
.el-input__wrapper {
  border-radius: 10px;
  background: var(--apple-bg-tertiary) !important;
  box-shadow: none !important;
  border: 1px solid var(--apple-separator);
  transition: all 0.2s ease;
}

.el-input__wrapper:hover {
  border-color: rgba(255, 255, 255, 0.2);
}

.el-input__wrapper.is-focus {
  border-color: var(--apple-accent) !important;
  box-shadow: 0 0 0 3px rgba(10, 132, 255, 0.2) !important;
}

.el-input__inner {
  color: var(--apple-text-primary);
}

.el-input__inner::placeholder {
  color: var(--apple-text-tertiary);
}

/* 下拉菜单样式 */
.el-dropdown-menu {
  background: var(--apple-bg-elevated) !important;
  border: 1px solid var(--apple-separator);
  border-radius: 12px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
  backdrop-filter: saturate(180%) blur(20px);
}

.el-dropdown-menu__item {
  color: var(--apple-text-primary) !important;
  border-radius: 8px;
  margin: 4px;
}

.el-dropdown-menu__item:hover {
  background: rgba(255, 255, 255, 0.08) !important;
}

/* 标签样式 */
.el-tag {
  border-radius: 6px;
  border: none;
  font-weight: 500;
}

.el-tag--success {
  background: rgba(48, 209, 88, 0.15);
  color: var(--apple-green);
}

.el-tag--danger {
  background: rgba(255, 69, 58, 0.15);
  color: var(--apple-red);
}

.el-tag--warning {
  background: rgba(255, 159, 10, 0.15);
  color: var(--apple-orange);
}

.el-tag--info {
  background: rgba(255, 255, 255, 0.1);
  color: var(--apple-text-secondary);
}

/* 对话框样式 */
.el-dialog {
  background: var(--apple-bg-secondary) !important;
  border-radius: 16px;
  border: 1px solid var(--apple-separator);
  box-shadow: 0 24px 80px rgba(0, 0, 0, 0.6);
}

.el-dialog__header {
  border-bottom: 1px solid var(--apple-separator);
  padding: 20px 24px;
}

.el-dialog__title {
  color: var(--apple-text-primary);
  font-weight: 600;
}

.el-dialog__body {
  color: var(--apple-text-primary);
  padding: 24px;
}

/* 表单样式 */
.el-form-item__label {
  color: var(--apple-text-secondary) !important;
  font-weight: 500;
}

/* Select 样式 */
.el-select__wrapper {
  background: var(--apple-bg-tertiary) !important;
  border: 1px solid var(--apple-separator);
  border-radius: 10px;
  box-shadow: none !important;
}

.el-select-dropdown {
  background: var(--apple-bg-elevated) !important;
  border: 1px solid var(--apple-separator);
  border-radius: 12px;
}

.el-select-dropdown__item {
  color: var(--apple-text-primary);
}

.el-select-dropdown__item.hover,
.el-select-dropdown__item:hover {
  background: rgba(255, 255, 255, 0.08);
}

.el-select-dropdown__item.selected {
  color: var(--apple-accent);
  font-weight: 600;
}

/* Switch 样式 */
.el-switch.is-checked .el-switch__core {
  background: var(--apple-green);
  border-color: var(--apple-green);
}

/* 消息提示样式 */
.el-message {
  background: var(--apple-bg-elevated) !important;
  border: 1px solid var(--apple-separator);
  border-radius: 12px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
}

.el-message__content {
  color: var(--apple-text-primary) !important;
}

/* 滚动条样式 */
::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

::-webkit-scrollbar-track {
  background: transparent;
}

::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.2);
  border-radius: 4px;
}

::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.3);
}

/* 全局盈亏颜色 */
.profit {
  color: var(--apple-green) !important;
}

.loss {
  color: var(--apple-red) !important;
}
</style>

