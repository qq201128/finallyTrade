# 多策略多用户永续合约交易系统

## 项目概述

支持多用户、多策略的永续合约交易系统，后端使用CCXT获取数据，前端使用Vue + TradingView图表展示。

## 技术栈

### 后端
- Python 3.9+
- FastAPI（异步API框架）
- CCXT（交易所集成，支持代理和WebSocket）
- SQLAlchemy（ORM）
- SQLite/PostgreSQL（数据持久化）
- WebSocket（实时数据推送）
- APScheduler（任务调度）

### 前端
- Vue 3
- Element Plus（UI组件库）
- TradingView Lightweight Charts（图表库）
- Vuex（状态管理）
- Vue Router（路由）
- Axios（HTTP客户端）

## 系统架构

```
backend/
├── app/
│   ├── api/          # API路由
│   │   ├── auth.py       # 用户认证
│   │   ├── strategies.py # 策略管理
│   │   ├── trades.py     # 交易相关
│   │   └── websocket.py  # WebSocket
│   ├── core/         # 核心配置
│   │   ├── config.py     # 配置管理
│   │   └── database.py   # 数据库连接
│   ├── models/       # 数据库模型
│   │   ├── user.py       # 用户模型
│   │   ├── strategy.py   # 策略模型
│   │   └── trade.py      # 交易模型
│   ├── services/     # 业务逻辑
│   │   ├── strategy_engine.py    # 策略引擎
│   │   ├── trading_engine.py     # 交易执行引擎
│   │   ├── exchange_service.py   # 交易所服务
│   │   ├── trading_scheduler.py  # 任务调度
│   │   └── user_service.py       # 用户服务
│   ├── strategies/   # 策略文件目录
│   │   ├── base_strategy.py      # 策略基类
│   │   └── *.py                  # 自定义策略文件
│   └── main.py       # 应用入口
├── requirements.txt
├── init_db.py        # 数据库初始化
└── run.py            # 启动脚本

frontend/
├── src/
│   ├── views/        # 页面视图
│   │   ├── Login.vue
│   │   ├── Register.vue
│   │   ├── Dashboard.vue
│   │   ├── Strategies.vue
│   │   ├── Positions.vue
│   │   ├── Orders.vue
│   │   └── Chart.vue
│   ├── store/        # Vuex状态管理
│   ├── services/     # API服务
│   ├── router/       # 路由配置
│   └── main.js       # 应用入口
└── package.json
```

## 核心功能

### 后端功能
- ✅ 用户认证系统（注册、登录、JWT Token）
- ✅ 策略管理系统（动态加载、多用户多策略）
- ✅ 交易所集成（CCXT，支持代理和WebSocket）
- ✅ 交易执行引擎（9步交易循环逻辑）
- ✅ 数据持久化（SQLite/PostgreSQL）
- ✅ WebSocket实时推送
- ✅ 任务调度（APScheduler）

### 前端功能
- ✅ 用户界面（登录、注册、仪表盘）
- ✅ 策略管理页面
- ✅ 持仓管理页面
- ✅ 订单管理页面
- ✅ TradingView图表展示
- ✅ WebSocket实时数据更新

## 快速开始

### 环境要求
- Python 3.9+
- Node.js 16+
- npm 或 yarn

### 后端启动

1. **创建并激活虚拟环境**

**Windows系统：**
```bash
cd backend
python -m venv venv
venv\Scripts\activate
```

**Linux/Mac系统：**
```bash
cd backend
python3 -m venv venv
source venv/bin/activate
```

2. **安装依赖**
```bash
pip install -r requirements.txt
```

3. **配置环境变量（可选）**
```bash
# 复制环境变量模板
copy .env.example .env  # Windows
# cp .env.example .env  # Linux/Mac

# 编辑 .env 文件，配置：
# - SECRET_KEY: JWT密钥
# - DATABASE_URL: 数据库连接
# - PROXY_URL: 代理配置（可选）
# - WS_ENABLED: WebSocket支持
```

