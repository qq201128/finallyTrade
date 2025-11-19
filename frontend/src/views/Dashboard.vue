<template>
  <div class="dashboard">
    <div class="dashboard-header">
      <h1 class="page-title">
        <el-icon :size="28" style="margin-right: 12px"><DataBoard /></el-icon>
        仪表盘
      </h1>
      <p class="page-subtitle">实时监控您的交易数据和策略表现</p>
    </div>
    
    <el-row :gutter="20" class="stats-row">
      <el-col :xs="24" :sm="12" :md="6">
        <el-card class="stat-card stat-card-1" shadow="hover">
          <div class="stat-item">
            <div class="stat-icon-wrapper icon-1">
              <el-icon :size="32"><Wallet /></el-icon>
            </div>
            <div class="stat-content">
              <div class="stat-label">持仓数量</div>
              <div class="stat-value">{{ positions.length }}</div>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="12" :md="6">
        <el-card class="stat-card stat-card-2" shadow="hover">
          <div class="stat-item">
            <div class="stat-icon-wrapper icon-2">
              <el-icon :size="32"><TrendCharts /></el-icon>
            </div>
            <div class="stat-content">
              <div class="stat-label">未实现盈亏</div>
              <div class="stat-value" :class="totalUnrealizedPnl >= 0 ? 'profit' : 'loss'">
                {{ totalUnrealizedPnl >= 0 ? '+' : '' }}{{ totalUnrealizedPnl.toFixed(2) }}
              </div>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="12" :md="6">
        <el-card class="stat-card stat-card-3" shadow="hover">
          <div class="stat-item">
            <div class="stat-icon-wrapper icon-3">
              <el-icon :size="32"><Money /></el-icon>
            </div>
            <div class="stat-content">
              <div class="stat-label">已实现盈亏</div>
              <div class="stat-value" :class="totalRealizedPnl >= 0 ? 'profit' : 'loss'">
                {{ totalRealizedPnl >= 0 ? '+' : '' }}{{ totalRealizedPnl.toFixed(2) }}
              </div>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="12" :md="6">
        <el-card class="stat-card stat-card-4" shadow="hover">
          <div class="stat-item">
            <div class="stat-icon-wrapper icon-4">
              <el-icon :size="32"><Setting /></el-icon>
            </div>
            <div class="stat-content">
              <div class="stat-label">启用策略</div>
              <div class="stat-value">{{ enabledStrategiesCount }}</div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>
    
    <el-row :gutter="20" class="data-row">
      <el-col :xs="24" :lg="12">
        <el-card class="data-card">
          <template #header>
            <div class="card-header-title">
              <el-icon><Wallet /></el-icon>
              <span>最近持仓</span>
            </div>
          </template>
          <el-table :data="(positions || []).slice(0, 5)" style="width: 100%">
            <el-table-column prop="symbol" label="交易对">
              <template #default="scope">
                {{ scope.row && scope.row.symbol ? scope.row.symbol : '-' }}
              </template>
            </el-table-column>
            <el-table-column prop="size" label="数量">
              <template #default="scope">
                {{ scope.row && scope.row.size ? scope.row.size : '-' }}
              </template>
            </el-table-column>
            <el-table-column prop="entry_price" label="开仓价">
              <template #default="scope">
                {{ scope.row && scope.row.entry_price ? scope.row.entry_price.toFixed(4) : '-' }}
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
            <el-table-column prop="pnl_percentage" label="盈亏 %" width="100">
              <template #default="scope">
                <span v-if="scope.row && scope.row.pnl_percentage !== null && scope.row.pnl_percentage !== undefined"
                      :class="scope.row.pnl_percentage >= 0 ? 'profit' : 'loss'">
                  {{ scope.row.pnl_percentage.toFixed(2) }}%
                </span>
                <span v-else>-</span>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
      <el-col :xs="24" :lg="12">
        <el-card class="data-card">
          <template #header>
            <div class="card-header-title">
              <el-icon><List /></el-icon>
              <span>最近订单</span>
            </div>
          </template>
          <el-table :data="(orders || []).slice(0, 5)" style="width: 100%">
            <el-table-column prop="symbol" label="交易对">
              <template #default="scope">
                {{ scope.row && scope.row.symbol ? scope.row.symbol : '-' }}
              </template>
            </el-table-column>
            <el-table-column prop="side" label="方向">
              <template #default="scope">
                <span v-if="scope.row && scope.row.side">
                  {{ scope.row.side === 'BUY' || scope.row.side === 'buy' ? '买入' : '卖出' }}
                </span>
                <span v-else>-</span>
              </template>
            </el-table-column>
            <el-table-column prop="amount" label="数量">
              <template #default="scope">
                {{ scope.row && scope.row.amount ? scope.row.amount : '-' }}
              </template>
            </el-table-column>
            <el-table-column prop="realized_pnl" label="已实现盈亏" width="120">
              <template #default="scope">
                <span v-if="scope.row && scope.row.realized_pnl !== null && scope.row.realized_pnl !== undefined" 
                      :class="scope.row.realized_pnl >= 0 ? 'profit' : 'loss'">
                  {{ scope.row.realized_pnl.toFixed(2) }}
                </span>
                <span v-else>-</span>
              </template>
            </el-table-column>
            <el-table-column prop="pnl_percentage" label="盈亏 %" width="100">
              <template #default="scope">
                <span v-if="scope.row && scope.row.pnl_percentage !== null && scope.row.pnl_percentage !== undefined"
                      :class="scope.row.pnl_percentage >= 0 ? 'profit' : 'loss'">
                  {{ scope.row.pnl_percentage.toFixed(2) }}%
                </span>
                <span v-else>-</span>
              </template>
            </el-table-column>
            <el-table-column prop="status" label="状态">
              <template #default="scope">
                <el-tag v-if="scope.row && scope.row.status" :type="getStatusType(scope.row.status)" size="small">
                  {{ getStatusText(scope.row.status) }}
                </el-tag>
                <span v-else>-</span>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script>
