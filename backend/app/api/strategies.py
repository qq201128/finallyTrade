"""
策略管理API
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from app.core.database import get_db
from app.models.strategy import Strategy, UserStrategy, StrategyHistory
from app.models.trade import PnLRecord
from app.models.user import User
from app.api.auth import get_current_user
from app.services.strategy_engine import StrategyEngine
from app.services.trading_scheduler import start_strategy, stop_strategy, restart_strategy, get_running_strategies
from app.services.exchange_service import validate_exchange_name, ExchangeService
from app.core.config import settings
import logging

router = APIRouter(prefix="/api/strategies", tags=["strategies"])
logger = logging.getLogger(__name__)

strategy_engine = StrategyEngine(settings.STRATEGIES_DIR)


class StrategyResponse(BaseModel):
    id: int
    name: str
    description: str
    file_path: str
    is_active: bool
    config: dict

    class Config:
        from_attributes = True


class UserStrategyResponse(BaseModel):
    id: int
    user_id: int
    strategy_id: int
    is_enabled: bool
    config: dict
    exchange: str
    symbols: list = []  # 币种列表
    timeframe: Optional[str] = None  # 时间周期（可选）
    trade_amount: Optional[str] = None  # 每笔交易数量（可选）
    is_simulated: bool = False  # 是否模拟运行
    strategy: StrategyResponse

    class Config:
        from_attributes = True


class UserStrategyCreate(BaseModel):
    strategy_id: int
    exchange: str
    api_key: Optional[str] = None  # API Key（可选）
    api_secret: Optional[str] = None  # API Secret（可选）
    config: dict = {}
    symbols: list = []  # 币种列表（可选多个，只支持永续合约）
    timeframe: Optional[str] = None  # 时间周期（可选），如 '1m', '5m', '15m', '1h', '4h', '1d'
    trade_amount: Optional[str] = None  # 每笔交易使用的加密货币数量（可选）
    is_simulated: bool = False  # 是否模拟运行


class UserStrategyUpdate(BaseModel):
    is_enabled: bool = None
    exchange: str = None  # 交易所名称
    api_key: str = None  # API Key
    api_secret: str = None  # API Secret
    config: dict = None
    symbols: list = None  # 币种列表
    timeframe: str = None  # 时间周期
    trade_amount: str = None  # 每笔交易数量
    is_simulated: bool = None  # 是否模拟运行


@router.get("/", response_model=List[StrategyResponse])
async def get_strategies(db: Session = Depends(get_db)):
    """获取所有策略列表"""
    strategies = db.query(Strategy).filter(Strategy.is_active == True).all()
    return strategies


@router.get("/files", response_model=List[str])
async def get_strategy_files():
    """获取策略文件列表"""
    files = strategy_engine.get_strategy_list()
    return files


@router.get("/exchanges", response_model=List[str])
async def get_available_exchanges():
    """获取可用的交易所列表"""
    import ccxt
    # 获取所有可用的交易所
    exchanges = []
    for name in dir(ccxt):
        if not name.startswith('_'):
            obj = getattr(ccxt, name, None)
            if isinstance(obj, type) and issubclass(obj, ccxt.Exchange):
                exchanges.append(name)
    # 返回排序后的列表
    return sorted(exchanges)


@router.get("/symbols", response_model=List[str])
async def get_exchange_symbols(exchange: str):
    """获取指定交易所支持的永续合约交易对列表"""
    try:
        exchange_service = ExchangeService(exchange_name=exchange)
        symbols = await exchange_service.get_tradable_symbols_async()
        return sorted(symbols)
    except Exception as e:
        logger.error(f"获取交易所 {exchange} 交易对失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取交易所交易对失败: {str(e)}"
        )

@router.get("/user", response_model=List[UserStrategyResponse])
async def get_user_strategies(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取用户的策略配置"""
    user_strategies = db.query(UserStrategy).filter(
        UserStrategy.user_id == current_user.id
    ).all()
    return user_strategies


