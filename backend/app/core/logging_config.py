"""
日志配置模块
支持控制台和文件输出，文件日志按日期轮转
"""
import logging
import os
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from app.core.config import settings


def setup_logging():
    """
    配置日志系统
    - 控制台输出：INFO级别及以上
    - 文件输出：INFO级别及以上，按日期轮转（每天一个文件）
    - 错误日志单独文件：ERROR级别及以上
    """
    # 创建logs目录
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)
    
    # 日志格式
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    date_format = '%Y-%m-%d %H:%M:%S'
    
    # 获取根日志记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # 清除已有的处理器（避免重复）
    root_logger.handlers.clear()
    
    # 1. 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter(log_format, date_format)
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)
    
    # 2. 所有日志文件处理器（按日期轮转，每天一个文件）
    all_log_file = logs_dir / "trading_system.log"
    file_handler = TimedRotatingFileHandler(
        filename=str(all_log_file),
        when='midnight',  # 每天午夜轮转
        interval=1,  # 每1天
        backupCount=30,  # 保留30天的日志
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    file_formatter = logging.Formatter(log_format, date_format)
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)
    
    # 3. 错误日志文件处理器（只记录ERROR和CRITICAL级别）
    error_log_file = logs_dir / "trading_system_error.log"
    error_handler = TimedRotatingFileHandler(
        filename=str(error_log_file),
        when='midnight',  # 每天午夜轮转
        interval=1,  # 每1天
        backupCount=90,  # 保留90天的错误日志（错误日志更重要，保留更久）
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)  # 只记录ERROR和CRITICAL
    error_formatter = logging.Formatter(log_format, date_format)
    error_handler.setFormatter(error_formatter)
    root_logger.addHandler(error_handler)
    
    # 4. 策略异常日志文件（专门记录策略异常终止的详细信息）
    strategy_error_log_file = logs_dir / "strategy_errors.log"
    strategy_error_handler = TimedRotatingFileHandler(
        filename=str(strategy_error_log_file),
        when='midnight',
        interval=1,
        backupCount=90,  # 保留90天
        encoding='utf-8'
    )
    strategy_error_handler.setLevel(logging.ERROR)
    strategy_error_formatter = logging.Formatter(log_format, date_format)
    strategy_error_handler.setFormatter(strategy_error_formatter)
    
    # 为策略相关的logger添加专门的错误处理器
    strategy_loggers = [
        'app.services.trading_scheduler',
        'app.services.trading_engine',
        'app.services.trading_engine_bidirectional',
        'app.services.exchange_service',
        'app.strategies'
    ]
    for logger_name in strategy_loggers:
        strategy_logger = logging.getLogger(logger_name)
        strategy_logger.addHandler(strategy_error_handler)
        strategy_logger.setLevel(logging.INFO)
    
    logger = logging.getLogger(__name__)
    logger.info(f"日志系统已配置完成")
    logger.info(f"日志文件目录: {logs_dir.absolute()}")
    logger.info(f"所有日志: {all_log_file}")
    logger.info(f"错误日志: {error_log_file}")
    logger.info(f"策略异常日志: {strategy_error_log_file}")