import { computed, onMounted } from 'vue'
import { useStore } from 'vuex'
import { DataBoard, Wallet, TrendCharts, Money, Setting, List } from '@element-plus/icons-vue'

export default {
  name: 'Dashboard',
  components: {
    DataBoard,
    Wallet,
    TrendCharts,
    Money,
    Setting,
    List
  },
  setup() {
    const store = useStore()
    
    const positions = computed(() => store.state.trades.positions)
    const orders = computed(() => store.state.trades.orders)
    const pnlRecords = computed(() => store.state.trades.pnlRecords)
    const userStrategies = computed(() => store.state.strategies.userStrategies)
    
    const totalUnrealizedPnl = computed(() => {
      return positions.value.reduce((sum, p) => sum + (p.unrealized_pnl || 0), 0)
    })
    
    const totalRealizedPnl = computed(() => {
      return store.state.trades.totalRealizedPnl || 0
    })
    
    const enabledStrategiesCount = computed(() => {
      return userStrategies.value.filter(s => s.is_enabled).length
    })
    
    const getStatusType = (status) => {
      const statusMap = {
        'filled': 'success',
        'partially_filled': 'warning',
        'open': 'warning',
        'pending': 'info',
        'closed': 'success',
        'canceled': 'danger'
      }
      return statusMap[status] || 'info'
    }
    
    const getStatusText = (status) => {
      const statusTextMap = {
        'filled': '已成交',
        'partially_filled': '部分成交',
        'open': '开放中',
        'pending': '待处理',
        'closed': '已关闭',
        'canceled': '已取消'
      }
      return statusTextMap[status] || status
    }
    
    onMounted(() => {
      // 并行加载所有数据，提升加载速度
      Promise.all([
        store.dispatch('trades/fetchPositions'),
        store.dispatch('trades/fetchOrders'),
        store.dispatch('trades/fetchPnLRecords'),
        store.dispatch('trades/fetchTotalRealizedPnl'),
        store.dispatch('strategies/fetchUserStrategies')
      ]).catch(error => {
        console.error('加载数据失败:', error)
      })
    })
    
    return {
      positions,
      orders,
      totalUnrealizedPnl,
      totalRealizedPnl,
      enabledStrategiesCount,
      getStatusType,
      getStatusText
    }
  }
}
</script>

<style scoped>
.dashboard {
  max-width: 1400px;
  margin: 0 auto;
}

.dashboard-header {
  margin-bottom: 32px;
}

.page-title {
  display: flex;
  align-items: center;
  font-size: 28px;
  font-weight: 600;
  color: #303133;
  margin: 0 0 8px 0;
}

.page-subtitle {
  color: #909399;
  font-size: 14px;
  margin: 0;
}

.stats-row {
  margin-bottom: 24px;
}

.stat-card {
  height: 100%;
  transition: all 0.3s;
  border: none;
  overflow: hidden;
  position: relative;
}

.stat-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 4px;
  background: linear-gradient(90deg, var(--card-gradient-start), var(--card-gradient-end));
  opacity: 0;
  transition: opacity 0.3s;
}

.stat-card:hover::before {
  opacity: 1;
}

.stat-card-1 {
  --card-gradient-start: #667eea;
  --card-gradient-end: #764ba2;
}

.stat-card-2 {
  --card-gradient-start: #f093fb;
  --card-gradient-end: #f5576c;
}

.stat-card-3 {
  --card-gradient-start: #4facfe;
  --card-gradient-end: #00f2fe;
}

.stat-card-4 {
  --card-gradient-start: #43e97b;
  --card-gradient-end: #38f9d7;
}

.stat-item {
  display: flex;
  align-items: center;
  padding: 8px 0;
}

.stat-icon-wrapper {
  width: 64px;
  height: 64px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-right: 16px;
  flex-shrink: 0;
}

.icon-1 {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: #fff;
}

.icon-2 {
  background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
  color: #fff;
}

.icon-3 {
  background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
  color: #fff;
}

.icon-4 {
  background: linear-gradient(135deg, #43e97b 0%, #38f9d7 100%);
  color: #fff;
}

.stat-content {
  flex: 1;
}

.stat-label {
  font-size: 14px;
  color: #909399;
  margin-bottom: 8px;
  font-weight: 500;
}

.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: #303133;
  line-height: 1.2;
}

.profit {
  color: #67c23a;
}

.loss {
  color: #f56c6c;
}

.data-row {
  margin-top: 24px;
}

.data-card {
  height: 100%;
}

.card-header-title {
  display: flex;
  align-items: center;
  font-weight: 600;
  color: #303133;
}

.card-header-title .el-icon {
  margin-right: 8px;
  color: #667eea;
}

:deep(.el-table) {
  font-size: 14px;
}

:deep(.el-table th) {
  background: #fafbfc;
  font-weight: 600;
}

:deep(.el-table td) {
  padding: 12px 0;
}
</style>

