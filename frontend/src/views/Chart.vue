<template>
  <div class="chart-container">
    <h1>图表分析</h1>
    <el-form :inline="true" style="margin-bottom: 20px">
      <el-form-item label="交易对">
        <el-select v-model="selectedSymbol" placeholder="请选择交易对" @change="loadChart">
          <el-option
            v-for="symbol in symbols"
            :key="symbol"
            :label="symbol"
            :value="symbol"
          ></el-option>
        </el-select>
      </el-form-item>
      <el-form-item label="时间周期">
        <el-select v-model="timeframe" placeholder="请选择时间周期" @change="loadChart">
          <el-option label="1分钟" value="1m"></el-option>
          <el-option label="5分钟" value="5m"></el-option>
          <el-option label="15分钟" value="15m"></el-option>
          <el-option label="1小时" value="1h"></el-option>
          <el-option label="4小时" value="4h"></el-option>
          <el-option label="1天" value="1d"></el-option>
        </el-select>
      </el-form-item>
    </el-form>
    <div ref="chartContainer" class="chart"></div>
  </div>
</template>

<script>
import { ref, onMounted, onUnmounted } from 'vue'
import { createChart, ColorType } from 'lightweight-charts'
import api from '@/services/api'

export default {
  name: 'Chart',
  setup() {
    const chartContainer = ref(null)
    const selectedSymbol = ref('BTC/USDT')
    const timeframe = ref('1h')
    const symbols = ref(['BTC/USDT', 'ETH/USDT', 'BNB/USDT'])
    let chart = null
    let candlestickSeries = null
    
    const initChart = () => {
      if (!chartContainer.value) return
      
      chart = createChart(chartContainer.value, {
        layout: {
          background: { type: ColorType.Solid, color: 'white' },
          textColor: 'black',
        },
        width: chartContainer.value.clientWidth,
        height: 600,
        grid: {
          vertLines: {
            color: '#f0f0f0',
          },
          horzLines: {
            color: '#f0f0f0',
          },
        },
        timeScale: {
          timeVisible: true,
          secondsVisible: false,
        },
      })
      
      candlestickSeries = chart.addCandlestickSeries({
        upColor: '#26a69a',
        downColor: '#ef5350',
        borderVisible: false,
        wickUpColor: '#26a69a',
        wickDownColor: '#ef5350',
      })
    }
    
    const loadChart = async () => {
      if (!candlestickSeries) return
      
      try {
        // 这里应该调用后端API获取OHLCV数据
        // 由于后端API需要交易所配置，这里使用模拟数据
        const mockData = generateMockData()
        candlestickSeries.setData(mockData)
        chart.timeScale().fitContent()
      } catch (error) {
        console.error('加载图表数据失败:', error)
      }
    }
    
    const generateMockData = () => {
      // 生成模拟K线数据
      const data = []
      const now = Date.now()
      const interval = timeframe.value === '1m' ? 60000 :
                      timeframe.value === '5m' ? 300000 :
                      timeframe.value === '15m' ? 900000 :
                      timeframe.value === '1h' ? 3600000 :
                      timeframe.value === '4h' ? 14400000 : 86400000
      
      let price = 50000
      for (let i = 100; i >= 0; i--) {
        const time = (now - i * interval) / 1000
        const change = (Math.random() - 0.5) * 1000
        const open = price
        const close = price + change
        const high = Math.max(open, close) + Math.random() * 500
        const low = Math.min(open, close) - Math.random() * 500
        price = close
        
        data.push({
          time: time,
          open: open,
          high: high,
          low: low,
          close: close,
        })
      }
      return data
    }
    
    const handleResize = () => {
      if (chart && chartContainer.value) {
        chart.applyOptions({ width: chartContainer.value.clientWidth })
      }
    }
    
    onMounted(() => {
      initChart()
      loadChart()
      window.addEventListener('resize', handleResize)
    })
    
    onUnmounted(() => {
      window.removeEventListener('resize', handleResize)
      if (chart) {
        chart.remove()
      }
    })
    
    return {
      chartContainer,
      selectedSymbol,
      timeframe,
      symbols,
      loadChart
    }
  }
}
</script>

<style scoped>
.chart-container {
  padding: 20px;
}

.chart {
  width: 100%;
  height: 600px;
}
</style>

