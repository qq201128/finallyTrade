"""
交易调度器 - 管理多个用户策略的交易循环
改为连续循环机制：策略执行完一次后立即开始下一次，直到用户关闭策略
"""
import threading
import time
import logging
from typing import Dict, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.core.database import SessionLocal
from app.models.strategy import UserStrategy, StrategyHistory
from app.models.trade import PnLRecord, Order, Position
from app.services.exchange_service import ExchangeService
from app.services.strategy_engine import StrategyEngine
from app.services.trading_engine import TradingEngine
from app.services.trading_engine_bidirectional import BidirectionalTradingEngine
from app.core.config import settings

logger = logging.getLogger(__name__)

strategy_engine = StrategyEngine(settings.STRATEGIES_DIR)

# 存储每个策略的运行状态和线程
running_threads: Dict[int, threading.Thread] = {}
running_flags: Dict[int, bool] = {}  # 控制循环是否继续
thread_locks: Dict[int, threading.Lock] = {}  # 线程锁


def run_trading_loop_continuous(user_strategy_id: int):
    """
    为特定用户策略持续运行交易循环
    执行完一次后立即开始下一次，直到策略被禁用
    """
    logger.info(f"开始为策略 {user_strategy_id} 启动连续循环")
    
    # 设置运行标志
    running_flags[user_strategy_id] = True
    
    while running_flags.get(user_strategy_id, False):
        db = SessionLocal()
        loop_interval = 10  # 默认等待时间
        try:
            # 检查策略是否仍然启用
            user_strategy = db.query(UserStrategy).filter(
                UserStrategy.id == user_strategy_id
            ).first()
            
            if not user_strategy or not user_strategy.is_enabled:
                logger.info(f"策略 {user_strategy_id} 已禁用，停止循环")
                running_flags[user_strategy_id] = False
                break
            
            # 在数据库会话关闭前获取配置信息
            if user_strategy.config:
                loop_interval = user_strategy.config.get('loop_interval', 10)
            
            # 创建交易所服务
            exchange_service = ExchangeService(
                exchange_name=user_strategy.exchange,
                api_key=user_strategy.api_key,
                api_secret=user_strategy.api_secret
            )
            
            # 根据配置选择交易引擎
            use_bidirectional = False
            if user_strategy.config:
                use_bidirectional = user_strategy.config.get('bidirectional_trading', False)
            
            if use_bidirectional:
                # 使用双向交易引擎
                logger.info(f"策略 {user_strategy_id} 使用双向交易引擎")
                trading_engine = BidirectionalTradingEngine(
                    db=db,
                    user_strategy=user_strategy,
                    exchange_service=exchange_service,
                    strategy_engine=strategy_engine
                )
            else:
                # 使用原有交易引擎
                trading_engine = TradingEngine(
                    db=db,
                    user_strategy=user_strategy,
                    exchange_service=exchange_service,
                    strategy_engine=strategy_engine
                )
            
            # 执行一次交易循环
            try:
                trading_engine.run_trading_loop()
                logger.debug(f"策略 {user_strategy_id} 完成一次交易循环")
            except Exception as e:
                logger.error(f"策略 {user_strategy_id} 执行交易循环失败: {e}")
                # 发生错误时等待一段时间再继续，避免快速重试
                time.sleep(10)
            
        except Exception as e:
            logger.error(f"策略 {user_strategy_id} 处理失败: {e}")
            time.sleep(10)  # 发生错误时等待再继续
        finally:
            db.close()
        
        # 循环完成后等待一段时间再开始下一次，避免无限快速循环
        # 可以根据需要调整等待时间（秒），建议至少5-10秒
        time.sleep(loop_interval)
    
    # 清理资源
    if user_strategy_id in running_threads:
        del running_threads[user_strategy_id]
    if user_strategy_id in running_flags:
        del running_flags[user_strategy_id]
    if user_strategy_id in thread_locks:
        del thread_locks[user_strategy_id]
    
    logger.info(f"策略 {user_strategy_id} 的循环已停止")


def start_strategy(user_strategy_id: int):
    """
    启动指定策略的连续循环
    
    Args:
        user_strategy_id: 用户策略ID
    """
    # 检查是否已经在运行
    if user_strategy_id in running_threads:
        thread = running_threads[user_strategy_id]
        if thread.is_alive():
            logger.warning(f"策略 {user_strategy_id} 已在运行中")
            return False
    
    # 创建历史记录
    db = SessionLocal()
    try:
        # 检查是否有正在运行的记录
        running_history = db.query(StrategyHistory).filter(
            StrategyHistory.user_strategy_id == user_strategy_id,
            StrategyHistory.is_running == True
        ).first()
        
        if not running_history:
            # 创建新的历史记录
            history = StrategyHistory(
                user_strategy_id=user_strategy_id,
                started_at=datetime.now(),
                is_running=True
            )
            db.add(history)
            db.commit()
            logger.info(f"创建策略 {user_strategy_id} 的历史记录")
    except Exception as e:
        logger.error(f"创建策略历史记录失败: {e}")
        db.rollback()
    finally:
        db.close()
    
    # 创建线程锁
    if user_strategy_id not in thread_locks:
        thread_locks[user_strategy_id] = threading.Lock()
    
    # 创建并启动线程
    thread = threading.Thread(
        target=run_trading_loop_continuous,
        args=(user_strategy_id,),
        name=f"TradingStrategy-{user_strategy_id}",
        daemon=True
    )
    
    running_threads[user_strategy_id] = thread
    thread.start()
    logger.info(f"策略 {user_strategy_id} 的连续循环已启动")
    return True


