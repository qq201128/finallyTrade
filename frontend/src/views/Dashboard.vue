<template>
  <div class="dashboard">
    <h1>仪表盘</h1>
    <el-row :gutter="20">
      <el-col :span="6">
        <el-card>
          <div class="stat-item">
            <div class="stat-label">持仓数量</div>
            <div class="stat-value">{{ positions.length }}</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card>
          <div class="stat-item">
            <div class="stat-label">未实现盈亏</div>
            <div class="stat-value" :class="totalUnrealizedPnl >= 0 ? 'profit' : 'loss'">
              {{ totalUnrealizedPnl.toFixed(2) }}
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card>
          <div class="stat-item">
            <div class="stat-label">已实现盈亏</div>
            <div class="stat-value" :class="totalRealizedPnl >= 0 ? 'profit' : 'loss'">
              {{ totalRealizedPnl.toFixed(2) }}
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card>
          <div class="stat-item">
            <div class="stat-label">启用策略</div>
            <div class="stat-value">{{ enabledStrategiesCount }}</div>
          </div>
        </el-card>
      </el-col>
    </el-row>
    
    <el-row :gutter="20" style="margin-top: 20px">
      <el-col :span="12">
        <el-card>
          <template #header>
            <span>最近持仓</span>
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
      <el-col :span="12">
        <el-card>
          <template #header>
            <span>最近订单</span>
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

export default {
  name: 'Dashboard',
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
      store.dispatch('trades/fetchPositions')
      store.dispatch('trades/fetchOrders')
      store.dispatch('trades/fetchPnLRecords')
      store.dispatch('trades/fetchTotalRealizedPnl')
      store.dispatch('strategies/fetchUserStrategies')
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
.stat-item {
  text-align: center;
}

.stat-label {
  font-size: 14px;
  color: #666;
  margin-bottom: 10px;
}

.stat-value {
  font-size: 24px;
  font-weight: bold;
}

.profit {
  color: #67c23a;
}

.loss {
  color: #f56c6c;
}
</style>

