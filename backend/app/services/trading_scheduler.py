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

# 使用配置常量
THREAD_STOP_TIMEOUT = settings.THREAD_STOP_TIMEOUT
THREAD_MONITOR_INTERVAL = settings.THREAD_MONITOR_INTERVAL

logger = logging.getLogger(__name__)

strategy_engine = StrategyEngine(settings.STRATEGIES_DIR)

# 存储每个策略的运行状态和线程
running_threads: Dict[int, threading.Thread] = {}
running_flags: Dict[int, bool] = {}  # 控制循环是否继续
thread_locks: Dict[int, threading.Lock] = {}  # 线程锁
monitor_thread: Optional[threading.Thread] = None  # 监控线程
monitor_running: bool = False  # 监控线程运行标志

# ExchangeService 实例缓存: {strategy_id: (exchange_service, config_hash)}
_exchange_service_cache: Dict[int, tuple] = {}
_exchange_cache_lock = threading.Lock()


def _get_config_hash(config: dict) -> str:
    """生成配置的哈希值，用于检测配置是否变更"""
    return f"{config['exchange_name']}_{config['api_key']}_{config['api_secret']}"


def _get_or_create_exchange_service(
    config: dict,
    user_strategy_id: int
) -> Optional[ExchangeService]:
    """
    获取或创建 ExchangeService 实例（带缓存）

    只有当配置变更时才重新创建实例
    """
    config_hash = _get_config_hash(config)

    with _exchange_cache_lock:
        # 检查缓存中是否有该策略的 ExchangeService
        if user_strategy_id in _exchange_service_cache:
            cached_service, cached_hash = _exchange_service_cache[user_strategy_id]
            # 配置未变更，复用现有实例
            if cached_hash == config_hash:
                logger.debug(f"策略 {user_strategy_id} 复用缓存的 ExchangeService")
                return cached_service
            else:
                # 配置已变更，需要重新创建
                logger.info(f"策略 {user_strategy_id} 配置已变更，重新创建 ExchangeService")

        # 创建新的 ExchangeService 实例
        try:
            exchange_service = ExchangeService(
                exchange_name=config['exchange_name'],
                api_key=config['api_key'],
                api_secret=config['api_secret']
            )
            # 缓存新实例
            _exchange_service_cache[user_strategy_id] = (exchange_service, config_hash)
            logger.debug(f"策略 {user_strategy_id} ExchangeService 初始化并缓存成功")
            return exchange_service
        except Exception as e:
            logger.error(
                f"策略 {user_strategy_id} ExchangeService 初始化异常: {e}",
                exc_info=True
            )
            return None


def _clear_exchange_service_cache(user_strategy_id: int = None):
    """
    清理 ExchangeService 缓存

    Args:
        user_strategy_id: 策略ID，如果为None则清理所有缓存
    """
    with _exchange_cache_lock:
        if user_strategy_id is not None:
            if user_strategy_id in _exchange_service_cache:
                del _exchange_service_cache[user_strategy_id]
                logger.debug(f"已清理策略 {user_strategy_id} 的 ExchangeService 缓存")
        else:
            _exchange_service_cache.clear()
            logger.debug("已清理所有 ExchangeService 缓存")


def _query_strategy_with_retry(user_strategy_id: int, max_retries: int = 3) -> Optional[UserStrategy]:
    """
    带重试机制的策略查询

    Args:
        user_strategy_id: 策略ID
        max_retries: 最大重试次数

    Returns:
        UserStrategy 对象，如果查询失败返回 None
    """
    for retry_count in range(1, max_retries + 1):
        try:
            with get_db_context() as db:
                user_strategy = db.query(UserStrategy).filter(
                    UserStrategy.id == user_strategy_id
                ).first()

                if user_strategy:
                    return user_strategy

                if retry_count < max_retries:
                    logger.warning(
                        f"策略 {user_strategy_id} 查询返回 None (尝试 {retry_count}/{max_retries})，"
                        f"可能是数据库连接问题，等待后重试..."
                    )
                    time.sleep(2)
                else:
                    logger.error(
                        f"策略 {user_strategy_id} 在 {max_retries} 次重试后仍然查询不到"
                    )
        except Exception as e:
            logger.warning(
                f"策略 {user_strategy_id} 数据库查询异常 (尝试 {retry_count}/{max_retries}) - "
                f"异常类型: {type(e).__name__}, 异常消息: {str(e)}"
            )
            if retry_count < max_retries:
                time.sleep(2)
    return None


def _extract_strategy_config(user_strategy_id: int) -> Optional[dict]:
    """
    提取策略配置信息

    Returns:
        包含 exchange_name, api_key, api_secret, loop_interval, use_bidirectional 的字典
    """
    try:
        with get_db_context() as db:
            user_strategy = db.query(UserStrategy).filter(
                UserStrategy.id == user_strategy_id
            ).first()

            if not user_strategy:
                return None

            try:
                db.refresh(user_strategy)
            except Exception:
                pass

            if not user_strategy.is_enabled:
                logger.warning(f"策略 {user_strategy_id} 的 is_enabled 状态为 False")
                return None

            config = {
                'exchange_name': user_strategy.exchange,
                'api_key': user_strategy.api_key,
                'api_secret': user_strategy.api_secret,
                'loop_interval': settings.DEFAULT_LOOP_INTERVAL,
                'use_bidirectional': False
            }

            if user_strategy.config:
                config['loop_interval'] = user_strategy.config.get('loop_interval', settings.DEFAULT_LOOP_INTERVAL)
                config['use_bidirectional'] = user_strategy.config.get('bidirectional_trading', False)

            return config
    except Exception as e:
        logger.error(f"策略 {user_strategy_id} 提取配置异常: {e}", exc_info=True)
        return None


