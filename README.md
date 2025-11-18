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

### 前端
- Vue 3
- TradingView Lightweight Charts
- Axios（HTTP客户端）
- WebSocket客户端

## 系统架构

```
backend/
├── app/
│   ├── api/          # API路由
│   ├── core/         # 核心配置
│   ├── models/       # 数据库模型
│   ├── services/     # 业务逻辑
│   │   ├── strategy_engine.py    # 策略引擎
│   │   ├── trading_engine.py     # 交易执行引擎
│   │   ├── exchange_service.py    # 交易所服务
│   │   └── user_service.py       # 用户服务
│   ├── strategies/   # 策略文件目录
│   └── main.py       # 应用入口
├── requirements.txt
└── config.py

frontend/
├── src/
│   ├── components/   # Vue组件
│   ├── views/        # 页面视图
│   ├── services/     # API服务
│   └── main.js
└── package.json
```

## 系统逻辑流程

1. 从持久化存储中获取未平仓交易
2. 计算当前可交易的交易对列表
3. 下载交易对列表的OHLCV数据（每个K线周期仅执行一次）
4. 调用策略回调函数（与货币对无关的计算）
5. 按交易对分析策略（入场和出场信号）
6. 从交易所更新交易的挂单状态（order_filled回调）
7. 验证现有持仓并视情况下达卖出平仓订单
8. 仓位调整（如启用）
9. 验证买入信号，尝试开立新仓位

## 快速开始

### 环境要求
- Python 3.9+
- Node.js 16+
- npm 或 yarn

### 后端启动

1. 创建并激活虚拟环境（推荐）

**Windows系统：**
```bash
cd backend
# 创建虚拟环境
python -m venv venv

# 激活虚拟环境
venv\Scripts\activate
```

**Linux/Mac系统：**
```bash
cd backend
# 创建虚拟环境
python3 -m venv venv

# 激活虚拟环境
source venv/bin/activate
```

激活成功后，命令行提示符前会显示 `(venv)`。

**自动激活虚拟环境的方法：**

**方法1：使用启动脚本（推荐）**
- Windows CMD: 双击 `activate_env.bat` 或 `start_backend.bat`
- PowerShell: 运行 `.\activate_env.ps1` 或 `.\start_backend.ps1`

**方法2：配置 PowerShell Profile（永久自动激活）**
```powershell
# 查看 Profile 路径
$PROFILE

# 如果文件不存在，创建它
if (!(Test-Path -Path $PROFILE)) {
    New-Item -ItemType File -Path $PROFILE -Force
}

# 添加自动激活脚本（编辑 $PROFILE 文件）
# 在文件末尾添加：
# Set-Location D:\Desktop\finallyTrade\backend
# & "D:\Desktop\finallyTrade\backend\venv\Scripts\Activate.ps1"
```

**方法3：创建快捷方式**
- 右键 `start_backend.bat` → 创建快捷方式
- 将快捷方式放到桌面或任务栏，双击即可启动

2. 安装依赖
```bash
pip install -r requirements.txt
```

3. 配置环境变量（可选）

**Windows系统：**
```bash
cd backend
copy .env.example .env
# 然后编辑 .env 文件，配置代理等参数
```

**Linux/Mac系统：**
```bash
cd backend
cp .env.example .env
# 然后编辑 .env 文件，配置代理等参数
```

**重要配置项说明：**
- `SECRET_KEY`: JWT密钥，生产环境必须修改为强随机字符串（至少32个字符）
- `DEBUG`: 调试模式，生产环境设置为 `False`
- `DATABASE_URL`: 数据库连接，默认使用SQLite
- `PROXY_URL` 或 `HTTP_PROXY`/`HTTPS_PROXY`: 代理配置（可选，如不需要可保持注释状态）
- `WS_ENABLED`: WebSocket支持，默认 `True`

详细配置说明请参考 `backend/.env.example` 文件中的注释。

4. 初始化数据库
```bash
python init_db.py
```

5. 启动服务
```bash
python run.py
# 或使用 uvicorn
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 前端启动

1. 安装依赖
```bash
cd frontend
npm install
```

2. 启动开发服务器
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
在 `backend/app/strategies/` 目录下创建Python策略文件，参考 `example_strategy.py` 或 `talib_example_strategy.py`（使用TA-Lib技术指标）。

策略文件需要实现以下函数：
- `populate_indicators(dataframe, metadata)`: 填充指标
- `populate_entry_trend(dataframe, metadata)`: 入场信号
- `populate_exit_trend(dataframe, metadata)`: 出场信号
- `before_loop(symbols)`: 循环开始前回调（可选）
- `after_loop(symbols)`: 循环结束后回调（可选）
- `order_filled(order, exchange_order)`: 订单成交回调（可选）
- `entry_conditions(symbol, analysis_result)`: 入场条件检查（可选）
- `custom_exit(position, current_price)`: 自定义退出（可选）
- `adjust_position(position)`: 仓位调整（可选）

### 4. 系统逻辑流程

系统按照以下流程自动执行交易：

1. **获取未平仓交易** - 从数据库加载当前持仓
2. **计算可交易对列表** - 从交易所获取永续合约交易对
3. **下载OHLCV数据** - 获取K线数据（每个周期仅执行一次）
4. **调用策略回调** - 执行与货币对无关的计算
5. **分析策略信号** - 对每个交易对分析入场和出场信号
6. **更新订单状态** - 从交易所同步订单状态，调用order_filled回调
7. **验证并平仓** - 检查止损、止盈、ROI、卖出信号，下达平仓订单
8. **仓位调整** - 如果启用，检查是否需要追加订单
9. **验证并开仓** - 检查买入信号，尝试开立新仓位

循环每5分钟执行一次（可在 `trading_scheduler.py` 中配置）。

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

根据[CCXT Pro官方文档](https://github.com/ccxt/ccxt/wiki/ccxt.pro.manual)，CCXT Pro是CCXT的免费部分，用于添加WebSocket流式支持。

## 注意事项

1. **API密钥安全**: 生产环境中应该加密存储API密钥
2. **策略测试**: 建议先在测试环境或使用模拟交易测试策略
3. **风险控制**: 合理设置止损、止盈和仓位大小
4. **网络稳定**: 确保网络连接稳定，避免订单执行失败
5. **数据备份**: 定期备份数据库，防止数据丢失

## 技术架构

- **后端**: FastAPI + SQLAlchemy + CCXT
- **前端**: Vue 3 + Element Plus + TradingView Lightweight Charts
- **数据库**: SQLite（可切换为PostgreSQL）
- **任务调度**: APScheduler
- **实时通信**: WebSocket

