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
from app.core.database import SessionLocal, get_db_context
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
monitor_thread: Optional[threading.Thread] = None  # 监控线程
monitor_running: bool = False  # 监控线程运行标志


def run_trading_loop_continuous(user_strategy_id: int):
    """
    为特定用户策略持续运行交易循环
    执行完一次后立即开始下一次，直到策略被禁用
    """
    logger.info(f"开始为策略 {user_strategy_id} 启动连续循环")
    
    # 设置运行标志
    running_flags[user_strategy_id] = True
    
    loop_count = 0  # 循环计数器，用于日志记录
    
    try:
        while running_flags.get(user_strategy_id, False):
            loop_count += 1
            loop_interval = 10  # 默认等待时间
            exchange_name = None
            api_key = None
            api_secret = None
            use_bidirectional = False
            exchange_service = None
            
            # 使用上下文管理器确保数据库会话正确关闭
            # 添加重试机制，防止数据库连接问题导致误判
            user_strategy = None
            retry_count = 0
            max_retries = 3
            
            while retry_count < max_retries:
                try:
                    with get_db_context() as db:
                        # 检查策略是否仍然启用
                        # 使用 refresh 确保读取到最新数据，避免缓存问题
                        user_strategy = db.query(UserStrategy).filter(
                            UserStrategy.id == user_strategy_id
                        ).first()
                        
                        if user_strategy:
                            break  # 查询成功，退出重试循环
                        else:
                            retry_count += 1
                            if retry_count < max_retries:
                                logger.warning(
                                    f"策略 {user_strategy_id} 查询返回 None (尝试 {retry_count}/{max_retries})，"
                                    f"可能是数据库连接问题，等待后重试..."
                                )
                                time.sleep(2)  # 等待2秒后重试
                            else:
                                # 重试次数用完，记录详细日志并停止
                                logger.error(
                                    f"策略 {user_strategy_id} 在 {max_retries} 次重试后仍然查询不到，"
                                    f"停止循环。可能原因：策略已被删除、数据库连接问题、或数据库锁定"
                                )
                                # 最后一次尝试：直接查询数据库确认
                                try:
                                    with get_db_context() as db:
                                        count = db.query(UserStrategy).filter(
                                            UserStrategy.id == user_strategy_id
                                        ).count()
                                        logger.error(
                                            f"策略 {user_strategy_id} 最终确认：数据库中存在 {count} 条记录"
                                        )
                                except Exception as e:
                                    logger.error(f"最终确认查询失败: {e}")
                                
                                running_flags[user_strategy_id] = False
                                break
                except Exception as e:
                    retry_count += 1
                    exception_type = type(e).__name__
                    exception_message = str(e)
                    logger.warning(
                        f"策略 {user_strategy_id} 数据库查询异常 (尝试 {retry_count}/{max_retries}) - "
                        f"异常类型: {exception_type}, "
                        f"异常消息: {exception_message}"
                    )
                    if retry_count < max_retries:
                        time.sleep(2)  # 等待后重试
                    else:
                        logger.error(
                            f"策略 {user_strategy_id} 数据库查询在 {max_retries} 次重试后仍然失败，"
                            f"跳过本次循环，等待下次循环"
                        )
                        time.sleep(10)
                        continue  # 跳过本次循环，继续下一次
            
            # 如果查询失败，跳过本次循环
            if not user_strategy:
                continue
                    
            # 在查询成功后，再次打开会话进行后续操作
            try:
                with get_db_context() as db:
                    # 重新查询以确保对象有效（因为之前的会话已关闭）
                    user_strategy = db.query(UserStrategy).filter(
                        UserStrategy.id == user_strategy_id
                    ).first()
                    
                    if not user_strategy:
                        logger.warning(f"策略 {user_strategy_id} 在后续查询中不存在，跳过本次循环")
                        time.sleep(10)
                        continue
                    
                    # 刷新对象以确保读取到最新状态（避免缓存问题）
                    try:
                        db.refresh(user_strategy)
                    except Exception as e:
                        logger.warning(f"刷新策略 {user_strategy_id} 状态失败: {e}，使用当前查询结果")
                    
                    # 记录当前状态用于调试
                    current_enabled = user_strategy.is_enabled
                    logger.debug(f"策略 {user_strategy_id} 当前状态检查: is_enabled={current_enabled}, exchange={user_strategy.exchange}")
                    
                    if not current_enabled:
                        logger.warning(f"策略 {user_strategy_id} 的 is_enabled 状态为 False，停止循环。当前数据库状态: id={user_strategy.id}, is_enabled={user_strategy.is_enabled}, exchange={user_strategy.exchange}, user_id={user_strategy.user_id}")
                        running_flags[user_strategy_id] = False
                        break
                    
                    # 在会话关闭前提取所有需要的数据
                    exchange_name = user_strategy.exchange
                    api_key = user_strategy.api_key
                    api_secret = user_strategy.api_secret
                    
                    # 获取配置信息（在会话内访问）
                    if user_strategy.config:
                        loop_interval = user_strategy.config.get('loop_interval', 10)
                        use_bidirectional = user_strategy.config.get('bidirectional_trading', False)
            except Exception as e:
                # 详细记录数据库会话异常
                exception_type = type(e).__name__
                exception_message = str(e)
                logger.error(
                    f"策略 {user_strategy_id} 数据库会话异常终止 - "
                    f"循环次数: {loop_count}, "
                    f"异常类型: {exception_type}, "
                    f"异常消息: {exception_message}",
                    exc_info=True
                )
                time.sleep(10)
                continue
            
            # 在数据库会话外创建交易所服务
            try:
                logger.info(f"策略 {user_strategy_id} 第 {loop_count} 次循环开始，交易所: {exchange_name}")
                exchange_service = ExchangeService(
                    exchange_name=exchange_name,
                    api_key=api_key,
                    api_secret=api_secret
                )
                logger.debug(f"策略 {user_strategy_id} ExchangeService 初始化成功")
            except Exception as e:
                # 详细记录 ExchangeService 初始化异常
                exception_type = type(e).__name__
                exception_message = str(e)
                logger.error(
                    f"策略 {user_strategy_id} ExchangeService 初始化异常终止 - "
                    f"循环次数: {loop_count}, "
                    f"异常类型: {exception_type}, "
                    f"异常消息: {exception_message}, "
                    f"交易所: {exchange_name}, "
                    f"API密钥: {'已配置' if api_key else '未配置'}",
                    exc_info=True
                )
                # ExchangeService 初始化失败，等待后继续下一次循环
                time.sleep(30)  # 初始化失败时等待更长时间
                continue  # 跳过本次循环，继续下一次
            
            # 执行交易循环（在独立的数据库会话中）
            # 添加重试机制，处理SQLite多线程并发问题
            user_strategy = None
            query_retry_count = 0
            max_query_retries = 3
            
            while query_retry_count < max_query_retries and not user_strategy:
                try:
                    with get_db_context() as db:
                        # 重新查询用户策略（因为之前的会话已关闭）
                        try:
                            user_strategy = db.query(UserStrategy).filter(
                                UserStrategy.id == user_strategy_id
                            ).first()
                        except Exception as query_error:
                            error_str = str(query_error).lower()
                            if "locked" in error_str or "database is locked" in error_str:
                                query_retry_count += 1
                                if query_retry_count < max_query_retries:
                                    logger.warning(
                                        f"策略 {user_strategy_id} 查询时数据库锁定 (尝试 {query_retry_count}/{max_query_retries})，"
                                        f"等待后重试..."
                                    )
                                    time.sleep(0.5 * query_retry_count)  # 递增等待时间
                                    continue
                                else:
                                    logger.error(f"策略 {user_strategy_id} 查询在 {max_query_retries} 次重试后仍然失败")
                                    break
                            else:
                                raise  # 其他异常直接抛出
                        
                        if not user_strategy:
                            # 查询失败，可能是数据库锁定或策略不存在
                            query_retry_count += 1
                            if query_retry_count < max_query_retries:
                                logger.warning(
                                    f"策略 {user_strategy_id} 查询返回 None (尝试 {query_retry_count}/{max_query_retries})，"
                                    f"可能是数据库锁定，等待后重试..."
                                )
                                time.sleep(0.5 * query_retry_count)  # 递增等待时间
                                continue  # 继续重试
                            else:
                                # 重试次数用完，详细记录并确认
                                try:
                                    # 先检查数据库中是否真的没有这个策略
                                    all_strategies = db.query(UserStrategy).all()
                                    strategy_ids = [s.id for s in all_strategies]
                                    logger.error(
                                        f"策略 {user_strategy_id} 在 {max_query_retries} 次重试后仍然查询不到 - "
                                        f"循环次数: {loop_count}, "
                                        f"数据库中当前存在的策略ID: {strategy_ids}, "
                                        f"查询的ID {user_strategy_id} {'不在' if user_strategy_id not in strategy_ids else '在'}列表中"
                                    )
                                    
                                    if user_strategy_id not in strategy_ids:
                                        # 策略确实不存在，停止循环
                                        logger.error(f"策略 {user_strategy_id} 确认已被删除，停止循环")
                                        running_flags[user_strategy_id] = False
                                        break
                                    else:
                                        # 策略存在但查询失败，可能是数据库锁定，跳过本次循环
                                        logger.warning(f"策略 {user_strategy_id} 存在但查询失败，跳过本次循环，等待下次")
                                        time.sleep(10)
                                        continue  # 跳过本次循环，继续下一次
                                except Exception as confirm_error:
                                    logger.error(
                                        f"确认策略 {user_strategy_id} 状态失败: {confirm_error}, "
                                        f"异常类型: {type(confirm_error).__name__}",
                                        exc_info=True
                                    )
                                    # 无法确认，跳过本次循环
                                    time.sleep(10)
                                    continue
                        
                        # 如果查询成功，继续执行交易循环
                        if user_strategy:
                            # 刷新对象以确保读取到最新状态
                            try:
                                db.refresh(user_strategy)
                            except Exception as e:
                                logger.warning(f"刷新策略 {user_strategy_id} 状态失败: {e}，使用当前查询结果")
                            
                            # 记录当前状态用于调试
                            current_enabled = user_strategy.is_enabled
                            logger.debug(f"策略 {user_strategy_id} 在执行交易循环时状态检查: is_enabled={current_enabled}")
                            
                            if not current_enabled:
                                logger.warning(f"策略 {user_strategy_id} 在执行交易循环时 is_enabled 状态为 False，停止循环。当前数据库状态: id={user_strategy.id}, is_enabled={user_strategy.is_enabled}, exchange={user_strategy.exchange}, user_id={user_strategy.user_id}")
                                running_flags[user_strategy_id] = False
                                break
                            
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
                            trading_engine.run_trading_loop()
                            logger.info(f"策略 {user_strategy_id} 第 {loop_count} 次循环完成")
                            break  # 成功执行后退出重试循环
                except Exception as loop_error:
                    query_retry_count += 1
                    error_str = str(loop_error).lower()
                    if "locked" in error_str or "database is locked" in error_str:
                        if query_retry_count < max_query_retries:
                            logger.warning(
                                f"策略 {user_strategy_id} 执行交易循环时数据库锁定 (尝试 {query_retry_count}/{max_query_retries})，"
                                f"等待后重试..."
                            )
                            time.sleep(0.5 * query_retry_count)
                            continue
                        else:
                            logger.error(f"策略 {user_strategy_id} 在 {max_query_retries} 次重试后仍然失败")
                            time.sleep(10)
                            continue  # 跳过本次循环
                    else:
                        # 其他异常，记录并跳过本次循环
                        logger.error(
                            f"策略 {user_strategy_id} 执行交易循环异常: {loop_error}, "
                            f"异常类型: {type(loop_error).__name__}",
                            exc_info=True
                        )
                        time.sleep(10)
                        continue  # 跳过本次循环
            
            # 如果查询失败（重试后仍然失败），跳过本次循环
            if not user_strategy:
                logger.warning(f"策略 {user_strategy_id} 查询失败，跳过本次循环")
                time.sleep(10)
                continue
            
            # 循环完成后等待一段时间再开始下一次，避免无限快速循环
            # 可以根据需要调整等待时间（秒），建议至少5-10秒
            time.sleep(loop_interval)
        
        # 记录策略循环停止信息（包括是否异常终止）
        final_loop_count = loop_count
        logger.info(
            f"策略 {user_strategy_id} 的循环已停止 - "
            f"总循环次数: {final_loop_count}, "
            f"停止原因: {'正常停止' if not running_flags.get(user_strategy_id, False) else '异常终止'}"
        )
    except Exception as e:
        # 捕获最外层未预期的异常，确保策略异常终止时能记录详细信息
        exception_type = type(e).__name__
        exception_message = str(e)
        logger.critical(
            f"策略 {user_strategy_id} 发生严重异常导致循环终止 - "
            f"循环次数: {loop_count}, "
            f"异常类型: {exception_type}, "
            f"异常消息: {exception_message}, "
            f"运行标志: {running_flags.get(user_strategy_id, False)}, "
            f"此异常可能导致策略完全停止运行",
            exc_info=True
        )
        # 确保运行标志被清除，防止资源泄漏
        running_flags[user_strategy_id] = False
    finally:
        # 最终清理资源，确保即使发生异常也能清理
        if user_strategy_id in running_threads:
            del running_threads[user_strategy_id]
        if user_strategy_id in running_flags:
            del running_flags[user_strategy_id]
        if user_strategy_id in thread_locks:
            del thread_locks[user_strategy_id]