@router.post("/user", response_model=UserStrategyResponse, status_code=status.HTTP_201_CREATED)
async def create_user_strategy(
    strategy_data: UserStrategyCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """创建用户策略配置"""
    # 验证策略是否存在
    strategy = db.query(Strategy).filter(Strategy.id == strategy_data.strategy_id).first()
    if not strategy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Strategy not found"
        )
    
    # 验证交易所名称
    is_valid, error_msg, suggestion = validate_exchange_name(strategy_data.exchange)
    if not is_valid:
        if suggestion:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{error_msg}。您是否想输入 '{suggestion}'？"
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_msg
            )
    
    try:
        user_strategy = UserStrategy(
            user_id=current_user.id,
            strategy_id=strategy_data.strategy_id,
            exchange=strategy_data.exchange,
            api_key=strategy_data.api_key if strategy_data.api_key else None,  # 实际应用中应该加密存储
            api_secret=strategy_data.api_secret if strategy_data.api_secret else None,  # 实际应用中应该加密存储
            config=strategy_data.config,
            symbols=strategy_data.symbols if strategy_data.symbols else [],
            timeframe=strategy_data.timeframe if strategy_data.timeframe else None,
            trade_amount=strategy_data.trade_amount if strategy_data.trade_amount else None,
            is_simulated=strategy_data.is_simulated if strategy_data.is_simulated is not None else False,
            is_enabled=True
        )
        db.add(user_strategy)
        db.flush()  # 刷新到数据库但不提交，这样可以获取ID等自动生成的值
        
        # 在提交前验证响应模型，确保可以正确序列化
        try:
            # 尝试创建响应对象，如果失败会抛出异常
            UserStrategyResponse.model_validate(user_strategy)
        except Exception as e:
            # 如果响应验证失败，回滚数据库操作（此时还没有commit）
            db.rollback()
            logger.error(f"响应验证失败，已回滚数据库操作: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"创建策略失败: 响应验证错误 - {str(e)}"
            )
        
        # 验证通过后，提交事务
        db.commit()
        db.refresh(user_strategy)
        
        # 自动启动策略的连续循环
        try:
            start_strategy(user_strategy.id)
        except Exception as e:
            logger.error(f"自动启动策略 {user_strategy.id} 失败: {e}")
        
        return user_strategy
    except HTTPException:
        # 重新抛出 HTTP 异常
        raise
    except Exception as e:
        # 其他异常，回滚数据库操作
        db.rollback()
        logger.error(f"创建策略失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"创建策略失败: {str(e)}"
        )


@router.put("/user/{user_strategy_id}", response_model=UserStrategyResponse)
async def update_user_strategy(
    user_strategy_id: int,
    strategy_data: UserStrategyUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """更新用户策略配置"""
    user_strategy = db.query(UserStrategy).filter(
        UserStrategy.id == user_strategy_id,
        UserStrategy.user_id == current_user.id
    ).first()
    
    if not user_strategy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User strategy not found"
        )
    
    # 如果更新了交易所名称，验证其有效性
    if strategy_data.exchange is not None:
        is_valid, error_msg, suggestion = validate_exchange_name(strategy_data.exchange)
        if not is_valid:
            if suggestion:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"{error_msg}。您是否想输入 '{suggestion}'？"
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=error_msg
                )
        user_strategy.exchange = strategy_data.exchange
    
    # 如果更新了 API 密钥
    if strategy_data.api_key is not None:
        user_strategy.api_key = strategy_data.api_key
    if strategy_data.api_secret is not None:
        user_strategy.api_secret = strategy_data.api_secret
    
    # 如果启用状态发生变化，需要启动或停止策略循环
    if strategy_data.is_enabled is not None:
        old_enabled = user_strategy.is_enabled
        user_strategy.is_enabled = strategy_data.is_enabled
        
        # 如果从禁用变为启用，启动策略循环
        if not old_enabled and strategy_data.is_enabled:
            db.flush()  # 先刷新，使其他线程读取到最新状态
            start_strategy(user_strategy_id)
        # 如果从启用变为禁用，停止策略循环
        elif old_enabled and not strategy_data.is_enabled:
            db.flush()
            stop_strategy(user_strategy_id)
    
    if strategy_data.config is not None:
        user_strategy.config = strategy_data.config
    
    # 更新新配置字段
    if strategy_data.symbols is not None:
        user_strategy.symbols = strategy_data.symbols
    if strategy_data.timeframe is not None:
        user_strategy.timeframe = strategy_data.timeframe
    if strategy_data.trade_amount is not None:
        user_strategy.trade_amount = strategy_data.trade_amount
    if strategy_data.is_simulated is not None:
        user_strategy.is_simulated = strategy_data.is_simulated
    
    # 如果配置发生变化且策略正在运行，重启以应用新配置
    if user_strategy.is_enabled and user_strategy_id in get_running_strategies():
        if (strategy_data.config is not None or 
            strategy_data.symbols is not None or 
            strategy_data.timeframe is not None or 
            strategy_data.trade_amount is not None or 
            strategy_data.is_simulated is not None):
            restart_strategy(user_strategy_id)
    
    db.commit()
    db.refresh(user_strategy)
    return user_strategy


