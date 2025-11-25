"""
交易所服务 - CCXT集成
支持代理和WebSocket
"""
import ccxt
import ccxt.pro as ccxtpro
from typing import Optional, Dict, List, Any, Tuple
from app.core.config import settings
import asyncio
import logging
import json

logger = logging.getLogger(__name__)


def validate_exchange_name(exchange_name: str) -> Tuple[bool, str, Optional[str]]:
    """
    验证交易所名称是否有效
    
    Args:
        exchange_name: 交易所名称
        
    Returns:
        (is_valid, error_message, suggestion): 
        - is_valid: 是否有效
        - error_message: 错误信息（如果无效）
        - suggestion: 建议的正确名称（如果有相似匹配）
    """
    if not exchange_name or not exchange_name.strip():
        return False, "交易所名称不能为空", None
    
    exchange_name = exchange_name.strip().lower()
    
    # 检查交易所是否存在于 CCXT
    if not hasattr(ccxt, exchange_name):
        # 尝试查找相似的交易所名称（模糊匹配）
        available_exchanges = [name for name in dir(ccxt) 
                              if not name.startswith('_') and 
                              isinstance(getattr(ccxt, name, None), type)]
        
        # 简单的模糊匹配：检查是否有相似的交易所名称
        suggestions = []
        for ex in available_exchanges:
            if ex.lower() == exchange_name:
                return True, "", None
            # 检查是否只有一个字符不同（常见拼写错误）
            if len(ex) == len(exchange_name):
                diff = sum(1 for a, b in zip(ex.lower(), exchange_name) if a != b)
                if diff <= 1:
                    suggestions.append(ex)
        
        if suggestions:
            return False, f"交易所 '{exchange_name}' 不存在", suggestions[0]
        else:
            # 返回一些常见的交易所名称作为建议
            common_exchanges = ['binance', 'okx', 'bybit', 'gate', 'huobi', 'kraken', 'coinbase']
            return False, f"交易所 '{exchange_name}' 不存在。支持的交易所包括: {', '.join(common_exchanges)}", None
    
    return True, "", None