def start_strategy(user_strategy_id: int):
    """
    启动指定策略的连续循环
    
    Args:
        user_strategy_id: 用户策略ID
    """
    # 创建线程锁（如果不存在）
    if user_strategy_id not in thread_locks:
        thread_locks[user_strategy_id] = threading.Lock()
    
    # 使用线程锁保护，防止重复启动
    with thread_locks[user_strategy_id]:
        # 检查是否已经在运行（双重检查）
        if user_strategy_id in running_threads:
            thread = running_threads[user_strategy_id]
            if thread.is_alive():
                logger.warning(f"策略 {user_strategy_id} 已在运行中")
                return False
        
        # 创建历史记录
        try:
            with get_db_context() as db:
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
                    # 上下文管理器会自动提交
                    logger.info(f"创建策略 {user_strategy_id} 的历史记录")
        except Exception as e:
            logger.error(f"创建策略历史记录失败: {e}", exc_info=True)
        
        # 创建并启动线程（在锁保护下，确保原子性）
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
    try:
        with get_db_context() as db:
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
                # 上下文管理器会自动提交
                logger.info(f"更新策略 {user_strategy_id} 的历史记录: 盈利={total_pnl}, 交易={total_trades}, 持仓={total_positions}")
    except Exception as e:
        logger.error(f"更新策略历史记录失败: {e}", exc_info=True)
    
    logger.info(f"策略 {user_strategy_id} 的连续循环已停止")
    return True