@router.get("/user/{user_strategy_id}/replenish-state")
async def get_replenish_state(
    user_strategy_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取双向策略的补仓状态（诊断用）"""
    user_strategy = db.query(UserStrategy).filter(
        UserStrategy.id == user_strategy_id,
        UserStrategy.user_id == current_user.id
    ).first()
    
    if not user_strategy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="策略不存在"
        )
    
    # 获取补仓状态
    config = user_strategy.config or {}
    replenish_state = config.get('replenish_state', {
        'long': {'wins': 0, 'last_trend': None, 'replenish_pool': []},
        'short': {'wins': 0, 'last_trend': None, 'replenish_pool': []}
    })
    
    return {
        'user_strategy_id': user_strategy_id,
        'position_adjustment_enabled': config.get('position_adjustment', False),
        'replenish_state': replenish_state,
        'long': {
            'wins': replenish_state.get('long', {}).get('wins', 0),
            'last_trend': replenish_state.get('long', {}).get('last_trend'),
            'replenish_pool_count': len(replenish_state.get('long', {}).get('replenish_pool', [])),
            'replenish_pool': replenish_state.get('long', {}).get('replenish_pool', [])
        },
        'short': {
            'wins': replenish_state.get('short', {}).get('wins', 0),
            'last_trend': replenish_state.get('short', {}).get('last_trend'),
            'replenish_pool_count': len(replenish_state.get('short', {}).get('replenish_pool', [])),
            'replenish_pool': replenish_state.get('short', {}).get('replenish_pool', [])
        }
    }


@router.get("/user/{user_strategy_id}/history")
async def get_strategy_history(
    user_strategy_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = 50
):
    """获取策略历史记录"""
    # 验证策略属于当前用户
    user_strategy = db.query(UserStrategy).filter(
        UserStrategy.id == user_strategy_id,
        UserStrategy.user_id == current_user.id
    ).first()
    
    if not user_strategy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Strategy not found"
        )
    
    # 获取历史记录
    history_records = db.query(StrategyHistory).filter(
        StrategyHistory.user_strategy_id == user_strategy_id
    ).order_by(StrategyHistory.started_at.desc()).limit(limit).all()
    
    return [
        {
            "id": h.id,
            "started_at": h.started_at.isoformat() if h.started_at else None,
            "stopped_at": h.stopped_at.isoformat() if h.stopped_at else None,
            "total_realized_pnl": h.total_realized_pnl,
            "total_trades": h.total_trades,
            "total_positions": h.total_positions,
            "is_running": h.is_running
        }
        for h in history_records
    ]


@router.delete("/user/{user_strategy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user_strategy(
    user_strategy_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """删除用户策略配置"""
    user_strategy = db.query(UserStrategy).filter(
        UserStrategy.id == user_strategy_id,
        UserStrategy.user_id == current_user.id
    ).first()
    
    if not user_strategy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User strategy not found"
        )
    
    # 如果策略正在运行，先停止它
    if user_strategy.is_enabled:
        stop_strategy(user_strategy_id)
    
    # 删除关联的盈亏记录，以避免外键约束
    try:
        db.query(PnLRecord).filter(
            PnLRecord.user_strategy_id == user_strategy_id
        ).delete()
    except Exception as e:
        db.rollback()
        logger.error(f"删除策略 {user_strategy_id} 的盈亏记录失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"删除策略的盈亏记录失败: {str(e)}"
        )
    
    db.delete(user_strategy)
    db.commit()
    return None
