<template>
  <div class="register-container">
    <div class="register-background">
      <div class="background-shapes">
        <div class="shape shape-1"></div>
        <div class="shape shape-2"></div>
        <div class="shape shape-3"></div>
      </div>
    </div>
    <el-card class="register-card">
      <template #header>
        <div class="card-header">
          <el-icon :size="32" class="header-icon"><UserFilled /></el-icon>
          <h2>创建账户</h2>
          <p class="header-subtitle">注册新用户开始交易之旅</p>
        </div>
      </template>
      <el-form :model="form" :rules="rules" ref="formRef" label-width="0" class="register-form">
        <el-form-item prop="username">
          <el-input 
            v-model="form.username" 
            placeholder="请输入用户名"
            size="large"
            :prefix-icon="User"
          ></el-input>
        </el-form-item>
        <el-form-item prop="email">
          <el-input 
            v-model="form.email" 
            placeholder="请输入邮箱"
            size="large"
            :prefix-icon="Message"
          ></el-input>
        </el-form-item>
        <el-form-item prop="password">
          <el-input 
            v-model="form.password" 
            type="password" 
            placeholder="请输入密码（至少6位）"
            size="large"
            :prefix-icon="Lock"
            show-password
          ></el-input>
        </el-form-item>
        <el-form-item prop="confirmPassword">
          <el-input 
            v-model="form.confirmPassword" 
            type="password" 
            placeholder="请再次输入密码"
            size="large"
            :prefix-icon="Lock"
            show-password
          ></el-input>
        </el-form-item>
        <el-form-item>
          <el-button 
            type="primary" 
            @click="handleRegister" 
            :loading="loading"
            size="large"
            class="register-button"
          >
            {{ loading ? '注册中...' : '注册' }}
          </el-button>
        </el-form-item>
        <div class="login-link">
          <span>已有账号？</span>
          <el-button type="text" @click="$router.push('/login')" class="link-button">
            立即登录
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
import { UserFilled, User, Message, Lock } from '@element-plus/icons-vue'

export default {
  name: 'Register',
  components: {
    UserFilled,
    User,
    Message,
    Lock
  },
  setup() {
    const store = useStore()
    const router = useRouter()
    const formRef = ref(null)
    const loading = ref(false)
    
    const form = reactive({
      username: '',
      email: '',
      password: '',
      confirmPassword: ''
    })
    
    const validateConfirmPassword = (rule, value, callback) => {
      if (value !== form.password) {
        callback(new Error('两次输入密码不一致'))
      } else {
        callback()
      }
    }
    
    const rules = {
      username: [
        { required: true, message: '请输入用户名', trigger: 'blur' }
      ],
      email: [
        { required: true, message: '请输入邮箱', trigger: 'blur' },
        { type: 'email', message: '请输入正确的邮箱格式', trigger: 'blur' }
      ],
      password: [
        { required: true, message: '请输入密码', trigger: 'blur' },
        { min: 6, message: '密码长度不能少于6位', trigger: 'blur' }
      ],
      confirmPassword: [
        { required: true, message: '请再次输入密码', trigger: 'blur' },
        { validator: validateConfirmPassword, trigger: 'blur' }
      ]
    }
    
    const handleRegister = async () => {
      if (!formRef.value) return
      
      await formRef.value.validate(async (valid) => {
        if (valid) {
          loading.value = true
          const result = await store.dispatch('auth/register', {
            username: form.username,
            email: form.email,
            password: form.password
          })
          loading.value = false
          
          if (result.success) {
            ElMessage.success('注册成功，请登录')
            router.push('/login')
          } else {
            ElMessage.error(result.error)
          }
        }
      })
    }
    
    return {
      form,
      rules,
      formRef,
      loading,
      handleRegister,
      UserFilled,
      User,
      Message,
      Lock
    }
  }
}
</script>

<style scoped>
.register-container {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100vh;
  position: relative;
  overflow: hidden;
  padding: 20px;
}

.register-background {
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
  background: rgba(191, 90, 242, 0.05);
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

.register-card {
  width: 400px;
  max-width: 100%;
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

.register-form {
  margin-top: 24px;
}

.register-form :deep(.el-form-item) {
  margin-bottom: 20px;
}

.register-form :deep(.el-input__wrapper) {
  padding: 12px 15px;
  background: var(--apple-bg-tertiary, #2c2c2e) !important;
  border: 1px solid var(--apple-separator, rgba(255, 255, 255, 0.1));
  border-radius: 12px;
  box-shadow: none !important;
}

.register-form :deep(.el-input__wrapper:hover) {
  border-color: rgba(255, 255, 255, 0.2);
}

.register-form :deep(.el-input__wrapper.is-focus) {
  border-color: var(--apple-accent, #0a84ff) !important;
  box-shadow: 0 0 0 3px rgba(10, 132, 255, 0.2) !important;
}

.register-form :deep(.el-input__inner) {
  color: var(--apple-text-primary, #fff);
}

.register-form :deep(.el-input__inner::placeholder) {
  color: var(--apple-text-tertiary, rgba(255, 255, 255, 0.5));
}

.register-form :deep(.el-input__prefix) {
  color: var(--apple-text-tertiary, rgba(255, 255, 255, 0.5));
}

.register-button {
  width: 100%;
  height: 48px;
  font-size: 16px;
  font-weight: 600;
  background: var(--apple-accent, #0a84ff) !important;
  border: none !important;
  border-radius: 12px !important;
  transition: all 0.2s ease;
}

.register-button:hover {
  background: var(--apple-accent-hover, #409eff) !important;
  transform: scale(1.02);
}

.login-link {
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