4. **初始化数据库**
```bash
python init_db.py
```

5. **启动服务**
```bash
python run.py
# 或使用 uvicorn
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 前端启动

1. **安装依赖**
```bash
cd frontend
npm install
```

2. **启动开发服务器**
```bash
npm run serve
```

访问 http://localhost:8080

## 使用说明

### 1. 用户注册和登录
- 访问前端页面，注册新用户
- 使用用户名和密码登录

### 2. 添加策略
- 在"策略管理"页面，可以查看系统策略文件
- 点击"添加策略"，配置：
  - 选择策略
  - 输入交易所名称（如：binance, okx）
  - 输入API Key和API Secret
  - 配置策略参数（可选）

### 3. 编写自定义策略

在 `backend/app/strategies/` 目录下创建Python策略文件，参考示例策略。

**必须实现的函数：**
- `populate_indicators(dataframe, metadata)`: 填充指标
- `populate_entry_trend(dataframe, metadata)`: 入场信号
- `populate_exit_trend(dataframe, metadata)`: 出场信号

**可选实现的函数：**
- `before_loop(symbols)`: 循环开始前回调
- `after_loop(symbols)`: 循环结束后回调
- `order_filled(order, exchange_order)`: 订单成交回调
- `entry_conditions(symbol, analysis_result)`: 入场条件检查
- `custom_exit(position, current_price)`: 自定义退出
- `adjust_position(position)`: 仓位调整

**策略基类：**
策略可以继承 `BaseStrategy` 基类来复用公共方法，也可以选择重写特定方法。

### 4. 系统交易流程

系统按照以下9步循环执行（每5分钟一次）：

1. **获取未平仓交易** - 从数据库加载当前持仓
2. **计算可交易对列表** - 从交易所获取永续合约交易对
3. **下载OHLCV数据** - 获取K线数据（每个周期仅执行一次）
4. **调用策略回调** - 执行与货币对无关的计算
5. **分析策略信号** - 对每个交易对分析入场和出场信号
6. **更新订单状态** - 从交易所同步订单状态，调用order_filled回调
7. **验证并平仓** - 检查止损、止盈、ROI、卖出信号，下达平仓订单
8. **仓位调整** - 如果启用，检查是否需要追加订单
9. **验证并开仓** - 检查买入信号，尝试开立新仓位

### 5. 查看交易数据
- **仪表盘**: 查看持仓数量、盈亏、策略状态
- **持仓**: 查看当前所有持仓
- **订单**: 查看历史订单记录
- **图表**: 使用TradingView图表查看K线数据

## 配置说明

### 代理配置
在 `.env` 文件中配置代理：
```
PROXY_URL=http://proxy.example.com:8080
# 或
HTTP_PROXY=http://proxy.example.com:8080
HTTPS_PROXY=http://proxy.example.com:8080
SOCKS_PROXY=socks5://proxy.example.com:1080
```

### WebSocket支持
系统支持CCXT Pro的WebSocket功能（CCXT Pro是CCXT的免费部分，无需许可证）。在配置中设置：
```
WS_ENABLED=True
```

### 数据库配置
```
DATABASE_URL=sqlite:///./trading_system.db
# 或 PostgreSQL
DATABASE_URL=postgresql://user:password@localhost/dbname
```

## API文档

启动后端服务后，访问：
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## 注意事项

1. **API密钥安全**: 生产环境中应该加密存储API密钥
2. **策略测试**: 建议先在测试环境或使用模拟交易测试策略
3. **风险控制**: 合理设置止损、止盈和仓位大小
4. **网络稳定**: 确保网络连接稳定，避免订单执行失败
5. **数据备份**: 定期备份数据库，防止数据丢失

## 开发计划

- [ ] API密钥加密存储
- [ ] 策略回测功能
- [ ] 更完善的错误处理和重试机制
- [ ] 更详细的日志和监控
- [ ] 性能优化（异步处理、缓存优化）
- [ ] 单元测试和集成测试
- [ ] Docker容器化部署

## 许可证

MIT License
