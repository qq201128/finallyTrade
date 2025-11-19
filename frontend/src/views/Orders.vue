<template>
  <div class="orders">
    <div class="orders-header">
      <h1 class="page-title">
        <el-icon :size="28" style="margin-right: 12px"><List /></el-icon>
        订单管理
      </h1>
      <p class="page-subtitle">查看和管理您的所有交易订单</p>
    </div>
    <el-table :data="orders || []" style="width: 100%" v-loading="!orders">
      <el-table-column prop="symbol" label="交易对"></el-table-column>
      <el-table-column prop="side" label="方向">
        <template #default="scope">
          <span v-if="scope.row && scope.row.side">
            {{ scope.row.side === 'BUY' || scope.row.side === 'buy' ? '买入' : '卖出' }}
          </span>
          <span v-else>-</span>
        </template>
      </el-table-column>
      <el-table-column prop="type" label="类型">
        <template #default="scope">
          <span v-if="scope.row && scope.row.type">
            {{ scope.row.type === 'MARKET' || scope.row.type === 'market' ? '市价' : '限价' }}
          </span>
          <span v-else>-</span>
        </template>
      </el-table-column>
      <el-table-column prop="amount" label="数量">
        <template #default="scope">
          {{ scope.row && scope.row.amount ? scope.row.amount : '-' }}
        </template>
      </el-table-column>
      <el-table-column prop="price" label="价格">
        <template #default="scope">
          {{ scope.row && scope.row.price ? scope.row.price : '-' }}
        </template>
      </el-table-column>
      <el-table-column prop="filled" label="已成交">
        <template #default="scope">
          {{ scope.row && scope.row.filled ? scope.row.filled : '-' }}
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
      <el-table-column prop="pnl_percentage" label="盈亏 %" width="120">
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
          <el-tag v-if="scope.row && scope.row.status" :type="getStatusType(scope.row.status)">
            {{ getStatusText(scope.row.status) }}
          </el-tag>
          <span v-else>-</span>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script>
import { computed, onMounted } from 'vue'
import { useStore } from 'vuex'
import { List } from '@element-plus/icons-vue'

export default {
  name: 'Orders',
  components: {
    List
  },
  setup() {
    const store = useStore()
    
    const orders = computed(() => {
      const ordersList = store.state.trades.orders || []
      // 确保每个订单都有必要的字段
      return ordersList.map(order => ({
        ...order,
        side: order.side || '',
        type: order.type || '',
        status: order.status || 'pending',
        amount: order.amount || 0,
        price: order.price || null,
        filled: order.filled || 0
      }))
    })
    
    const getStatusType = (status) => {
      const statusMap = {
        'filled': 'success',           // 已成交 - 绿色
        'partially_filled': 'warning', // 部分成交 - 橙色
        'open': 'warning',             // 开放中 - 橙色
        'pending': 'info',             // 待处理 - 蓝色
        'closed': 'success',           // 已关闭 - 绿色
        'canceled': 'danger'            // 已取消 - 红色
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
      store.dispatch('trades/fetchOrders')
    })
    
    return {
      orders,
      getStatusType,
      getStatusText
    }
  }
}
</script>

<style scoped>
.orders {
  max-width: 1400px;
  margin: 0 auto;
}

.orders-header {
  margin-bottom: 24px;
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

.profit {
  color: #67c23a;
  font-weight: bold;
}

.loss {
  color: #f56c6c;
  font-weight: bold;
}

:deep(.el-table) {
  border-radius: 8px;
  overflow: hidden;
}
</style>