class ExchangeService:
    """交易所服务类"""
    
    def __init__(self, exchange_name: str, api_key: Optional[str] = None, 
                 api_secret: Optional[str] = None, proxy_config: Optional[Dict] = None):
        """
        初始化交易所
        
        Args:
            exchange_name: 交易所名称，如 'binance', 'okx'
            api_key: API密钥
            api_secret: API密钥
            proxy_config: 代理配置字典
        """
        self.exchange_name = exchange_name
        self.api_key = api_key
        self.api_secret = api_secret
        self.proxy_config = proxy_config or self._get_default_proxy_config()
        
        # 初始化同步交易所实例
        self.exchange = self._create_exchange()
        
        # WebSocket实例（异步）
        self.ws_exchange = None
        self._ws_initialized = False
    
    def _get_default_proxy_config(self) -> Dict:
        """
        获取默认代理配置
        CCXT不允许同时设置多个代理，优先级：PROXY_URL > SOCKS_PROXY > HTTP_PROXY/HTTPS_PROXY
        
        注意：代理URL格式应该是完整的URL，如 http://127.0.0.1:10809
        """
        config = {}
        # 优先级1: 通用代理URL
        # 注意：CCXT的'proxy'参数在某些版本中可能导致URL拼接错误
        # 使用'httpsProxy'或'httpProxy'更可靠
        if settings.PROXY_URL:
            # 确保代理URL格式正确
            proxy_url = settings.PROXY_URL.strip()
            # 如果URL没有协议前缀，添加http://
            if not proxy_url.startswith(('http://', 'https://', 'socks5://', 'socks4://')):
                proxy_url = f'http://{proxy_url}'
                logger.info(f"自动添加协议前缀，代理URL: {proxy_url}")
            # 移除末尾斜杠，避免URL拼接问题
            proxy_url = proxy_url.rstrip('/')
            # 使用httpsProxy而不是proxy，避免URL拼接错误
            config['httpsProxy'] = proxy_url
            logger.info(f"使用代理: {proxy_url}")
            return config
        
        # 优先级2: SOCKS代理
        if settings.SOCKS_PROXY:
            socks_url = settings.SOCKS_PROXY.strip()
            if not socks_url.startswith(('socks5://', 'socks4://')):
                # 如果没有协议前缀，添加socks5://
                if not socks_url.startswith('socks'):
                    socks_url = f'socks5://{socks_url}'
            config['socksProxy'] = socks_url
            return config
        
        # 优先级3: HTTP/HTTPS代理（只能设置一个，优先使用HTTPS）
        if settings.HTTPS_PROXY:
            https_proxy = settings.HTTPS_PROXY.strip()
            if not https_proxy.startswith(('http://', 'https://')):
                https_proxy = f'http://{https_proxy}'
            config['httpsProxy'] = https_proxy
        elif settings.HTTP_PROXY:
            http_proxy = settings.HTTP_PROXY.strip()
            if not http_proxy.startswith(('http://', 'https://')):
                http_proxy = f'http://{http_proxy}'
            config['httpProxy'] = http_proxy
        
        return config
    
    async def _to_thread(self, func, *args, **kwargs):
        """统一的线程池调用入口"""
        return await asyncio.to_thread(func, *args, **kwargs)
    
    def _create_exchange(self) -> ccxt.Exchange:
        """创建交易所实例"""
        # 验证交易所名称
        is_valid, error_msg, suggestion = validate_exchange_name(self.exchange_name)
        if not is_valid:
            if suggestion:
                raise ValueError(f"{error_msg}。您是否想输入 '{suggestion}'？")
            else:
                raise ValueError(error_msg)
        
        exchange_class = getattr(ccxt, self.exchange_name)
        
        config = {
            'apiKey': self.api_key,
            'secret': self.api_secret,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'swap',  # 永续合约
            }
        }
        
        # 添加代理配置（确保格式正确）
        # 注意：不要使用'proxy'参数，它会导致URL拼接错误
        # 只使用 httpProxy、httpsProxy 或 socksProxy
        if self.proxy_config:
            for key, value in self.proxy_config.items():
                if value:
                    # 跳过'proxy'参数，避免URL拼接错误
                    if key == 'proxy':
                        logger.warning("跳过'proxy'参数，使用'httpsProxy'替代以避免URL拼接错误")
                        continue
                    
                    # 对于代理URL，确保格式正确
                    if key in ['httpProxy', 'httpsProxy', 'socksProxy']:
                        proxy_value = str(value).strip()
                        # 确保代理URL以正确的协议开头，且格式完整
                        if key == 'socksProxy':
                            if not proxy_value.startswith(('socks5://', 'socks4://')):
                                if not proxy_value.startswith('socks'):
                                    proxy_value = f'socks5://{proxy_value}'
                        elif key in ['httpProxy', 'httpsProxy']:
                            if not proxy_value.startswith(('http://', 'https://')):
                                proxy_value = f'http://{proxy_value}'
                        # 确保URL格式正确（移除末尾的斜杠，避免拼接问题）
                        proxy_value = proxy_value.rstrip('/')
                        config[key] = proxy_value
                        # logger.info(f"设置代理配置: {key} = {proxy_value}")
                    else:
                        config[key] = value
        
        try:
            exchange = exchange_class(config)
            # logger.info(f"交易所 {self.exchange_name} 初始化成功")
            return exchange
        except Exception as e:
            logger.error(f"交易所 {self.exchange_name} 初始化失败: {e}")
            raise
    
    async def get_ws_exchange(self):
        """获取WebSocket交易所实例（懒加载）"""
        if not settings.WS_ENABLED:
            logger.debug(f"WebSocket未启用，跳过 {self.exchange_name} WebSocket初始化")
            return None
            
        if not self._ws_initialized:
            try:
                exchange_class = getattr(ccxtpro, self.exchange_name)
                config = {
                    'apiKey': self.api_key,
                    'secret': self.api_secret,
                    'enableRateLimit': True,
                    'options': {
                        'defaultType': 'swap',
                    },
                    'timeout': 60000,  # WebSocket 超时时间（毫秒），增加到60秒
                }
                
                # WebSocket 代理配置（如果支持）
                # 注意：CCXT 不允许同时设置多个代理，只能使用一个
                if self.proxy_config:
                    # 优先级：socksProxy > httpsProxy > httpProxy
                    ws_proxy_config = {}
                    if 'socksProxy' in self.proxy_config:
                        ws_proxy_config['socksProxy'] = self.proxy_config.get('socksProxy')
                        logger.info(f"WebSocket代理配置: 使用 socksProxy")
                    elif 'httpsProxy' in self.proxy_config:
                        ws_proxy_config['httpsProxy'] = self.proxy_config.get('httpsProxy')
                        logger.info(f"WebSocket代理配置: 使用 httpsProxy")
                    elif 'httpProxy' in self.proxy_config:
                        ws_proxy_config['httpProxy'] = self.proxy_config.get('httpProxy')
                        logger.info(f"WebSocket代理配置: 使用 httpProxy")
                    
                    if ws_proxy_config:
                        config.update(ws_proxy_config)
                
                self.ws_exchange = exchange_class(config)
                self._ws_initialized = True
                logger.info(f"WebSocket交易所 {self.exchange_name} 初始化成功")
            except Exception as e:
                logger.error(f"WebSocket交易所 {self.exchange_name} 初始化失败: {e}", exc_info=True)
                return None
        
        return self.ws_exchange
    
    def get_markets(self) -> Dict:
        """获取市场信息"""
        try:
            markets = self.exchange.load_markets()
            return markets
        except Exception as e:
            logger.error(f"获取市场信息失败: {e}")
            raise
    
    def get_tradable_symbols(self) -> List[str]:
        """获取可交易的交易对列表（永续合约）"""
        try:
            markets = self.get_markets()
            # 筛选永续合约
            tradable = [
                symbol for symbol, market in markets.items()
                if market.get('swap', False) and market.get('active', False)
            ]
            return tradable
        except Exception as e:
            logger.error(f"获取可交易对列表失败: {e}")
            raise
    
    async def get_tradable_symbols_async(self, force_refresh: bool = False) -> List[str]:
        """
        异步获取可交易的交易对列表（永续合约）
        
        Args:
            force_refresh: 是否强制刷新，忽略缓存
        
        Returns:
            可交易对列表
        """
        try:
            # 使用异步方法获取市场信息
            markets = await self.get_markets_async(force_refresh=force_refresh)
            # 筛选永续合约
            tradable = [
                symbol for symbol, market in markets.items()
                if market.get('swap', False) and market.get('active', False)
            ]
            return tradable
        except Exception as e:
            logger.error(f"异步获取可交易对列表失败: {e}")
            raise
    
    async def get_markets_async(self, force_refresh: bool = False) -> Dict:
        """
        异步获取市场信息（使用缓存）
        
        Args:
            force_refresh: 是否强制刷新，忽略缓存
        
        Returns:
            市场信息字典
        """
        try:
            # 使用缓存服务
            from app.services.cache import cache_service
            cache_key = f"markets:{self.exchange_name}"
            
            if not force_refresh:
                cached = await cache_service.get(cache_key)
                if cached is not None:
                    return cached
            
            # 在线程池中执行同步调用
            markets = await self._to_thread(self.exchange.load_markets)
            
            # 缓存结果（市场信息变化不频繁，缓存10分钟）
            await cache_service.set(
                cache_key, 
                markets, 
                ttl=600  # 10分钟
            )
            
            return markets
        except Exception as e:
            logger.error(f"异步获取市场信息失败: {e}")
            raise
    
    async def get_ticker_price_async(
        self,
        symbol: str,
        use_cache: bool = True,
        cache_ttl: Optional[float] = None
    ) -> float:
        """
        异步获取指定交易对的最新价格（支持缓存）
        
        Args:
            symbol: 交易对，例如 'BTC/USDT:USDT'
            use_cache: 是否启用缓存
            cache_ttl: 缓存有效期（秒）
        
        Returns:
            最新价格（float），获取失败时返回 0.0
        """
        cache_key = f"ticker:{self.exchange_name}:{symbol}"
        ttl = cache_ttl if cache_ttl is not None else settings.CACHE_TICKER_TTL
        
        try:
            if use_cache:
                from app.services.cache import cache_service
                cached_price = await cache_service.get(cache_key)
                if isinstance(cached_price, (int, float)) and cached_price > 0:
                    return float(cached_price)
        except Exception as exc:
            logger.debug(f"读取价格缓存失败 {cache_key}: {exc}")
        
        try:
            ticker = await self._to_thread(self.exchange.fetch_ticker, symbol)
            price = ticker.get('last') or ticker.get('close') or ticker.get('bid') or ticker.get('ask') or 0.0
            price = float(price or 0.0)
            
            if price > 0 and use_cache:
                try:
                    from app.services.cache import cache_service
                    await cache_service.set(cache_key, price, ttl=ttl)
                except Exception as exc:
                    logger.debug(f"写入价格缓存失败 {cache_key}: {exc}")
            
            return price
        except Exception as e:
            logger.error(f"获取 {symbol} 当前价格失败: {e}")
            return 0.0
    
    def fetch_ohlcv(self, symbol: str, timeframe: str = '1h', 
                   since: Optional[int] = None, limit: int = 100) -> List:
        """
        获取OHLCV数据
        
        Args:
            symbol: 交易对
            timeframe: 时间周期，如 '1m', '5m', '1h', '1d'
            since: 起始时间戳（毫秒）
            limit: 返回数量限制
        """
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, since, limit)
            return ohlcv
        except Exception as e:
            logger.error(f"获取 {symbol} OHLCV数据失败: {e}")
            raise
    
    async def watch_ohlcv(self, symbol: str, timeframe: str = '1h'):
        """通过WebSocket订阅OHLCV数据"""
        ws_exchange = await self.get_ws_exchange()
        if not ws_exchange:
            return  # 异步生成器不能返回值，只能使用 return 结束
        
        try:
            while True:
                ohlcv = await ws_exchange.watch_ohlcv(symbol, timeframe)
                yield ohlcv
        except Exception as e:
            logger.error(f"WebSocket订阅 {symbol} OHLCV失败: {e}")
            raise
    
    async def watch_ticker(self, symbol: str, max_retries: int = 3):
        """
        通过WebSocket订阅实时价格数据，使用 Binance 官方 WebSocket API
        支持 aiohttp 代理（包括 SOCKS5）
        """
        if not settings.WS_ENABLED:
            logger.warning(f"WebSocket未启用，无法订阅 {symbol} 实时价格")
            return
        
        # 只支持 Binance（目前）
        if self.exchange_name.lower() != 'binance':
            logger.warning(f"官方 WebSocket API 目前只支持 Binance，交易所 {self.exchange_name} 将使用轮询模式")
            return
        
        try:
            import aiohttp
        except ImportError:
            logger.error("需要安装 aiohttp 库: pip install aiohttp")
            return
        
        # 转换 symbol 格式：BTC/USDT:USDT -> btcusdt
        binance_symbol = self._convert_to_binance_symbol(symbol)
        if not binance_symbol:
            logger.error(f"无法转换交易对格式: {symbol}")
            return
        
        # Binance 合约（永续）WebSocket 端点
        # 现货: wss://stream.binance.com:9443
        # 合约: wss://fstream.binance.com
        base_url = "wss://fstream.binance.com"
        stream_name = f"{binance_symbol}@ticker"
        ws_url = f"{base_url}/ws/{stream_name}"
        
        # 代理配置
        connector = None
        proxy = None
        
        if self.proxy_config:
            if 'socksProxy' in self.proxy_config:
                socks_url = self.proxy_config['socksProxy']
                logger.info(f"使用 SOCKS5 代理: {socks_url}")
                try:
                    from aiohttp_socks import ProxyConnector
                    connector = ProxyConnector.from_url(socks_url)
                    logger.debug("使用 aiohttp_socks 处理 SOCKS5 代理")
                except ImportError:
                    logger.warning("未安装 aiohttp_socks，SOCKS5 代理无法使用")
                    logger.warning("安装命令: pip install aiohttp-socks")
                    connector = aiohttp.TCPConnector()
            elif 'httpsProxy' in self.proxy_config:
                proxy = self.proxy_config['httpsProxy']
                logger.info(f"使用 HTTPS 代理: {proxy}")
                connector = aiohttp.TCPConnector()
            elif 'httpProxy' in self.proxy_config:
                proxy = self.proxy_config['httpProxy']
                logger.info(f"使用 HTTP 代理: {proxy}")
                connector = aiohttp.TCPConnector()
        
        if connector is None:
            connector = aiohttp.TCPConnector()
        
        retry_count = 0
        while retry_count < max_retries:
            try:
                logger.debug(f"尝试订阅 {symbol} 的实时价格 (尝试 {retry_count + 1}/{max_retries})")
                logger.debug(f"WebSocket URL: {ws_url}")
                
                timeout = aiohttp.ClientTimeout(total=60, connect=30)
                
                async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                    async with session.ws_connect(
                        ws_url,
                        proxy=proxy if proxy else None,  # SOCKS5 通过 connector 处理
                        heartbeat=20,  # 每20秒发送心跳（对应 Binance 的 ping）
                    ) as ws:
                        logger.debug(f"✓ WebSocket 连接成功: {symbol}")
                        
                        # 持续接收数据
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                try:
                                    data = json.loads(msg.data)
                                    
                                    # 处理 ticker 数据
                                    if 'e' in data and data['e'] == '24hrTicker':
                                        # 转换为 CCXT 格式的 ticker
                                        ticker = self._convert_binance_ticker_to_ccxt(data, symbol)
                                        if ticker:
                                            retry_count = 0  # 成功接收数据，重置重试计数
                                            yield ticker
                                    
                                except json.JSONDecodeError:
                                    logger.debug(f"收到非 JSON 消息: {msg.data[:100]}")
                            
                            elif msg.type == aiohttp.WSMsgType.ERROR:
                                logger.error(f"WebSocket 错误: {ws.exception()}")
                                break
                            
                            elif msg.type == aiohttp.WSMsgType.CLOSE:
                                logger.warning(f"WebSocket 连接已关闭: {symbol}")
                                break
                        
                        # 如果正常退出循环，说明连接关闭，需要重试
                        if retry_count < max_retries - 1:
                            logger.warning(f"WebSocket 连接关闭，准备重试...")
                            await asyncio.sleep(2 ** retry_count)  # 指数退避
                            retry_count += 1
                            continue
                        else:
                            break
                            
            except asyncio.TimeoutError:
                retry_count += 1
                logger.warning(
                    f"WebSocket订阅 {symbol} 连接超时 (尝试 {retry_count}/{max_retries})"
                )
            except aiohttp.ClientConnectorError as e:
                retry_count += 1
                logger.error(f"WebSocket连接失败: {e} (尝试 {retry_count}/{max_retries})")
            except Exception as e:
                retry_count += 1
                error_msg = str(e)
                logger.error(f"WebSocket订阅 {symbol} 失败: {e} (尝试 {retry_count}/{max_retries})")
            
            if retry_count >= max_retries:
                logger.error(f"WebSocket订阅 {symbol} 达到最大重试次数，放弃订阅")
                raise
            
            # 等待一段时间后重试
            await asyncio.sleep(2 ** retry_count)  # 指数退避：2秒、4秒、8秒
    
    def _convert_to_binance_symbol(self, symbol: str) -> Optional[str]:
        """
        转换交易对格式：BTC/USDT:USDT -> btcusdt
        """
        try:
            # 移除 :USDT 后缀（永续合约标记）
            if ':' in symbol:
                symbol = symbol.split(':')[0]
            
            # 分割基础货币和报价货币
            if '/' in symbol:
                base, quote = symbol.split('/')
                return f"{base.lower()}{quote.lower()}"
            else:
                # 已经是 binance 格式
                return symbol.lower()
        except Exception as e:
            logger.error(f"转换交易对格式失败: {symbol}, 错误: {e}")
            return None
    
    def _convert_binance_ticker_to_ccxt(self, binance_data: Dict, original_symbol: str) -> Optional[Dict]:
        """
        将 Binance WebSocket ticker 数据转换为 CCXT 格式
        """
        try:
            # Binance 24hrTicker 字段映射到 CCXT ticker 格式
            ticker = {
                'symbol': original_symbol,
                'last': float(binance_data.get('c', 0)),  # 最新价
                'bid': float(binance_data.get('b', 0)),  # 买一价
                'ask': float(binance_data.get('a', 0)),  # 卖一价
                'high': float(binance_data.get('h', 0)),  # 最高价
                'low': float(binance_data.get('l', 0)),  # 最低价
                'open': float(binance_data.get('o', 0)),  # 开盘价
                'close': float(binance_data.get('c', 0)),  # 收盘价（最新价）
                'volume': float(binance_data.get('v', 0)),  # 24h成交量（基础货币）
                'quoteVolume': float(binance_data.get('q', 0)),  # 24h成交量（报价货币）
                'change': float(binance_data.get('p', 0)),  # 价格变化
                'percentage': float(binance_data.get('P', 0)),  # 价格变化百分比
                'timestamp': binance_data.get('E', 0),  # 事件时间
                'datetime': None,  # 可以后续转换
                'info': binance_data,  # 原始数据
            }
            return ticker
        except Exception as e:
            logger.error(f"转换 Binance ticker 数据失败: {e}")
            return None
    
    def create_order(self, symbol: str, side: str, order_type: str, 
                    amount: float, price: Optional[float] = None, 
                    params: Optional[Dict] = None) -> Dict:
        """
        创建订单
        
        Args:
            symbol: 交易对
            side: 'buy' 或 'sell'
            order_type: 'market', 'limit', 'stop', 'stop_limit'
            amount: 数量
            price: 价格（限价单必需）
            params: 额外参数
        """
        try:
            order = self.exchange.create_order(
                symbol, order_type, side, amount, price, params or {}
            )
            logger.info(f"订单创建成功: {order.get('id')}")
            return order
        except Exception as e:
            logger.error(f"创建订单失败: {e}")
            raise
    
    def fetch_order(self, order_id: str, symbol: str) -> Dict:
        """获取订单状态"""
        try:
            order = self.exchange.fetch_order(order_id, symbol)
            return order
        except Exception as e:
            logger.error(f"获取订单状态失败: {e}")
            raise
    
    def fetch_open_orders(self, symbol: Optional[str] = None) -> List[Dict]:
        """获取未成交订单"""
        try:
            orders = self.exchange.fetch_open_orders(symbol)
            return orders
        except Exception as e:
            logger.error(f"获取未成交订单失败: {e}")
            raise
    
    def fetch_positions(self, symbol: Optional[str] = None) -> List[Dict]:
        """获取持仓信息"""
        try:
            positions = self.exchange.fetch_positions(symbol)
            # 只返回未平仓持仓
            open_positions = [p for p in positions if p.get('contracts', 0) != 0]
            return open_positions
        except Exception as e:
            logger.error(f"获取持仓信息失败: {e}")
            raise
    
    def cancel_order(self, order_id: str, symbol: str) -> Dict:
        """取消订单"""
        try:
            result = self.exchange.cancel_order(order_id, symbol)
            return result
        except Exception as e:
            logger.error(f"取消订单失败: {e}")
            raise
    
    def set_leverage(self, leverage: int, symbol: str):
        """设置杠杆"""
        try:
            self.exchange.set_leverage(leverage, symbol)
            logger.info(f"设置 {symbol} 杠杆为 {leverage}x")
        except Exception as e:
            logger.error(f"设置杠杆失败: {e}")
            raise