def start_trading_scheduler():
    """
    启动交易调度器
    检查所有启用的策略并启动它们的连续循环
    系统重启后会自动恢复所有启用的策略
    """
    try:
        with get_db_context() as db:
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


def check_and_restart_dead_threads():
    """
    检查并自动重启死亡的线程
    这个函数应该定期调用（例如每分钟）来监控线程健康状态
    """
    dead_threads = []
    
    # 检查所有标记为运行的策略
    for user_strategy_id, flag in list(running_flags.items()):
        if not flag:
            continue  # 已停止的策略，跳过
        
        # 检查线程是否存在且存活
        if user_strategy_id not in running_threads:
            # 详细记录线程丢失信息
            logger.warning(
                f"策略 {user_strategy_id} 的线程不存在（异常终止） - "
                f"运行标志: {flag}, "
                f"线程字典中无记录, "
                f"尝试自动重启"
            )
            dead_threads.append(user_strategy_id)
        else:
            thread = running_threads[user_strategy_id]
            if not thread.is_alive():
                # 详细记录线程死亡信息
                logger.warning(
                    f"策略 {user_strategy_id} 的线程已死亡（异常终止） - "
                    f"运行标志: {flag}, "
                    f"线程名称: {thread.name}, "
                    f"线程ID: {thread.ident}, "
                    f"尝试自动重启"
                )
                dead_threads.append(user_strategy_id)
    
    # 重启死亡的线程
    for user_strategy_id in dead_threads:
        try:
            # 清理旧的线程引用
            if user_strategy_id in running_threads:
                del running_threads[user_strategy_id]
            
            # 检查策略是否仍然启用
            with get_db_context() as db:
                user_strategy = db.query(UserStrategy).filter(
                    UserStrategy.id == user_strategy_id
                ).first()
                
                if user_strategy and user_strategy.is_enabled:
                    logger.info(f"自动重启策略 {user_strategy_id} 的线程")
                    start_strategy(user_strategy_id)
                else:
                    # 策略已禁用，清理运行标志
                    if user_strategy_id in running_flags:
                        running_flags[user_strategy_id] = False
                    logger.info(f"策略 {user_strategy_id} 已禁用，清理运行标志")
        except Exception as e:
            # 详细记录重启策略异常信息
            exception_type = type(e).__name__
            exception_message = str(e)
            logger.error(
                f"重启策略异常终止 - "
                f"策略ID: {user_strategy_id}, "
                f"异常类型: {exception_type}, "
                f"异常消息: {exception_message}, "
                f"原因: 线程死亡后尝试重启失败",
                exc_info=True
            )
    
    return len(dead_threads)