def stop_strategy(user_strategy_id: int):
    """
    停止指定策略的连续循环
    
    Args:
        user_strategy_id: 用户策略ID
    """
    if user_strategy_id not in running_flags:
        logger.warning(f"策略 {user_strategy_id} 未在运行")
        return False
    
    # 设置停止标志
    running_flags[user_strategy_id] = False
    
    # 等待线程结束（最多等待10秒）
    if user_strategy_id in running_threads:
        thread = running_threads[user_strategy_id]
        if thread.is_alive():
            thread.join(timeout=10)
            if thread.is_alive():
                logger.warning(f"策略 {user_strategy_id} 的线程未能及时停止")
    
    # 更新历史记录
    db = SessionLocal()
    try:
        history = db.query(StrategyHistory).filter(
            StrategyHistory.user_strategy_id == user_strategy_id,
            StrategyHistory.is_running == True
        ).first()
        
        if history:
            # 计算该期间的已实现盈亏
            total_pnl = db.query(func.sum(PnLRecord.realized_pnl)).filter(
                PnLRecord.user_strategy_id == user_strategy_id,
                PnLRecord.closed_at >= history.started_at
            ).scalar() or 0.0
            
            # 获取用户ID
            user_strategy = db.query(UserStrategy).filter(
                UserStrategy.id == user_strategy_id
            ).first()
            
            if user_strategy:
                # 计算交易次数
                total_trades = db.query(func.count(Order.id)).filter(
                    Order.user_id == user_strategy.user_id,
                    Order.created_at >= history.started_at
                ).scalar() or 0
            else:
                total_trades = 0
            
            # 计算持仓数
            total_positions = db.query(func.count(Position.id)).filter(
                Position.user_strategy_id == user_strategy_id,
                Position.opened_at >= history.started_at
            ).scalar() or 0
            
            history.stopped_at = datetime.now()
            history.total_realized_pnl = total_pnl
            history.total_trades = total_trades
            history.total_positions = total_positions
            history.is_running = False
            db.commit()
            logger.info(f"更新策略 {user_strategy_id} 的历史记录: 盈利={total_pnl}, 交易={total_trades}, 持仓={total_positions}")
    except Exception as e:
        logger.error(f"更新策略历史记录失败: {e}")
        db.rollback()
    finally:
        db.close()
    
    logger.info(f"策略 {user_strategy_id} 的连续循环已停止")
    return True


def start_trading_scheduler():
    """
    启动交易调度器
    检查所有启用的策略并启动它们的连续循环
    系统重启后会自动恢复所有启用的策略
    """
    db = SessionLocal()
    try:
        # 获取所有启用的策略
        user_strategies = db.query(UserStrategy).filter(
            UserStrategy.is_enabled == True
        ).all()
        
        if not user_strategies:
            logger.info("没有发现启用的策略")
            return
        
        logger.info(f"发现 {len(user_strategies)} 个启用的策略，开始恢复连续循环...")
        
        success_count = 0
        fail_count = 0
        
        for user_strategy in user_strategies:
            try:
                # 检查策略是否已经在运行（防止重复启动）
                if user_strategy.id in running_threads:
                    thread = running_threads[user_strategy.id]
                    if thread.is_alive():
                        logger.debug(f"策略 {user_strategy.id} 已在运行中，跳过")
                        continue
                
                # 启动策略
                if start_strategy(user_strategy.id):
                    success_count += 1
                    logger.info(f"策略 {user_strategy.id} ({user_strategy.exchange}) 恢复成功")
                else:
                    fail_count += 1
                    logger.warning(f"策略 {user_strategy.id} 恢复失败")
            except Exception as e:
                fail_count += 1
                logger.error(f"启动策略 {user_strategy.id} 失败: {e}", exc_info=True)
        
        logger.info(f"交易调度器启动完成: 成功恢复 {success_count} 个策略，失败 {fail_count} 个策略")
    except Exception as e:
        logger.error(f"启动交易调度器失败: {e}", exc_info=True)
    finally:
        db.close()


def stop_trading_scheduler():
    """
    停止所有策略的连续循环
    """
    logger.info("正在停止所有策略的连续循环...")
    
    # 获取所有正在运行的策略ID
    strategy_ids = list(running_flags.keys())
    
    for strategy_id in strategy_ids:
        try:
            stop_strategy(strategy_id)
        except Exception as e:
            logger.error(f"停止策略 {strategy_id} 失败: {e}")
    
    logger.info("交易调度器已停止，所有策略循环已结束")


def restart_strategy(user_strategy_id: int):
    """
    重启指定策略的连续循环
    
    Args:
        user_strategy_id: 用户策略ID
    """
    stop_strategy(user_strategy_id)
    time.sleep(1)  # 等待线程完全停止
    start_strategy(user_strategy_id)


def get_running_strategies():
    """
    获取当前正在运行的策略ID列表
    
    Returns:
        List[int]: 正在运行的策略ID列表
    """
    return [
        strategy_id for strategy_id, flag in running_flags.items()
        if flag and strategy_id in running_threads and running_threads[strategy_id].is_alive()
    ]
