"""
全局共享的OHLCV数据缓存服务
支持多策略共享相同交易对的K线数据，减少内存占用和API调用
"""
import threading
import logging
from typing import Dict, Optional, Any
from datetime import datetime, timedelta
import pandas as pd

logger = logging.getLogger(__name__)


class OHLCVCache:
    """
    全局OHLCV缓存服务（线程安全）
    缓存格式: {cache_key: {'dataframe': DataFrame, 'timestamp': datetime}}
    cache_key格式: {exchange_name}:{symbol}:{timeframe}
    """
    
    def __init__(self, default_ttl_seconds: int = 300):
        """
        初始化缓存
        
        Args:
            default_ttl_seconds: 默认缓存有效期（秒），默认5分钟
        """
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()  # 使用可重入锁，支持嵌套调用
        self.default_ttl = default_ttl_seconds
        logger.info(f"OHLCV缓存服务已初始化，默认TTL: {default_ttl_seconds}秒")
    
    def _make_cache_key(self, exchange_name: str, symbol: str, timeframe: str) -> str:
        """
        生成缓存键
        
        Args:
            exchange_name: 交易所名称
            symbol: 交易对
            timeframe: 时间周期
            
        Returns:
            缓存键字符串
        """
        return f"{exchange_name}:{symbol}:{timeframe}"
    
    def get(self, exchange_name: str, symbol: str, timeframe: str, 
            ttl_seconds: Optional[int] = None) -> Optional[pd.DataFrame]:
        """
        获取缓存的OHLCV数据
        
        Args:
            exchange_name: 交易所名称
            symbol: 交易对
            timeframe: 时间周期
            ttl_seconds: 缓存有效期（秒），如果为None则使用默认值
            
        Returns:
            DataFrame或None（如果缓存不存在或已过期）
        """
        cache_key = self._make_cache_key(exchange_name, symbol, timeframe)
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl
        
        with self._lock:
            if cache_key not in self._cache:
                return None
            
            cached_data = self._cache[cache_key]
            timestamp = cached_data.get('timestamp')
            
            if not timestamp:
                # 如果没有时间戳，认为缓存无效
                del self._cache[cache_key]
                return None
            
            # 检查是否过期
            age_seconds = (datetime.now() - timestamp).total_seconds()
            if age_seconds >= ttl:
                # 缓存已过期，删除
                del self._cache[cache_key]
                logger.debug(f"OHLCV缓存已过期: {cache_key}, 年龄: {age_seconds:.1f}秒")
                return None
            
            # 返回DataFrame的副本，避免外部修改影响缓存
            dataframe = cached_data.get('dataframe')
            if dataframe is not None:
                return dataframe.copy()
            return None
    
    def set(self, exchange_name: str, symbol: str, timeframe: str, 
            dataframe: pd.DataFrame, ttl_seconds: Optional[int] = None):
        """
        设置缓存的OHLCV数据
        
        Args:
            exchange_name: 交易所名称
            symbol: 交易对
            timeframe: 时间周期
            dataframe: 要缓存的DataFrame
            ttl_seconds: 缓存有效期（秒），如果为None则使用默认值
        """
        if dataframe is None or dataframe.empty:
            logger.warning(f"尝试缓存空的DataFrame: {exchange_name}:{symbol}:{timeframe}")
            return
        
        cache_key = self._make_cache_key(exchange_name, symbol, timeframe)
        
        with self._lock:
            # 存储DataFrame的副本，避免外部修改影响缓存
            self._cache[cache_key] = {
                'dataframe': dataframe.copy(),
                'timestamp': datetime.now()
            }
            logger.debug(f"OHLCV数据已缓存: {cache_key}, 行数: {len(dataframe)}")
    
    def delete(self, exchange_name: str, symbol: str, timeframe: Optional[str] = None):
        """
        删除缓存的OHLCV数据
        
        Args:
            exchange_name: 交易所名称
            symbol: 交易对
            timeframe: 时间周期，如果为None则删除该交易对的所有时间周期缓存
        """
        with self._lock:
            if timeframe:
                # 删除特定时间周期的缓存
                cache_key = self._make_cache_key(exchange_name, symbol, timeframe)
                if cache_key in self._cache:
                    del self._cache[cache_key]
                    logger.debug(f"已删除OHLCV缓存: {cache_key}")
            else:
                # 删除该交易对的所有时间周期缓存
                prefix = f"{exchange_name}:{symbol}:"
                keys_to_delete = [key for key in self._cache.keys() if key.startswith(prefix)]
                for key in keys_to_delete:
                    del self._cache[key]
                if keys_to_delete:
                    logger.debug(f"已删除 {len(keys_to_delete)} 个OHLCV缓存项: {prefix}*")
    
    def clear(self):
        """清空所有缓存"""
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            logger.info(f"已清空所有OHLCV缓存，共 {count} 项")
    
    def cleanup_expired(self, ttl_seconds: Optional[int] = None):
        """
        清理过期的缓存项
        
        Args:
            ttl_seconds: 缓存有效期（秒），如果为None则使用默认值
        """
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl
        now = datetime.now()
        
        with self._lock:
            keys_to_delete = []
            for cache_key, cached_data in self._cache.items():
                timestamp = cached_data.get('timestamp')
                if timestamp:
                    age_seconds = (now - timestamp).total_seconds()
                    if age_seconds >= ttl:
                        keys_to_delete.append(cache_key)
            
            for key in keys_to_delete:
                del self._cache[key]
            
            if keys_to_delete:
                logger.debug(f"清理了 {len(keys_to_delete)} 个过期的OHLCV缓存项")
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取缓存统计信息
        
        Returns:
            包含缓存统计信息的字典
        """
        with self._lock:
            total_items = len(self._cache)
            total_size = 0
            oldest_timestamp = None
            newest_timestamp = None
            
            for cached_data in self._cache.values():
                dataframe = cached_data.get('dataframe')
                if dataframe is not None:
                    # 估算DataFrame大小（粗略计算）
                    total_size += dataframe.memory_usage(deep=True).sum()
                
                timestamp = cached_data.get('timestamp')
                if timestamp:
                    if oldest_timestamp is None or timestamp < oldest_timestamp:
                        oldest_timestamp = timestamp
                    if newest_timestamp is None or timestamp > newest_timestamp:
                        newest_timestamp = timestamp
            
            return {
                'total_items': total_items,
                'estimated_size_mb': round(total_size / (1024 * 1024), 2),
                'oldest_timestamp': oldest_timestamp.isoformat() if oldest_timestamp else None,
                'newest_timestamp': newest_timestamp.isoformat() if newest_timestamp else None,
                'default_ttl_seconds': self.default_ttl
            }


# 全局单例实例
_ohlcv_cache_instance: Optional[OHLCVCache] = None
_cache_lock = threading.Lock()


def get_ohlcv_cache(ttl_seconds: int = 300) -> OHLCVCache:
    """
    获取全局OHLCV缓存实例（单例模式）

    Args:
        ttl_seconds: 默认缓存有效期（秒），仅在首次创建时生效

    Returns:
        OHLCVCache实例
    """
    global _ohlcv_cache_instance

    if _ohlcv_cache_instance is None:
        with _cache_lock:
            if _ohlcv_cache_instance is None:
                _ohlcv_cache_instance = OHLCVCache(default_ttl_seconds=ttl_seconds)

    return _ohlcv_cache_instance


async def fetch_ohlcv_batch_async(
    exchange_service,
    symbols: list,
    timeframe: str,
    limit: int = 100,
    max_concurrent: int = 5
) -> Dict[str, Optional[pd.DataFrame]]:
    """
    并行批量获取多个交易对的 OHLCV 数据

    Args:
        exchange_service: ExchangeService 实例
        symbols: 交易对列表
        timeframe: 时间周期
        limit: 每个交易对获取的K线数量
        max_concurrent: 最大并发数（避免触发交易所限流）

    Returns:
        {symbol: DataFrame} 字典，获取失败的为 None
    """
    import asyncio

    cache = get_ohlcv_cache()
    exchange_name = exchange_service.exchange_name
    results: Dict[str, Optional[pd.DataFrame]] = {}

    # 分离缓存命中和需要获取的交易对
    symbols_to_fetch = []
    for symbol in symbols:
        cached_df = cache.get(exchange_name, symbol, timeframe)
        if cached_df is not None:
            results[symbol] = cached_df
            logger.debug(f"OHLCV 缓存命中: {symbol}")
        else:
            symbols_to_fetch.append(symbol)

    if not symbols_to_fetch:
        logger.debug(f"所有 {len(symbols)} 个交易对都命中缓存")
        return results

    logger.info(f"并行获取 {len(symbols_to_fetch)} 个交易对的 OHLCV 数据（缓存命中 {len(results)} 个）")

    # 使用信号量限制并发数
    semaphore = asyncio.Semaphore(max_concurrent)

    async def fetch_single(symbol: str) -> tuple:
        """获取单个交易对的数据"""
        async with semaphore:
            try:
                ohlcv = await exchange_service.fetch_ohlcv_async(symbol, timeframe, limit=limit)
                if not ohlcv:
                    return symbol, None

                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                df.set_index('timestamp', inplace=True)

                # 存入缓存
                cache.set(exchange_name, symbol, timeframe, df)

                return symbol, df
            except Exception as e:
                logger.warning(f"获取 {symbol} OHLCV 数据失败: {e}")
                return symbol, None

    # 并行执行所有请求
    tasks = [fetch_single(symbol) for symbol in symbols_to_fetch]
    fetch_results = await asyncio.gather(*tasks, return_exceptions=True)

    # 处理结果
    for result in fetch_results:
        if isinstance(result, Exception):
            logger.error(f"OHLCV 获取异常: {result}")
            continue
        if isinstance(result, tuple):
            symbol, df = result
            results[symbol] = df

    logger.info(f"OHLCV 批量获取完成: 成功 {sum(1 for v in results.values() if v is not None)}/{len(symbols)}")
    return results


def fetch_ohlcv_batch_sync(
    exchange_service,
    symbols: list,
    timeframe: str,
    limit: int = 100,
    max_workers: int = 5
) -> Dict[str, Optional[pd.DataFrame]]:
    """
    同步版本的批量获取 OHLCV 数据（使用线程池）

    Args:
        exchange_service: ExchangeService 实例
        symbols: 交易对列表
        timeframe: 时间周期
        limit: 每个交易对获取的K线数量
        max_workers: 最大线程数

    Returns:
        {symbol: DataFrame} 字典，获取失败的为 None
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    cache = get_ohlcv_cache()
    exchange_name = exchange_service.exchange_name
    results: Dict[str, Optional[pd.DataFrame]] = {}

    # 分离缓存命中和需要获取的交易对
    symbols_to_fetch = []
    for symbol in symbols:
        cached_df = cache.get(exchange_name, symbol, timeframe)
        if cached_df is not None:
            results[symbol] = cached_df
        else:
            symbols_to_fetch.append(symbol)

    if not symbols_to_fetch:
        return results

    logger.info(f"并行获取 {len(symbols_to_fetch)} 个交易对的 OHLCV 数据（线程池）")

    def fetch_single(symbol: str) -> tuple:
        """获取单个交易对的数据"""
        try:
            ohlcv = exchange_service.fetch_ohlcv(symbol, timeframe, limit=limit)
            if not ohlcv:
                return symbol, None

            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)

            # 存入缓存
            cache.set(exchange_name, symbol, timeframe, df)

            return symbol, df
        except Exception as e:
            logger.warning(f"获取 {symbol} OHLCV 数据失败: {e}")
            return symbol, None

    # 使用线程池并行执行
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_single, symbol): symbol for symbol in symbols_to_fetch}

        for future in as_completed(futures):
            try:
                symbol, df = future.result()
                results[symbol] = df
            except Exception as e:
                symbol = futures[future]
                logger.error(f"获取 {symbol} OHLCV 数据异常: {e}")
                results[symbol] = None

    return results