def _monitor_threads_loop():
    """
    监控线程循环，定期检查线程健康状态
    """
    global monitor_running
    monitor_running = True
    logger.info("线程监控器已启动")
    
    while monitor_running:
        try:
            # 每分钟检查一次
            time.sleep(60)
            
            if not monitor_running:
                break
            
            # 检查并重启死亡的线程
            dead_count = check_and_restart_dead_threads()
            if dead_count > 0:
                logger.info(f"线程监控器检测到 {dead_count} 个死亡线程，已尝试重启")
        except Exception as e:
            logger.error(f"线程监控器运行失败: {e}", exc_info=True)
            time.sleep(60)  # 出错后等待再继续
    
    logger.info("线程监控器已停止")


def start_thread_monitor():
    """
    启动线程监控器
    """
    global monitor_thread, monitor_running
    
    if monitor_thread is not None and monitor_thread.is_alive():
        logger.warning("线程监控器已在运行")
        return
    
    monitor_thread = threading.Thread(
        target=_monitor_threads_loop,
        name="ThreadMonitor",
        daemon=True
    )
    monitor_thread.start()
    logger.info("线程监控器已启动")


def stop_thread_monitor():
    """
    停止线程监控器
    """
    global monitor_running, monitor_thread
    
    monitor_running = False
    
    if monitor_thread is not None and monitor_thread.is_alive():
        monitor_thread.join(timeout=5)
        logger.info("线程监控器已停止")
