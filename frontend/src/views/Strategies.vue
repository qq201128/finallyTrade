<template>
  <div class="strategies">
    <h1>策略管理</h1>
    
    <el-tabs v-model="activeTab">
      <el-tab-pane label="系统策略" name="system">
        <el-table :data="strategies" style="width: 100%">
          <el-table-column prop="name" label="策略名称"></el-table-column>
          <el-table-column prop="description" label="描述"></el-table-column>
          <el-table-column label="操作">
            <template #default="scope">
              <el-button size="small" @click="handleAddStrategy(scope.row)">添加</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
      
      <el-tab-pane label="我的策略" name="user">
        <el-button type="primary" @click="handleAddStrategy(null)" style="margin-bottom: 20px">添加策略</el-button>
        <el-table :data="userStrategies" style="width: 100%">
          <el-table-column prop="strategy.name" label="策略名称">
            <template #default="scope">
              {{ getStrategyDisplayName(scope.row.strategy?.name || '') }}
            </template>
          </el-table-column>
          <el-table-column prop="exchange" label="交易所"></el-table-column>
          <el-table-column label="币种" width="150">
            <template #default="scope">
              <el-tag v-for="symbol in (scope.row.symbols || [])" :key="symbol" size="small" style="margin-right: 5px">
                {{ symbol }}
              </el-tag>
              <span v-if="!scope.row.symbols || scope.row.symbols.length === 0" style="color: #999">全部</span>
            </template>
          </el-table-column>
          <el-table-column prop="timeframe" label="时间周期" width="100"></el-table-column>
          <el-table-column prop="trade_amount" label="交易数量" width="120"></el-table-column>
          <el-table-column label="模拟运行" width="100">
            <template #default="scope">
              <el-tag :type="scope.row.is_simulated ? 'warning' : 'success'" size="small">
                {{ scope.row.is_simulated ? '是' : '否' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="is_enabled" label="状态" width="80">
            <template #default="scope">
              <el-tag :type="scope.row.is_enabled ? 'success' : 'info'">
                {{ scope.row.is_enabled ? '启用' : '禁用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="双向交易" width="100">
            <template #default="scope">
              <el-tag :type="scope.row.config?.bidirectional_trading ? 'success' : 'info'" size="small">
                {{ scope.row.config?.bidirectional_trading ? '是' : '否' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="200">
            <template #default="scope">
              <el-button size="small" @click="handleEditStrategy(scope.row)">编辑</el-button>
              <el-button size="small" @click="handleToggleStrategy(scope.row)">
                {{ scope.row.is_enabled ? '禁用' : '启用' }}
              </el-button>
              <el-button size="small" type="danger" @click="handleDeleteStrategy(scope.row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
      
      <el-tab-pane label="策略历史" name="history">
        <el-select 
          v-model="selectedStrategyId" 
          placeholder="请选择策略查看历史" 
          style="width: 300px; margin-bottom: 20px"
          @change="handleStrategyChange"
        >
          <el-option
            v-for="strategy in userStrategies"
            :key="strategy.id"
            :label="`${getStrategyDisplayName(strategy.strategy?.name || '')} (${strategy.exchange})`"
            :value="strategy.id"
          ></el-option>
        </el-select>
        
        <el-table :data="strategyHistory" style="width: 100%" v-loading="historyLoading">
          <el-table-column prop="started_at" label="启动时间" width="180">
            <template #default="scope">
              {{ formatDate(scope.row.started_at) }}
            </template>
          </el-table-column>
          <el-table-column prop="stopped_at" label="停止时间" width="180">
            <template #default="scope">
              {{ scope.row.stopped_at ? formatDate(scope.row.stopped_at) : '-' }}
            </template>
          </el-table-column>
          <el-table-column prop="total_realized_pnl" label="已实现盈亏" width="150">
            <template #default="scope">
              <span :class="scope.row.total_realized_pnl >= 0 ? 'profit' : 'loss'">
                {{ scope.row.total_realized_pnl.toFixed(2) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="total_trades" label="交易次数" width="120"></el-table-column>
          <el-table-column prop="total_positions" label="持仓数" width="120"></el-table-column>
          <el-table-column prop="is_running" label="状态" width="100">
            <template #default="scope">
              <el-tag :type="scope.row.is_running ? 'success' : 'info'" size="small">
                {{ scope.row.is_running ? '运行中' : '已停止' }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>
    
    <!-- 添加/编辑策略对话框 -->
    <el-dialog
      v-model="dialogVisible"
      :title="isEdit ? '编辑策略' : '添加策略'"
      width="900px"
      class="strategy-dialog"
    >
      <el-form :model="form" label-width="140px">
        <el-form-item label="策略" required>
          <el-select v-model="form.strategy_id" placeholder="请选择策略" :disabled="isEdit" style="width: 100%">
            <el-option
              v-for="strategy in strategies"
              :key="strategy.id"
              :label="getStrategyDisplayName(strategy.name)"
              :value="strategy.id"
            >
              <span>{{ getStrategyDisplayName(strategy.name) }}</span>
              <span style="color: #999; font-size: 12px; margin-left: 10px" v-if="strategy.description">
                {{ strategy.description }}
              </span>
            </el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="交易所" required>
          <el-select 
            v-model="form.exchange" 
            placeholder="请选择交易所" 
            filterable
            allow-create
            default-first-option
            style="width: 100%"
          >
            <el-option
              v-for="exchange in exchanges"
              :key="exchange"
              :label="exchange"
              :value="exchange"
            ></el-option>
          </el-select>
          <div style="color: #999; font-size: 12px; margin-top: 5px">
            支持从列表选择或手动输入（会自动验证）
          </div>
        </el-form-item>
        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item label="API Key（可选）">
              <el-input v-model="form.api_key" type="password" placeholder="请输入API Key" show-password></el-input>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="API Secret（可选）">
              <el-input v-model="form.api_secret" type="password" placeholder="请输入API Secret" show-password></el-input>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="币种（可选）">
          <el-select
            v-model="form.symbols"
            multiple
            filterable
            allow-create
            default-first-option
            placeholder="选择或输入币种，留空则交易所有永续合约"
            style="width: 100%"
            :loading="symbolsLoading"
            :disabled="!form.exchange"
          >
            <el-option
              v-for="symbol in availableSymbols"
              :key="symbol"
              :label="symbol"
              :value="symbol"
            ></el-option>
          </el-select>
          <div style="color: #999; font-size: 12px; margin-top: 5px">
            选择交易所后将自动加载支持的永续合约，您也可以手动输入交易对
          </div>
        </el-form-item>
        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item label="时间周期（可选）">
              <el-select v-model="form.timeframe" placeholder="请选择时间周期" style="width: 100%">
                <el-option label="1分钟" value="1m"></el-option>
                <el-option label="5分钟" value="5m"></el-option>
                <el-option label="15分钟" value="15m"></el-option>
                <el-option label="30分钟" value="30m"></el-option>
                <el-option label="1小时" value="1h"></el-option>
                <el-option label="4小时" value="4h"></el-option>
                <el-option label="1天" value="1d"></el-option>
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="交易数量（可选）">
              <el-input v-model="form.trade_amount" placeholder="每笔交易使用的保证金（USDT），如: 20">
                <template #append>USDT</template>
              </el-input>
              <div style="color: #999; font-size: 12px; margin-top: 5px">
                填写保证金数量，系统会根据杠杆自动计算名义价值
              </div>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="模拟运行">
          <el-switch v-model="form.is_simulated"></el-switch>
          <div style="color: #999; font-size: 12px; margin-top: 5px">
            开启后不会实际下单，仅用于测试策略
          </div>
        </el-form-item>
        <el-form-item label="双向交易">
          <el-switch v-model="form.bidirectional_trading"></el-switch>
          <div style="color: #999; font-size: 12px; margin-top: 5px; line-height: 1.6">
            <div style="margin-bottom: 5px">开启后支持同时持有多头和空头仓位，支持双向补仓和平仓</div>
            <div style="color: #409EFF; font-weight: 500">
              💡 提示：如果您的策略需要同时做多和做空，或者需要根据市场情况灵活切换多空方向，请开启此选项
            </div>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSubmit">{{ isEdit ? '保存' : '确定' }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script>
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useStore } from 'vuex'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '@/services/api'

export default {
  name: 'Strategies',
  setup() {
    const store = useStore()
    const activeTab = ref('user')
    const dialogVisible = ref(false)
    const isEdit = ref(false)
    const editingId = ref(null)
    
    // 动态获取的交易对列表
    const availableSymbols = ref([])
    const symbolsLoading = ref(false)
    
    const form = reactive({
      strategy_id: null,
      exchange: '',
      api_key: '',
      api_secret: '',
      symbols: [],
      timeframe: '',
      trade_amount: '',
      is_simulated: false,
      bidirectional_trading: false,
      config: {}
    })
    
    const strategies = computed(() => store.state.strategies.strategies)
    const userStrategies = computed(() => store.state.strategies.userStrategies)
    const exchanges = computed(() => store.state.strategies.exchanges)
    
    // 策略历史记录
    const selectedStrategyId = ref(null)
    const strategyHistory = ref([])
    const historyLoading = ref(false)
    
    const handleStrategyChange = async (strategyId) => {
      if (!strategyId) {
        strategyHistory.value = []
        return
      }
      
      historyLoading.value = true
      try {
        const response = await api.get(`/strategies/user/${strategyId}/history`)
        strategyHistory.value = response.data
      } catch (error) {
        console.error('获取策略历史失败:', error)
        ElMessage.error('获取策略历史失败')
      } finally {
        historyLoading.value = false
      }
    }
    
    const formatDate = (dateString) => {
      if (!dateString) return '-'
      const date = new Date(dateString)
      return date.toLocaleString('zh-CN')
    }
    
    // 策略名称中文映射
    const strategyNameMap = {
      'example_strategy': '示例策略',
      'quick_test_strategy': '快速测试策略',
      'talib_example_strategy': 'TA-Lib示例策略',
      'aggressive_quant_strategy': '激进量化策略',
      'bidirectional_example_strategy': '双向交易示例策略'
    }
    
    const getStrategyDisplayName = (strategyName) => {
      return strategyNameMap[strategyName] || strategyName
    }
    
    const handleAddStrategy = (strategy) => {
      isEdit.value = false
      editingId.value = null
      availableSymbols.value = []
      Object.assign(form, {
        strategy_id: strategy ? strategy.id : null,
        exchange: '',
        api_key: '',
        api_secret: '',
        symbols: [],
        timeframe: '',
        trade_amount: '',
        is_simulated: false,
        bidirectional_trading: false,
        config: {}
      })
      dialogVisible.value = true
    }
    
    const handleEditStrategy = (userStrategy) => {
      isEdit.value = true
      editingId.value = userStrategy.id
      Object.assign(form, {
        strategy_id: userStrategy.strategy_id,
        exchange: userStrategy.exchange,
        api_key: userStrategy.api_key || '',  // 注意：编辑时API密钥可能为空（安全考虑）
        api_secret: userStrategy.api_secret || '',
        symbols: userStrategy.symbols || [],
        timeframe: userStrategy.timeframe || '',
        trade_amount: userStrategy.trade_amount || '',
        is_simulated: userStrategy.is_simulated || false,
        bidirectional_trading: userStrategy.config?.bidirectional_trading || false,
        config: userStrategy.config || {}
      })
      dialogVisible.value = true
    }
    
    const handleSubmit = async () => {
      if (isEdit.value && editingId.value) {
        // 编辑模式
        const updateData = {
          exchange: form.exchange,
          symbols: form.symbols,
          timeframe: form.timeframe,
          trade_amount: form.trade_amount,
          is_simulated: form.is_simulated,
          config: {
            ...form.config,
            bidirectional_trading: form.bidirectional_trading,
            position_adjustment: true  // 自动开启仓位调整
          }
        }
        // 如果用户输入了新的API密钥，则更新
        if (form.api_key) {
          updateData.api_key = form.api_key
        }
        if (form.api_secret) {
          updateData.api_secret = form.api_secret
        }
        
        const result = await store.dispatch('strategies/updateUserStrategy', {
          id: editingId.value,
          data: updateData
        })
        if (result.success) {
          ElMessage.success('更新成功')
          dialogVisible.value = false
        } else {
          ElMessage.error(result.error)
        }
      } else {
        // 创建模式
        const createData = {
          ...form,
          config: {
            ...form.config,
            bidirectional_trading: form.bidirectional_trading,
            position_adjustment: true  // 自动开启仓位调整
          }
        }
        const result = await store.dispatch('strategies/createUserStrategy', createData)
        if (result.success) {
          ElMessage.success('添加成功')
          dialogVisible.value = false
          Object.assign(form, {
            strategy_id: null,
            exchange: '',
            api_key: '',
            api_secret: '',
            symbols: [],
            timeframe: '1h',
            trade_amount: '0.001',
            is_simulated: false,
            config: {}
          })
        } else {
          ElMessage.error(result.error)
        }
      }
    }
    
    const handleToggleStrategy = async (userStrategy) => {
      const result = await store.dispatch('strategies/updateUserStrategy', {
        id: userStrategy.id,
        data: { is_enabled: !userStrategy.is_enabled }
      })
      if (result.success) {
        ElMessage.success('更新成功')
      } else {
        ElMessage.error(result.error)
      }
    }
    
    const handleDeleteStrategy = async (userStrategy) => {
      try {
        await ElMessageBox.confirm('确定要删除这个策略吗？', '提示', {
          type: 'warning'
        })
        const result = await store.dispatch('strategies/deleteUserStrategy', userStrategy.id)
        if (result.success) {
          ElMessage.success('删除成功')
        } else {
          ElMessage.error(result.error)
        }
      } catch {
        // 用户取消
      }
    }
    
    const fetchAvailableSymbols = async () => {
      if (!form.exchange) {
        availableSymbols.value = []
        return
      }
      symbolsLoading.value = true
      try {
        const response = await api.get('/strategies/symbols', {
          params: { exchange: form.exchange }
        })
        availableSymbols.value = response.data || []
      } catch (error) {
        console.error('获取交易对失败:', error)
        availableSymbols.value = []
        ElMessage.error('获取交易对列表失败，请确认交易所可用')
      } finally {
        symbolsLoading.value = false
      }
    }

    watch(
      () => form.exchange,
      (newVal, oldVal) => {
        if (!newVal) {
          availableSymbols.value = []
          return
        }
        if (oldVal && newVal !== oldVal) {
          form.symbols = []
        }
        fetchAvailableSymbols()
      }
    )

    onMounted(() => {
      store.dispatch('strategies/fetchStrategies')
      store.dispatch('strategies/fetchUserStrategies')
      store.dispatch('strategies/fetchExchanges')
    })
    
    return {
      activeTab,
      dialogVisible,
      isEdit,
      form,
      strategies,
      userStrategies,
      exchanges,
      availableSymbols,
      symbolsLoading,
      selectedStrategyId,
      strategyHistory,
      historyLoading,
      handleAddStrategy,
      handleEditStrategy,
      handleSubmit,
      handleToggleStrategy,
      handleDeleteStrategy,
      handleStrategyChange,
      formatDate,
      getStrategyDisplayName
    }
  }
}
</script>

<style scoped>
.profit {
  color: #67c23a;
  font-weight: bold;
}

.loss {
  color: #f56c6c;
  font-weight: bold;
}
</style>

<style scoped>
.strategies {
  padding: 20px;
}

:deep(.strategy-dialog .el-form-item__label) {
  white-space: nowrap;
}
</style>

