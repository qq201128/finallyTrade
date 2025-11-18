/**
 * 状态转换工具函数
 * 统一管理订单状态、方向、类型等的中文显示
 */

/**
 * 获取订单状态的中文文本
 * @param {string} status - 订单状态
 * @returns {string} 中文状态文本
 */
export function getOrderStatusText(status) {
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

/**
 * 获取订单状态的标签类型（用于 Element Plus 的 el-tag）
 * @param {string} status - 订单状态
 * @returns {string} 标签类型
 */
export function getOrderStatusType(status) {
  const statusMap = {
    'filled': 'success',           // 已成交 - 绿色
    'partially_filled': 'warning', // 部分成交 - 橙色
    'open': 'warning',             // 开放中 - 橙色
    'pending': 'info',             // 待处理 - 蓝色
    'closed': 'success',          // 已关闭 - 绿色
    'canceled': 'danger'           // 已取消 - 红色
  }
  return statusMap[status] || 'info'
}

/**
 * 获取订单方向的中文文本
 * @param {string} side - 订单方向 (BUY/SELL 或 buy/sell)
 * @returns {string} 中文方向文本
 */
export function getOrderSideText(side) {
  if (!side) return ''
  const upperSide = side.toUpperCase()
  return upperSide === 'BUY' ? '买入' : '卖出'
}

/**
 * 获取持仓方向的中文文本
 * @param {string} side - 持仓方向 (long/short)
 * @returns {string} 中文方向文本
 */
export function getPositionSideText(side) {
  if (!side) return ''
  return side.toLowerCase() === 'long' ? '做多' : '做空'
}

/**
 * 获取订单类型的中文文本
 * @param {string} type - 订单类型 (MARKET/LIMIT 或 market/limit)
 * @returns {string} 中文类型文本
 */
export function getOrderTypeText(type) {
  if (!type) return ''
  const upperType = type.toUpperCase()
  return upperType === 'MARKET' ? '市价' : '限价'
}

