<template>
  <div class="positions">
    <div class="positions-header">
      <h1 class="page-title">
        <el-icon :size="28" style="margin-right: 12px"><Wallet /></el-icon>
        持仓管理
      </h1>
      <p class="page-subtitle">实时监控和管理您的交易持仓</p>
    </div>
    
    <!-- 持仓统计 -->
    <el-row :gutter="20" style="margin-bottom: 20px">
      <el-col :span="6">
        <el-card shadow="hover">
          <div class="stat-item">
            <div class="stat-label">总持仓数</div>
            <div class="stat-value">{{ positions.length }}</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <div class="stat-item">
            <div class="stat-label">多头持仓</div>
            <div class="stat-value" style="color: #67c23a">
              {{ longPositionsCount }}
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <div class="stat-item">
            <div class="stat-label">空头持仓</div>
            <div class="stat-value" style="color: #f56c6c">
              {{ shortPositionsCount }}
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <div class="stat-item">
            <div class="stat-label">总未实现盈亏</div>
            <div class="stat-value" :class="totalUnrealizedPnl >= 0 ? 'profit' : 'loss'">
              {{ totalUnrealizedPnl.toFixed(2) }}
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>
    
    <!-- 再入场限制提示 -->
    <el-card v-if="reentryBlocks.length" class="reentry-card" shadow="hover">
      <template #header>
        <div style="display: flex; align-items: center; justify-content: space-between;">
          <span>以下方向当前禁止再入场，等待下一个周期或手动开启</span>
          <el-button type="primary" size="small" :loading="reentryLoading" @click="fetchReentryBlocks">刷新</el-button>
        </div>
      </template>
      <el-table :data="reentryBlocks" size="small" style="width: 100%">
        <el-table-column label="交易对" prop="symbol"></el-table-column>
        <el-table-column label="方向">
          <template #default="scope">
            {{ scope.row.side === 'long' ? '做多' : '做空' }}
          </template>
        </el-table-column>
        <el-table-column label="限制截止">
          <template #default="scope">
            {{ formatDate(scope.row.blocked_until) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="scope">
            <el-button
              type="warning"
              size="small"
              :loading="unlockingBlockId === scope.row.id"
              @click="handleUnlockBlock(scope.row)"
            >
              手动开启
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
    
    <el-tabs v-model="activeTab">
      <el-tab-pane label="当前持仓" name="current">
        <!-- 筛选器和刷新按钮 -->
        <div style="margin-bottom: 15px; display: flex; justify-content: space-between; align-items: center">
          <el-radio-group v-model="positionFilter" size="small">
            <el-radio-button label="all">全部</el-radio-button>
            <el-radio-button label="long">多头</el-radio-button>
            <el-radio-button label="short">空头</el-radio-button>
          </el-radio-group>
          <el-button 
            type="primary" 
            size="small" 
            :loading="positionsLoading"
            @click="handleRefreshPositions"
            :icon="'Refresh'"
          >
            刷新
          </el-button>
        </div>
        <el-table :data="filteredPositions || []" style="width: 100%" v-loading="positionsLoading">
      <el-table-column prop="symbol" label="交易对">
        <template #default="scope">
          {{ scope.row && scope.row.symbol ? scope.row.symbol : '-' }}
        </template>
      </el-table-column>
      <el-table-column prop="side" label="方向" width="100">
        <template #default="scope">
          <el-tag v-if="scope.row && scope.row.side" 
                  :type="scope.row.side === 'long' ? 'success' : 'danger'" 
                  size="small">
            {{ scope.row.side === 'long' ? '做多' : '做空' }}
          </el-tag>
          <span v-else>-</span>
        </template>
      </el-table-column>
      <el-table-column prop="size" label="数量">
        <template #default="scope">
          {{ scope.row && scope.row.size ? scope.row.size : '-' }}
        </template>
      </el-table-column>
      <el-table-column prop="entry_price" label="开仓价">
        <template #default="scope">
          {{ formatPrice(scope.row?.entry_price) }}
        </template>
      </el-table-column>
      <el-table-column prop="current_price" label="当前价">
        <template #default="scope">
        <span>{{ formatPrice(scope.row?.current_price) }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="leverage" label="倍数" width="80">
        <template #default="scope">
          <el-tag v-if="scope.row && scope.row.leverage" type="warning" size="small">
            {{ scope.row.leverage }}x
          </el-tag>
          <span v-else>1x</span>
        </template>
      </el-table-column>
      <el-table-column prop="margin_used" label="保证金">
        <template #default="scope">
          <span v-if="scope.row && scope.row.margin_used !== null && scope.row.margin_used !== undefined">
            {{ formatNumber(scope.row.margin_used) }}
          </span>
          <span v-else>-</span>
        </template>
      </el-table-column>
      <el-table-column prop="unrealized_pnl" label="未实现盈亏">
        <template #default="scope">
          <span v-if="scope.row && scope.row.unrealized_pnl !== null && scope.row.unrealized_pnl !== undefined" 
                :class="scope.row.unrealized_pnl >= 0 ? 'profit' : 'loss'">
            {{ scope.row.unrealized_pnl.toFixed(2) }}
          </span>
          <span v-else>-</span>
        </template>
      </el-table-column>
      <el-table-column prop="pnl_percentage" label="盈亏 %">
        <template #default="scope">
          <span v-if="scope.row && scope.row.pnl_percentage !== null && scope.row.pnl_percentage !== undefined"
                :class="scope.row.pnl_percentage >= 0 ? 'profit' : 'loss'">
            {{ scope.row.pnl_percentage.toFixed(2) }}%
          </span>
          <span v-else>-</span>
        </template>
      </el-table-column>
      <el-table-column prop="stop_loss" label="止损">
        <template #default="scope">
          {{ formatPrice(scope.row?.stop_loss) }}
        </template>
      </el-table-column>
      <el-table-column prop="take_profit" label="止盈">
        <template #default="scope">
          {{ formatPrice(scope.row?.take_profit) }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="120" fixed="right">
        <template #default="scope">
          <el-button 
            type="danger" 
            size="small" 
            :loading="closingPositionId === scope.row.id"
            @click="handleClosePosition(scope.row)"
            :disabled="!scope.row || !scope.row.is_open">
            手动平仓
          </el-button>
        </template>
      </el-table-column>
        </el-table>
      </el-tab-pane>
      
      <el-tab-pane label="持仓历史" name="history">
        <el-table :data="positionHistory || []" style="width: 100%" v-loading="historyLoading">
          <el-table-column prop="symbol" label="交易对">
            <template #default="scope">
              {{ scope.row && scope.row.symbol ? scope.row.symbol : '-' }}
            </template>
          </el-table-column>
          <el-table-column prop="side" label="方向">
            <template #default="scope">
              <span v-if="scope.row && scope.row.side">
                {{ scope.row.side === 'long' ? '做多' : '做空' }}
              </span>
              <span v-else>-</span>
            </template>
          </el-table-column>
          <el-table-column prop="size" label="数量">
            <template #default="scope">
              {{ scope.row && scope.row.size ? scope.row.size : '-' }}
            </template>
          </el-table-column>
      <el-table-column prop="entry_price" label="开仓价">
            <template #default="scope">
              {{ formatPrice(scope.row?.entry_price) }}
            </template>
          </el-table-column>
          <el-table-column prop="current_price" label="平仓价">
            <template #default="scope">
              {{ formatPrice(scope.row?.current_price) }}
            </template>
          </el-table-column>
          <el-table-column prop="leverage" label="倍数" width="80">
            <template #default="scope">
              <el-tag v-if="scope.row && scope.row.leverage" type="warning" size="small">
                {{ scope.row.leverage }}x
              </el-tag>
              <span v-else>1x</span>
            </template>
          </el-table-column>
          <el-table-column prop="realized_pnl" label="已实现盈亏" width="150">
            <template #default="scope">
              <span v-if="scope.row && scope.row.realized_pnl !== null && scope.row.realized_pnl !== undefined" 
                    :class="scope.row.realized_pnl >= 0 ? 'profit' : 'loss'">
                {{ scope.row.realized_pnl.toFixed(2) }}
              </span>
              <span v-else>-</span>
            </template>
          </el-table-column>
          <el-table-column prop="opened_at" label="开仓时间" width="180">
            <template #default="scope">
              {{ formatDate(scope.row.opened_at) }}
            </template>
          </el-table-column>
          <el-table-column prop="closed_at" label="平仓时间" width="180">
            <template #default="scope">
              {{ formatDate(scope.row.closed_at) }}
            </template>
          </el-table-column>
          <el-table-column prop="duration" label="持仓时长" width="120">
            <template #default="scope">
              {{ scope.row && scope.row.duration ? scope.row.duration : '-' }}
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useStore } from 'vuex'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '@/services/api'
import { Wallet } from '@element-plus/icons-vue'
import { debounce } from '@/utils/request-optimizer'

export default {
  name: 'Positions',
  components: {
    Wallet
  },
  setup() {
    const store = useStore()
    const closingPositionId = ref(null)
    const activeTab = ref('current')
    const positionHistory = ref([])
    const historyLoading = ref(false)
    const positionFilter = ref('all')
    const reentryBlocks = ref([])
    const reentryLoading = ref(false)
    const unlockingBlockId = ref(null)
    const positionsLoading = ref(false)  // 持仓列表加载状态

    const calculateMarginUsed = (position) => {
      if (!position) return null
      const entryPrice = Number(position.entry_price) || 0
      const size = Math.abs(Number(position.size) || 0)
      const leverage = Number(position.leverage) || 1
      if (!entryPrice || !size) return null
      const effectiveLeverage = leverage > 0 ? leverage : 1
      return (entryPrice * size) / effectiveLeverage
    }

    const calculatePnlPercentage = (position) => {
      if (!position) return null
      const entryPrice = Number(position.entry_price) || 0
      const size = Math.abs(Number(position.size) || 0)
      const unrealized = Number(position.unrealized_pnl)
      const leverage = Number(position.leverage) || 1
      const notional = entryPrice * size
      if (!notional || isNaN(unrealized)) return null
      const effectiveLeverage = leverage > 0 ? leverage : 1
      return (unrealized / notional) * effectiveLeverage * 100
    }
    
    const positions = computed(() => {
      const positionsList = store.state.trades.positions || []
      // 过滤掉已平仓的持仓
      const openPositions = positionsList.filter(p => p.is_open !== false && p.is_open !== 0)
      // 确保每个持仓都有必要的字段
      return openPositions.map(position => {
        const normalized = {
          ...position,
          side: position.side || 'long',
          size: Math.abs(position.size || 0),
          entry_price: position.entry_price || null,
          current_price: position.current_price || null,
          unrealized_pnl: position.unrealized_pnl !== undefined ? position.unrealized_pnl : 0,
          leverage: position.leverage || 1,
          is_open: position.is_open !== undefined ? position.is_open : true
        }
        const marginValue = position.margin_used
        const pnlPercentValue = position.pnl_percentage
        normalized.margin_used = marginValue !== undefined ? marginValue : calculateMarginUsed(normalized)
        normalized.pnl_percentage = pnlPercentValue !== undefined ? pnlPercentValue : calculatePnlPercentage(normalized)
        return normalized
      })
    })
    
    // 筛选后的持仓
    const sortPositions = (list) => {
      return [...list].sort((a, b) => {
        const symbolA = (a.symbol || '').toUpperCase()
        const symbolB = (b.symbol || '').toUpperCase()
        if (symbolA !== symbolB) {
          return symbolA.localeCompare(symbolB, 'en')
        }
        if (a.side === b.side) {
          return 0
        }
        // 做多排在做空之前，方便对比
        return a.side === 'long' ? -1 : 1
      })
    }

    const filteredPositions = computed(() => {
      let baseList = positions.value
      if (positionFilter.value === 'long') {
        baseList = positions.value.filter(p => p.side === 'long')
      } else if (positionFilter.value === 'short') {
        baseList = positions.value.filter(p => p.side === 'short')
      }
      return sortPositions(baseList)
    })
    
    // 持仓统计
    const longPositionsCount = computed(() => {
      return positions.value.filter(p => p.side === 'long').length
    })
    
    const shortPositionsCount = computed(() => {
      return positions.value.filter(p => p.side === 'short').length
    })
    
    const totalUnrealizedPnl = computed(() => {
      return positions.value.reduce((sum, p) => sum + (p.unrealized_pnl || 0), 0)
    })
    
    // 获取当前用户ID
    const getCurrentUserId = () => {
      const user = store.state.auth.user
      return user ? user.id : null
    }
    
    // 格式化日期（显示为北京时间 UTC+8）
    const formatDate = (dateString) => {
      if (!dateString) return '-'
      const date = new Date(dateString)
      // 直接使用北京时区格式化
      return date.toLocaleString('zh-CN', { 
        timeZone: 'Asia/Shanghai',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
      })
    }
    
    const fetchReentryBlocks = async () => {
      reentryLoading.value = true
      try {
        const response = await api.get('/trades/reentry-blocks')
        reentryBlocks.value = (response.data || []).map(block => ({
          ...block,
          id: `${block.user_strategy_id}_${block.symbol}_${block.side}`
        }))
      } catch (error) {
        console.error('获取再入场限制失败:', error)
        ElMessage.error('获取再入场限制失败')
      } finally {
        reentryLoading.value = false
      }
    }
    
    // 获取持仓历史记录
    const fetchPositionHistory = async () => {
      historyLoading.value = true
      try {
        const response = await api.get('/trades/positions/history', { params: { limit: 100 } })
        positionHistory.value = response.data
      } catch (error) {
        console.error('获取持仓历史失败:', error)
        ElMessage.error('获取持仓历史失败')
      } finally {
        historyLoading.value = false
      }
    }
    
    const formatPrice = (value) => {
      if (value === undefined || value === null || isNaN(value)) return '-'
      const str = value.toString()
      if (!str.includes('e') && !str.includes('E')) return str
      const expanded = Number(value).toFixed(16)
      return expanded.replace(/\.?0+$/, '')
    }

    const formatNumber = (value, decimals = 2) => {
      if (value === undefined || value === null || isNaN(value)) return '-'
      return Number(value).toFixed(decimals)
    }
    
    // 处理手动平仓
    const handleClosePosition = async (position) => {
      if (!position || !position.id) {
        ElMessage.error('持仓信息无效')
        return
      }
      
      try {
        await ElMessageBox.confirm(
          `确定要平仓 ${position.symbol} 吗？\n数量: ${position.size}\n当前价: ${position.current_price ? position.current_price.toFixed(4) : '-'}\n未实现盈亏: ${position.unrealized_pnl !== null && position.unrealized_pnl !== undefined ? position.unrealized_pnl.toFixed(2) : '-'}`,
          '确认平仓',
          {
            confirmButtonText: '确定',
            cancelButtonText: '取消',
            type: 'warning',
          }
        )
        
        closingPositionId.value = position.id
        
        const result = await store.dispatch('trades/closePosition', position.id)
        
        if (result.success) {
          ElMessage.success(result.data?.message || '平仓成功')
          // closePosition action 已经会刷新持仓列表，这里只需要刷新再入场限制
          // 添加一个小的延迟确保数据已同步
          setTimeout(async () => {
            try {
              await fetchReentryBlocks()
            } catch (error) {
              console.error('刷新再入场限制失败:', error)
            }
          }, 500)
        } else {
          ElMessage.error(result.error || '平仓失败')
        }
      } catch (error) {
        if (error !== 'cancel') {
          ElMessage.error(error.message || '平仓失败')
        }
      } finally {
        closingPositionId.value = null
      }
    }
    
    const handleUnlockBlock = async (block) => {
      if (!block) return
      unlockingBlockId.value = block.id
      try {
        await api.post('/trades/reentry-blocks/unblock', {
          user_strategy_id: block.user_strategy_id,
          symbol: block.symbol,
          side: block.side
        })
        ElMessage.success('已解除限制')
        await fetchReentryBlocks()
      } catch (error) {
        ElMessage.error(error.response?.data?.detail || error.message || '解除失败')
      } finally {
        unlockingBlockId.value = null
      }
    }
    
    // 手动刷新持仓（完整模式，获取最新价格）- 添加防抖
    const handleRefreshPositions = debounce(async () => {
      try {
        positionsLoading.value = true
        // 使用完整模式（fast=false）获取最新价格
        await store.dispatch('trades/fetchPositions', false)
        ElMessage.success('刷新成功')
      } catch (error) {
        console.error('刷新持仓失败:', error)
        ElMessage.error('刷新失败')
      } finally {
        positionsLoading.value = false
      }
    }, 1000)  // 1秒防抖
    
    // 监听标签页切换，切换到历史时加载数据
    watch(activeTab, (newTab) => {
      if (newTab === 'history' && positionHistory.value.length === 0) {
        fetchPositionHistory()
      }
    })
    
    onMounted(async () => {
      // 确保用户信息已加载
      if (!store.state.auth.user) {
        await store.dispatch('auth/fetchUser')
      }
      
      // 并行加载数据，提升速度
      try {
        positionsLoading.value = true
        // 并行执行，不等待再入场限制
        await Promise.all([
          store.dispatch('trades/fetchPositions'),
          fetchReentryBlocks().catch(err => {
            console.warn('获取再入场限制失败（非关键）:', err)
            // 不显示错误，因为这不是关键数据
          })
        ])
        console.log('初始持仓数据:', store.state.trades.positions)
      } catch (error) {
        console.error('获取持仓数据失败:', error)
        ElMessage.error('获取持仓数据失败')
      } finally {
        positionsLoading.value = false
      }
      
      // 连接 WebSocket 接收实时更新（延迟连接，确保初始数据已加载）
      setTimeout(() => {
        const userId = getCurrentUserId()
        if (userId) {
          console.log('连接持仓 WebSocket，用户ID:', userId)
          store.dispatch('trades/connectPositionsWebSocket', userId)
        } else {
          console.warn('无法获取用户ID，WebSocket 连接失败。请确保已登录。')
        }
      }, 500) // 延迟 500ms 确保初始数据已加载
    })
    
    onUnmounted(() => {
      // 组件卸载时断开 WebSocket（如果只有这个组件在使用）
      // 注意：如果多个组件都需要 WebSocket，应该共享连接
    })
    
    return {
      positions,
      filteredPositions,
      closingPositionId,
      handleClosePosition,
      activeTab,
      positionHistory,
      historyLoading,
      formatDate,
      positionFilter,
      longPositionsCount,
      shortPositionsCount,
      totalUnrealizedPnl,
      formatPrice,
      formatNumber,
      reentryBlocks,
      reentryLoading,
      unlockingBlockId,
      fetchReentryBlocks,
      handleUnlockBlock,
      positionsLoading,
      handleRefreshPositions
    }
  }
}
</script>

<style scoped>
.positions {
  max-width: 1400px;
  margin: 0 auto;
}

.positions-header {
  margin-bottom: 24px;
}

.page-title {
  display: flex;
  align-items: center;
  font-size: 28px;
  font-weight: 600;
  color: var(--apple-text-primary, #fff);
  margin: 0 0 8px 0;
  letter-spacing: -0.5px;
}

.page-subtitle {
  color: var(--apple-text-secondary, rgba(255, 255, 255, 0.7));
  font-size: 14px;
  margin: 0;
}

.profit {
  color: var(--apple-green, #30d158) !important;
  font-weight: bold;
}

.loss {
  color: var(--apple-red, #ff453a) !important;
  font-weight: bold;
}

.stat-item {
  text-align: center;
}

.stat-label {
  font-size: 13px;
  color: var(--apple-text-secondary, rgba(255, 255, 255, 0.7));
  margin-bottom: 10px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.stat-value {
  font-size: 24px;
  font-weight: 700;
  color: var(--apple-text-primary, #fff);
  letter-spacing: -0.5px;
}

:deep(.el-tabs__header) {
  margin-bottom: 20px;
  border-bottom: 1px solid var(--apple-separator, rgba(255, 255, 255, 0.1));
}

:deep(.el-tabs__nav-wrap::after) {
  display: none;
}

:deep(.el-tabs__item) {
  font-weight: 500;
  font-size: 15px;
  color: var(--apple-text-secondary, rgba(255, 255, 255, 0.7));
}

:deep(.el-tabs__item.is-active) {
  color: var(--apple-text-primary, #fff);
}

:deep(.el-tabs__active-bar) {
  background: var(--apple-accent, #0a84ff);
}

:deep(.el-table) {
  border-radius: 12px;
  overflow: hidden;
}

:deep(.el-radio-button__inner) {
  background: var(--apple-bg-tertiary, #2c2c2e);
  border-color: var(--apple-separator, rgba(255, 255, 255, 0.1));
  color: var(--apple-text-secondary, rgba(255, 255, 255, 0.7));
}

:deep(.el-radio-button__original-radio:checked + .el-radio-button__inner) {
  background: var(--apple-accent, #0a84ff);
  border-color: var(--apple-accent, #0a84ff);
  color: #fff;
}

.reentry-card {
  margin-bottom: 20px;
  border-left: 4px solid var(--apple-orange, #ff9f0a);
  background: var(--apple-bg-secondary, #1c1c1e) !important;
}
</style>

