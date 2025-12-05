"""
初始化数据库和示例数据
"""
from app.core.database import engine, Base, SessionLocal
from app.models import User, Strategy
from app.services.user_service import create_user
import os

def init_database():
    """初始化数据库表"""
    Base.metadata.create_all(bind=engine)
    print("数据库表创建成功")

def init_sample_data():
    """初始化示例数据"""
    db = SessionLocal()
    try:
        # 创建示例策略
        strategies_dir = "./app/strategies"
        if not os.path.exists(strategies_dir):
            print(f"策略目录不存在: {strategies_dir}")
            return
        
        strategy_files = [f for f in os.listdir(strategies_dir) if f.endswith('.py') and f != '__init__.py']
        
        if not strategy_files:
            print("未找到策略文件")
            return
        
        print(f"找到 {len(strategy_files)} 个策略文件")
        
        for file in strategy_files:
            strategy_name = file.replace('.py', '')
            # 使用绝对路径
            file_path = os.path.abspath(os.path.join(strategies_dir, file))
            
            # 根据策略名称设置描述
            descriptions = {
                'example_strategy': '基础示例策略 - 使用简单移动平均线和RSI指标',
                'talib_example_strategy': 'TA-Lib示例策略 - 使用MACD、RSI、EMA等多种技术指标进行交易决策',
                'quick_test_strategy': '快速测试策略 - 快速开仓平仓，用于测试交易系统功能。盈利1%或亏损1%即平仓',
                'aggressive_quant_strategy': '激进量化加密货币交易策略 - 多时间框架技术分析（3分钟短期 + 4小时中期），激进风险管理（单笔风险8-15%，杠杆15-25x），动态仓位管理（金字塔加仓、分级止盈止损），支持多时间框架分析，突破追踪、极端RSI反转、动量追踪等激进策略。适合风险承受能力强的交易者，适合高波动市场环境。目标年化收益：120-200%，预期最大回撤：30-40%',
                'bidirectional_example_strategy': '双向交易示例策略 - 支持同时持有多头和空头仓位，RSI超卖时开多，RSI超买时开空，使用分离的long/short信号函数，支持双向补仓和双向平仓，正确的盈亏计算和止损止盈。适合需要同时做多和做空的策略，适合震荡市场和趋势反转市场。注意：使用此策略需要在前端配置中开启"双向交易"选项',
                'grid_strategy': '网格交易策略 - 设置基准价和网格大小（默认2%），价格跌破下轨时监测买入机会，反弹后自动买入；价格突破上轨时监测卖出机会，回落后自动卖出。适合震荡行情，低买高卖赚取差价。参考GridBNB-USDT项目'
            }
            
            description = descriptions.get(strategy_name, f"策略文件: {file}")
            
            # 检查策略是否已存在
            existing = db.query(Strategy).filter(Strategy.name == strategy_name).first()
            if existing:
                # 更新已存在的策略描述和文件路径
                existing.description = description
                existing.file_path = file_path
                print(f"[更新] 策略 {strategy_name} - {description}")
            else:
                # 创建新策略
                strategy = Strategy(
                    name=strategy_name,
                    description=description,
                    file_path=file_path,
                    is_active=True,
                    config={}
                )
                db.add(strategy)
                print(f"[创建] 策略 {strategy_name} - {description}")
        
        db.commit()
        print(f"\n成功初始化 {len(strategy_files)} 个策略")
    except Exception as e:
        print(f"初始化示例数据失败: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    print("=" * 50)
    print("初始化数据库...")
    print("=" * 50)
    init_database()
    print("\n" + "=" * 50)
    print("初始化示例数据...")
    print("=" * 50)
    init_sample_data()
    print("\n" + "=" * 50)
    print("初始化完成！")
    print("=" * 50)