def _execute_trading_loop(
    user_strategy_id: int,
    exchange_service: ExchangeService,
    use_bidirectional: bool,
    loop_count: int
) -> bool:
    """
    执行一次交易循环

    Returns:
        True 表示成功，False 表示失败
    """
    max_retries = 3

    for retry_count in range(1, max_retries + 1):
        try:
            with get_db_context() as db:
                user_strategy = db.query(UserStrategy).filter(
                    UserStrategy.id == user_strategy_id
                ).first()

                if not user_strategy:
                    if retry_count < max_retries:
                        time.sleep(0.5 * retry_count)
                        continue
                    return False

                try:
                    db.refresh(user_strategy)
                except Exception:
                    pass

                if not user_strategy.is_enabled:
                    logger.warning(f"策略 {user_strategy_id} 已禁用，停止循环")
                    running_flags[user_strategy_id] = False
                    return False

                # 创建交易引擎并执行
                if use_bidirectional:
                    trading_engine = BidirectionalTradingEngine(
                        db=db,
                        user_strategy=user_strategy,
                        exchange_service=exchange_service,
                        strategy_engine=strategy_engine
                    )
                else:
                    trading_engine = TradingEngine(
                        db=db,
                        user_strategy=user_strategy,
                        exchange_service=exchange_service,
                        strategy_engine=strategy_engine
                    )

                trading_engine.run_trading_loop()
                # logger.info(f"策略 {user_strategy_id} 第 {loop_count} 次循环完成")
                return True

        except Exception as e:
            error_str = str(e).lower()
            if "locked" in error_str or "database is locked" in error_str:
                if retry_count < max_retries:
                    logger.warning(f"策略 {user_strategy_id} 数据库锁定，重试 {retry_count}/{max_retries}")
                    time.sleep(0.5 * retry_count)
                    continue
            logger.error(f"策略 {user_strategy_id} 执行交易循环异常: {e}", exc_info=True)
            return False

    return False


def run_trading_loop_continuous(user_strategy_id: int):
    """
    为特定用户策略持续运行交易循环
    执行完一次后立即开始下一次，直到策略被禁用
    """
    logger.info(f"开始为策略 {user_strategy_id} 启动连续循环")
    running_flags[user_strategy_id] = True
    loop_count = 0

    try:
        while running_flags.get(user_strategy_id, False):
            loop_count += 1

            # 1. 查询策略是否存在
            user_strategy = _query_strategy_with_retry(user_strategy_id)
            if not user_strategy:
                running_flags[user_strategy_id] = False
                break

            # 2. 提取策略配置
            config = _extract_strategy_config(user_strategy_id)
            if not config:
                running_flags[user_strategy_id] = False
                break

            # 3. 获取或创建交易所服务（使用缓存）
            exchange_service = _get_or_create_exchange_service(config, user_strategy_id)
            if not exchange_service:
                time.sleep(30)
                continue

            # 4. 执行交易循环
            success = _execute_trading_loop(
                user_strategy_id,
                exchange_service,
                config['use_bidirectional'],
                loop_count
            )

            if not success and not running_flags.get(user_strategy_id, False):
                break

            # 5. 等待下一次循环
            time.sleep(config['loop_interval'])

        logger.info(
            f"策略 {user_strategy_id} 的循环已停止 - "
            f"总循环次数: {loop_count}, 停止原因: 正常停止"
        )
    except Exception as e:
        logger.critical(
            f"策略 {user_strategy_id} 发生严重异常导致循环终止 - "
            f"循环次数: {loop_count}, 异常: {e}",
            exc_info=True
        )
        running_flags[user_strategy_id] = False
    finally:
        # 清理资源
        running_threads.pop(user_strategy_id, None)
        running_flags.pop(user_strategy_id, None)
        thread_locks.pop(user_strategy_id, None)
        # 清理 ExchangeService 缓存
        _clear_exchange_service_cache(user_strategy_id)


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
    
    # 等待线程结束
    if user_strategy_id in running_threads:
        thread = running_threads[user_strategy_id]
        if thread.is_alive():
            thread.join(timeout=THREAD_STOP_TIMEOUT)
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
        # 先从数据库获取策略信息，提取所需字段后再关闭会话
        strategies_to_start = []
        with get_db_context() as db:
            # 获取所有启用的策略
            user_strategies = db.query(UserStrategy).filter(
                UserStrategy.is_enabled == True
            ).all()

            if not user_strategies:
                logger.info("没有发现启用的策略")
                return

            logger.info(f"发现 {len(user_strategies)} 个启用的策略，开始恢复连续循环...")

            # 在会话关闭前提取所需的属性值
            for user_strategy in user_strategies:
                strategies_to_start.append({
                    'id': user_strategy.id,
                    'exchange': user_strategy.exchange
                })

        # 在会话关闭后启动策略
        success_count = 0
        fail_count = 0

        for strategy_info in strategies_to_start:
            strategy_id = strategy_info['id']
            exchange = strategy_info['exchange']
            try:
                # 检查策略是否已经在运行（防止重复启动）
                if strategy_id in running_threads:
                    thread = running_threads[strategy_id]
                    if thread.is_alive():
                        logger.debug(f"策略 {strategy_id} 已在运行中，跳过")
                        continue

                # 启动策略
                if start_strategy(strategy_id):
                    success_count += 1
                    logger.info(f"策略 {strategy_id} ({exchange}) 恢复成功")
                else:
                    fail_count += 1
                    logger.warning(f"策略 {strategy_id} 恢复失败")
            except Exception as e:
                fail_count += 1
                logger.error(f"启动策略 {strategy_id} 失败: {e}", exc_info=True)

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
            # 定期检查
            time.sleep(THREAD_MONITOR_INTERVAL)
            
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
