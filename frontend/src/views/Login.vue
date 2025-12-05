<template>
  <div class="login-container">
    <div class="login-background">
      <div class="background-shapes">
        <div class="shape shape-1"></div>
        <div class="shape shape-2"></div>
        <div class="shape shape-3"></div>
      </div>
    </div>
    <el-card class="login-card">
      <template #header>
        <div class="card-header">
          <el-icon :size="32" class="header-icon"><Lock /></el-icon>
          <h2>欢迎回来</h2>
          <p class="header-subtitle">登录您的交易账户</p>
        </div>
      </template>
      <el-form 
        :model="form" 
        :rules="rules" 
        ref="formRef" 
        label-width="0" 
        class="login-form"
        @submit.prevent="handleLogin"
      >
        <el-form-item prop="username">
          <el-input 
            v-model="form.username" 
            placeholder="请输入用户名"
            size="large"
            :prefix-icon="User"
          ></el-input>
        </el-form-item>
        <el-form-item prop="password">
          <el-input 
            v-model="form.password" 
            type="password" 
            placeholder="请输入密码" 
            @keyup.enter="handleLogin"
            size="large"
            :prefix-icon="Lock"
            show-password
          ></el-input>
        </el-form-item>
        <el-form-item>
          <el-button 
            type="primary" 
            @click="handleLogin" 
            :loading="loading"
            size="large"
            class="login-button"
          >
            {{ loading ? '登录中...' : '登录' }}
          </el-button>
        </el-form-item>
        <div class="register-link">
          <span>还没有账号？</span>
          <el-button type="text" @click="$router.push('/register')" class="link-button">
            立即注册
          </el-button>
        </div>
      </el-form>
    </el-card>
  </div>
</template>

<script>
import { ref, reactive } from 'vue'
import { useStore } from 'vuex'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Lock, User } from '@element-plus/icons-vue'

export default {
  name: 'Login',
  components: {
    Lock,
    User
  },
  setup() {
    const store = useStore()
    const router = useRouter()
    const formRef = ref(null)
    const loading = ref(false)
    
    const form = reactive({
      username: '',
      password: ''
    })
    
    const rules = {
      username: [
        { required: true, message: '请输入用户名', trigger: 'blur' }
      ],
      password: [
        { required: true, message: '请输入密码', trigger: 'blur' }
      ]
    }
    
    const handleLogin = async (e) => {
      // 阻止表单默认提交行为
      if (e && e.preventDefault) {
        e.preventDefault()
      }
      
      if (!formRef.value) return
      
      await formRef.value.validate(async (valid) => {
        if (valid) {
          // 保存用户名，防止被清空
          const savedUsername = form.username
          
          loading.value = true
          const result = await store.dispatch('auth/login', form)
          loading.value = false
          
          if (result.success) {
            ElMessage.success('登录成功')
            router.push('/dashboard')
          } else {
            // 显示错误提示，使用配置对象确保 duration 生效（6秒）
            ElMessage({
              message: result.error || '登录失败',
              type: 'error',
              duration: 6000,
              showClose: true
            })
            
            // 登录失败时，确保用户名保留，只清空密码
            form.username = savedUsername
            form.password = ''
            
            // 清除密码字段的验证状态
            if (formRef.value) {
              formRef.value.clearValidate('password')
            }
            
            // 让密码输入框重新获得焦点
            await formRef.value.$nextTick()
            const passwordInput = formRef.value.$el?.querySelector('input[type="password"]')
            if (passwordInput) {
              passwordInput.focus()
            }
          }
        }
      })
    }
    
    return {
      form,
      rules,
      formRef,
      loading,
      handleLogin,
      Lock,
      User
    }
  }
}
</script>

<style scoped>
.login-container {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100vh;
  position: relative;
  overflow: hidden;
}

.login-background {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: var(--apple-bg-primary, #000);
  z-index: 0;
}

.background-shapes {
  position: absolute;
  width: 100%;
  height: 100%;
  overflow: hidden;
}

.shape {
  position: absolute;
  border-radius: 50%;
  background: rgba(10, 132, 255, 0.08);
  animation: float 20s infinite;
}

.shape-1 {
  width: 400px;
  height: 400px;
  top: -150px;
  left: -150px;
  animation-delay: 0s;
}

.shape-2 {
  width: 300px;
  height: 300px;
  bottom: -100px;
  right: -100px;
  background: rgba(48, 209, 88, 0.06);
  animation-delay: 5s;
}

.shape-3 {
  width: 200px;
  height: 200px;
  top: 40%;
  right: 15%;
  background: rgba(255, 69, 58, 0.05);
  animation-delay: 10s;
}

@keyframes float {
  0%, 100% {
    transform: translate(0, 0) scale(1);
  }
  50% {
    transform: translate(30px, -30px) scale(1.1);
  }
}

.login-card {
  width: 400px;
  position: relative;
  z-index: 1;
  background: var(--apple-bg-secondary, #1c1c1e) !important;
  border: 1px solid var(--apple-separator, rgba(255, 255, 255, 0.1)) !important;
  border-radius: 20px !important;
  box-shadow: 0 24px 80px rgba(0, 0, 0, 0.6);
  backdrop-filter: saturate(180%) blur(20px);
}

.card-header {
  text-align: center;
  padding: 10px 0;
}

.header-icon {
  color: var(--apple-accent, #0a84ff);
  margin-bottom: 12px;
}

.card-header h2 {
  margin: 0 0 8px 0;
  color: var(--apple-text-primary, #fff);
  font-size: 24px;
  font-weight: 600;
  letter-spacing: -0.5px;
}

.header-subtitle {
  margin: 0;
  color: var(--apple-text-secondary, rgba(255, 255, 255, 0.7));
  font-size: 14px;
}

.login-form {
  margin-top: 24px;
}

.login-form :deep(.el-form-item) {
  margin-bottom: 20px;
}

.login-form :deep(.el-input__wrapper) {
  padding: 12px 15px;
  background: var(--apple-bg-tertiary, #2c2c2e) !important;
  border: 1px solid var(--apple-separator, rgba(255, 255, 255, 0.1));
  border-radius: 12px;
  box-shadow: none !important;
}

.login-form :deep(.el-input__wrapper:hover) {
  border-color: rgba(255, 255, 255, 0.2);
}

.login-form :deep(.el-input__wrapper.is-focus) {
  border-color: var(--apple-accent, #0a84ff) !important;
  box-shadow: 0 0 0 3px rgba(10, 132, 255, 0.2) !important;
}

.login-form :deep(.el-input__inner) {
  color: var(--apple-text-primary, #fff);
}

.login-form :deep(.el-input__inner::placeholder) {
  color: var(--apple-text-tertiary, rgba(255, 255, 255, 0.5));
}

.login-form :deep(.el-input__prefix) {
  color: var(--apple-text-tertiary, rgba(255, 255, 255, 0.5));
}

.login-button {
  width: 100%;
  height: 48px;
  font-size: 16px;
  font-weight: 600;
  background: var(--apple-accent, #0a84ff) !important;
  border: none !important;
  border-radius: 12px !important;
  transition: all 0.2s ease;
}

.login-button:hover {
  background: var(--apple-accent-hover, #409eff) !important;
  transform: scale(1.02);
}

.register-link {
  text-align: center;
  margin-top: 20px;
  color: var(--apple-text-secondary, rgba(255, 255, 255, 0.7));
  font-size: 14px;
}

.link-button {
  color: var(--apple-accent, #0a84ff) !important;
  font-weight: 500;
  padding: 0 4px;
}

.link-button:hover {
  color: var(--apple-accent-hover, #409eff) !important;
}
</style>

