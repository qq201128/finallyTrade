<template>
  <div id="app">
    <el-container>
      <el-header v-if="isAuthenticated">
        <el-menu
          mode="horizontal"
          :default-active="activeIndex"
          router
        >
          <el-menu-item index="/dashboard">仪表盘</el-menu-item>
          <el-menu-item index="/strategies">策略管理</el-menu-item>
          <el-menu-item index="/positions">持仓</el-menu-item>
          <el-menu-item index="/orders">订单</el-menu-item>
          <el-menu-item index="/logout" @click="handleLogout">退出</el-menu-item>
        </el-menu>
      </el-header>
      <el-main>
        <router-view />
      </el-main>
    </el-container>
  </div>
</template>

<script>
import { computed } from 'vue'
import { useStore } from 'vuex'
import { useRouter } from 'vue-router'

export default {
  name: 'App',
  setup() {
    const store = useStore()
    const router = useRouter()
    
    const isAuthenticated = computed(() => store.state.auth.isAuthenticated)
    const activeIndex = computed(() => router.currentRoute.value.path)
    
    const handleLogout = () => {
      store.dispatch('auth/logout')
      router.push('/login')
    }
    
    return {
      isAuthenticated,
      activeIndex,
      handleLogout
    }
  }
}
</script>

<style>
#app {
  font-family: Avenir, Helvetica, Arial, sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  color: #2c3e50;
}

.el-header {
  background-color: #409EFF;
  color: #fff;
  line-height: 60px;
}

.el-main {
  padding: 20px;
}
</style>

