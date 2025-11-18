module.exports = {
  devServer: {
    port: 8080,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true
      }
    },
    // 忽略 ResizeObserver 警告
    client: {
      overlay: {
        warnings: false,
        errors: true,
        runtimeErrors: (error) => {
          // 忽略 ResizeObserver 相关错误
          const errorMessage = error.message || error.toString()
          if (errorMessage.includes('ResizeObserver') || 
              errorMessage.includes('ResizeObserver loop')) {
            return false
          }
          return true
        }
      }
    }
  },
  // 配置 webpack
  configureWebpack: {
    ignoreWarnings: [
      /ResizeObserver/
    ]
  }
}

