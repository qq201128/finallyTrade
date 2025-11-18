"""
量化加密货币交易策略分析师（DeepSeek版）
==========================================

Profile 概述
------------
- language: 中文 / English
- description: 专注永续合约的激进量化专家，擅长多周期融合、动态仓位与激进风险控制。
- background: 深耕技术分析、市场微观结构与衍生品定价，熟练运用 EMA / MACD / RSI、
  持仓量(OI)与资金费率做综合研判。
- personality: 理性果断，敢于在高波动中抓取利润，同时坚守数据驱动与纪律。
- expertise: 技术分析、多时间框架、永续合约、动态仓位、资金费率套利、金字塔加仓等。
- target_audience: 自动化交易系统、量化平台、算法交易引擎。

核心能力
--------
1. 多维市场分析：3分钟 VS 4小时联动、量价配合、ATR 波动率评估。
2. 衍生品专业：OI、资金费率、杠杆与清算风险精细管理。
3. 策略执行：标准化信号、动态仓位（单笔风险 8-15%）、分级止盈止损。
4. 风控纪律：实时监控、单日亏损/连亏熔断、集中持仓（2-4 个核心仓）。

激进策略库
-----------
- 突破追踪：24h 高低点突破 + 150% 放量 → 15-20x 杠杆，ATR×1 止损。
- 金字塔加仓：初始 8-10% 资金，1R→+6-8%，2R→+4-6%，总加仓 ≤150%。
- 资金费率套利：|funding|>0.02% 逆向开仓，ATR×1.5 止损。
- 极端 RSI 反转：RSI>80 连续 2 根后下拐即开空，20-25x 杠杆，5% 止损/8-12% 止盈。
- 动量追踪：MACD 柱体爆发 + 关键 EMA 突破 + 200% 放量，ATR×1 止损 + 移动止盈。

执行准则与限制
---------------
- 单笔风险： confidence≥0.85 → 12-15%；0.75-0.85 → 8-12%；0.65-0.75 → 6-8%；0.55-0.65 → 4-6%。
- 杠杆：同上依次 20-25x / 15-20x / 10-15x / 5-10x。
- 名义价值限制：BTC/ETH ≤ 资本 50%；SOL/BNB/XRP ≤ 40%；其他 ≤ 30%。
- 现金储备：保持 15-20%，最低 10%。
- 分批止盈：1R → 平 50% 且止损至 BE；2R → 平 25% 且止损至 1R；余 25% 用 ATR×2 trailing。
- 优先级：无效化 > 仓位超限 > 盈利 1R/2R 减仓 > 信号强化加仓 > 新开仓。

工作流（用于生成 JSON 信号）
----------------------------
1. 市场评估（BTC 4h EMA20/EMA50、资金费率、OI）。
2. 持仓管理（检查 invalidation / R 倍数 / 加减仓）。
3. 新机会筛选（极强&标准信号、资金费率套利、逆势反转）。
4. 仓位规模计算（风险、杠杆、名义价值限制）。
5. 止盈止损定义（ATR/波动与 confidence 映射）。
6. 生成 signal/quantity/leverage/profit_target/stop_loss/invalidation/confidence/risk/justification 的字典，
   上层控制器可直接序列化为 JSON。

风险披露
--------
- 目标年化 120-200%，最大回撤 30-40%，胜率 50-55%，高杠杆伴随高清算风险。
- 单日亏损 >15% 停盘 24h；连亏 3 次降级至保守模式；回撤 >40% 全面降杠杆。

绩效追踪
--------
- 需跟踪收益率 / 最大回撤 / 夏普 / 胜率 / 盈亏比 / 连亏 / 实际杠杆 / 各 confidence 胜率等指标。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import talib

# === 参数区（可根据市场特性做细调） ===
DEFAULT_TIMEFRAME_MINUTES = 1
SHORT_WINDOW_MINUTES = 3  # 3m
MID_WINDOW_MINUTES = 4 * 60  # 4h

RISK_CONFIG = {
    'max_loss_pct': -0.15,          # 单笔最大允许亏损
    'soft_stop_pct': -0.08,         # 预警止损（触发后等待反抽）
    'tp_levels': [0.06, 0.12, 0.2], # 分级止盈
    'tp_reduce': [0.35, 0.35, 0.3], # 各级减仓权重
    'trailing_buffer': 0.035,       # 移动止盈回撤
}

PYRAMID_CONFIG = {
    'step_roi': 0.025,    # 每当浮盈超过 2.5% 允许加仓
    'max_layers': 3,
    'increment_pct': 0.35 # 每层加仓比例
}

CORE_SYMBOLS = {'BTC', 'BTCUSDT', 'BTC/USDT', 'ETH', 'ETHUSDT', 'ETH/USDT'}
MAJOR_SYMBOLS = {'SOL', 'SOLUSDT', 'SOL/USDT', 'BNB', 'BNBUSDT', 'BNB/USDT', 'XRP', 'XRPUSDT', 'XRP/USDT'}


@dataclass
class StrategyProfile:
    language: str = "中文/English"
    description: str = "Aggressive multi-timeframe crypto derivatives strategist."
    background: str = "Technical analysis + derivatives microstructure + dynamic risk."
    personality: str = "Rational, decisive, aggressive but disciplined."
    expertise: List[str] = field(default_factory=lambda: [
        "Multi-timeframe TA", "Perpetual swaps", "Dynamic position sizing",
        "Aggressive risk control", "Funding-rate arbitrage", "Pyramiding"
    ])
    target_audience: str = "Automated trading engines / quant platforms"


@dataclass
class MarketEnvironment:
    btc_trend: str = "neutral"
    stage: str = "range"
    funding_bias: Optional[str] = None
    oi_signal: Optional[str] = None
    news_bias: float = 0.0  # -0.1 ~ +0.1


class DeepSeekDecisionEngine:
    """
    将高层文字化规则映射为可执行的策略指令，供策略控制器调用。
    控制器只需传入 market_state 字典，便可获得标准化的信号字典，
    再由外层序列化为 JSON（满足 signal/quantity/leverage/... 格式要求）。
    """

    def __init__(
        self,
        profile: StrategyProfile,
        risk_config: Dict[str, Any]
    ):
        self.profile = profile
        self.risk_config = risk_config

    # ------------------------------------------------------------------ #
    # 公共入口
    # ------------------------------------------------------------------ #
    def generate_trade_directives(self, market_state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """
        根据 market_state（包含市场上下文、可用资金、现有持仓、潜在机会等）
        输出标准化的信号字典：{symbol: {...fields...}}
        """
        env = self._build_environment(market_state.get('market_context', {}))
        directives: Dict[str, Dict[str, Any]] = {}

        # Step 2: 现有持仓激进管理
        for position in market_state.get('positions', []):
            action = self._manage_position(position, env)
            if action:
                directives[position['symbol']] = action

        # Step 3/4/5: 新信号筛选 + 仓位规模 + 止盈止损
        available_cash = max(float(market_state.get('available_cash', 0)), 0.0)
        initial_capital = float(market_state.get('initial_capital', available_cash))
        opportunities = market_state.get('opportunities', [])

        if opportunities and available_cash > 0:
            for opportunity in opportunities:
                signal = self._evaluate_opportunity(
                    opportunity=opportunity,
                    env=env,
                    available_cash=available_cash,
                    initial_capital=initial_capital,
                    existing_symbols=list(directives.keys())
                )
                if signal:
                    directives[opportunity['symbol']] = signal

        # Step 5+6: 如无信号且有持仓，则保持 hold 指令
        if not directives:
            for position in market_state.get('positions', []):
                directives[position['symbol']] = self._build_hold_signal(position)

        return directives

    # ------------------------------------------------------------------ #
    # 市场环境 / 信息融合
    # ------------------------------------------------------------------ #
    def _build_environment(self, context: Dict[str, Any]) -> MarketEnvironment:
        ema20 = context.get('btc_4h_ema20')
        ema50 = context.get('btc_4h_ema50')
        btc_trend = "neutral"
        if ema20 and ema50:
            if ema20 > ema50 * 1.01:
                btc_trend = "bullish"
            elif ema20 < ema50 * 0.99:
                btc_trend = "bearish"

        stage = context.get('market_stage') or ("trend" if btc_trend != "neutral" else "range")
        funding_bias = None
        funding_rate = context.get('aggregate_funding_rate')
        if funding_rate is not None:
            if funding_rate > 0.02:
                funding_bias = "positive_extreme"
            elif funding_rate < -0.02:
                funding_bias = "negative_extreme"

        oi_signal = None
        oi_change = context.get('oi_change_pct')
        if oi_change is not None:
            if oi_change > 10:
                oi_signal = "surge"
            elif oi_change < -10:
                oi_signal = "flush"

        news_bias = float(context.get('news_bias', 0.0))
        news_bias = max(-0.1, min(0.1, news_bias))

        return MarketEnvironment(
            btc_trend=btc_trend,
            stage=stage,
            funding_bias=funding_bias,
            oi_signal=oi_signal,
            news_bias=news_bias
        )

    # ------------------------------------------------------------------ #
    # 现有持仓管理
    # ------------------------------------------------------------------ #
    def _manage_position(self, position: Dict[str, Any], env: MarketEnvironment) -> Optional[Dict[str, Any]]:
        symbol = position.get('symbol')
        entry = position.get('entry_price') or 0
        current = position.get('current_price') or 0
        stop_loss = position.get('stop_loss') or position.get('initial_stop')
        direction = position.get('side', 'long')
        quantity = abs(position.get('quantity') or position.get('size') or 0)
        leverage = position.get('leverage') or 10
        invalid_triggered = position.get('invalidation_triggered', False)
        invalid_text = position.get('invalidation_condition') or "Price closes beyond stop on 3m candle"

        if not symbol or entry <= 0 or current <= 0 or quantity <= 0:
            return None

        risk_unit = None
        if stop_loss and stop_loss > 0:
            risk_unit = abs(entry - stop_loss)
        elif position.get('atr'):
            risk_unit = max(position['atr'], entry * 0.01)

        r_multiple = None
        if risk_unit and risk_unit > 0:
            if direction == 'long':
                r_multiple = (current - entry) / risk_unit
            else:
                r_multiple = (entry - current) / risk_unit

        # 无效化优先
        if invalid_triggered:
            return self._build_close_signal(
                position=position,
                reduce_ratio=1.0,
                invalidation=invalid_text,
                reason="Invalidation triggered - immediate exit"
            )

        # R 倍数规则
        if r_multiple is not None:
            if r_multiple >= 2.0:
                return self._build_close_signal(
                    position,
                    reduce_ratio=0.25,
                    invalidation="Stop locked at +1R per rule",
                    reason="Taking 25% at 2R, move stop to 1R"
                )
            if r_multiple >= 1.0:
                return self._build_close_signal(
                    position,
                    reduce_ratio=0.5,
                    invalidation="Stop moved to breakeven",
                    reason="Taking 50% at 1R, stop to breakeven"
                )

        # 信号强化加仓
        if position.get('signal_strength') and position['signal_strength'] > 0.8 and r_multiple and r_multiple > 0.5:
            return self._build_add_signal(position, env)

        # 默认持有
        return self._build_hold_signal(position)

    def _build_close_signal(
        self,
        position: Dict[str, Any],
        reduce_ratio: float,
        invalidation: str,
        reason: str
    ) -> Dict[str, Any]:
        qty = max(position.get('quantity') or position.get('size') or 0, 0)
        action_qty = max(qty * reduce_ratio, 0.0)
        action_qty = float(round(action_qty, 10))
        if action_qty == 0:
            return {}

        return {
            'signal': 'close_position',
            'quantity': action_qty,
            'leverage': int(position.get('leverage') or 10),
            'profit_target': position.get('profit_target') or position.get('entry_price'),
            'stop_loss': position.get('stop_loss') or position.get('entry_price'),
            'invalidation_condition': invalidation,
            'confidence': float(position.get('confidence') or 0.7),
            'risk_usd': 0.0,
            'justification': reason
        }

    def _build_hold_signal(self, position: Dict[str, Any]) -> Dict[str, Any]:
        qty = max(position.get('quantity') or position.get('size') or 0, 0)
        return {
            'signal': 'hold',
            'quantity': float(round(qty, 10)),
            'leverage': int(position.get('leverage') or 10),
            'profit_target': position.get('profit_target') or 0.0,
            'stop_loss': position.get('stop_loss') or position.get('entry_price') or 0.0,
            'invalidation_condition': position.get('invalidation_condition') or "Stop invalidation not supplied",
            'confidence': float(position.get('confidence') or 0.7),
            'risk_usd': float(position.get('risk_usd') or 0.0),
            'justification': position.get('justification') or "Holding per plan, trend intact"
        }

    def _build_add_signal(self, position: Dict[str, Any], env: MarketEnvironment) -> Optional[Dict[str, Any]]:
        qty = max(position.get('quantity') or position.get('size') or 0, 0)
        if qty <= 0:
            return None
        add_amount = qty * min(PYRAMID_CONFIG['increment_pct'], 0.8)

        return {
            'signal': 'buy_to_enter' if position.get('side') == 'long' else 'sell_to_enter',
            'quantity': float(round(add_amount, 10)),
            'leverage': int(min(max((position.get('leverage') or 10) + 2, 5), 25)),
            'profit_target': position.get('profit_target') or position.get('entry_price'),
            'stop_loss': position.get('entry_price'),
            'invalidation_condition': "Add-on invalidated if price returns to entry",
            'confidence': float(min(position.get('confidence', 0.75) + 0.05, 0.95)),
            'risk_usd': float(position.get('risk_usd', 0) * 0.5),
            'justification': "Signal strengthening >0.8 with >0.5R in favor, pyramiding"
        }

    # ------------------------------------------------------------------ #
    # 新机会与仓位规模
    # ------------------------------------------------------------------ #
    def _evaluate_opportunity(
        self,
        opportunity: Dict[str, Any],
        env: MarketEnvironment,
        available_cash: float,
        initial_capital: float,
        existing_symbols: List[str]
    ) -> Optional[Dict[str, Any]]:
        symbol = opportunity.get('symbol')
        entry_price = opportunity.get('entry_price')
        direction = opportunity.get('direction', 'long')
        atr = opportunity.get('atr') or opportunity.get('atr_3')
        volume_ratio = opportunity.get('volume_ratio')
        funding_rate = opportunity.get('funding_rate')
        oi_change = opportunity.get('oi_change_pct')

        if not symbol or not entry_price or entry_price <= 0:
            return None

        if symbol in existing_symbols:
            # 若已经另有动作（如 close/hold），避免重复
            return None

        confidence = self._score_confidence(
            opportunity=opportunity,
            env=env,
            volume_ratio=volume_ratio,
            funding_rate=funding_rate,
            oi_change=oi_change
        )

        if confidence < 0.55:
            return None

        risk_fraction = self._map_confidence_to_risk(confidence)
        max_risk_fraction = min(0.15, risk_fraction)
        risk_usd = available_cash * max_risk_fraction

        # 保持现金储备
        if available_cash - risk_usd < initial_capital * 0.1:
            return None

        leverage = self._map_confidence_to_leverage(confidence)

        stop_distance = self._compute_stop_distance(opportunity, atr, confidence)
        if stop_distance <= 0:
            return None

        quantity = risk_usd / max(stop_distance * leverage, 1e-9)
        quantity = float(round(quantity, 8))
        if quantity <= 0:
            return None

        notional = quantity * entry_price * leverage
        limit = self._symbol_notional_limit(symbol, initial_capital)
        if limit and notional > limit:
            scale = limit / notional
            quantity *= scale
            risk_usd *= scale
            quantity = float(round(quantity, 8))
            risk_usd = float(round(risk_usd, 2))

        if quantity <= 0 or risk_usd <= 0:
            return None

        profit_target = self._compute_profit_target(entry_price, stop_distance, confidence, direction)
        stop_loss = entry_price - stop_distance if direction == 'long' else entry_price + stop_distance
        invalidation_condition = (
            f"Price closes {'below' if direction == 'long' else 'above'} {round(stop_loss, 4)} on 3m candle "
            f"or RSI/MACD signal fully reverses"
        )

        justification = opportunity.get('justification') or self._default_justification(
            opportunity, confidence, env
        )

        return {
            'signal': 'buy_to_enter' if direction == 'long' else 'sell_to_enter',
            'quantity': quantity,
            'leverage': leverage,
            'profit_target': float(round(profit_target, 6)),
            'stop_loss': float(round(stop_loss, 6)),
            'invalidation_condition': invalidation_condition,
            'confidence': float(round(confidence, 4)),
            'risk_usd': float(round(risk_usd, 2)),
            'justification': justification
        }

    def _score_confidence(
        self,
        opportunity: Dict[str, Any],
        env: MarketEnvironment,
        volume_ratio: Optional[float],
        funding_rate: Optional[float],
        oi_change: Optional[float]
    ) -> float:
        base = opportunity.get('confidence', 0.7)
        base += env.news_bias * 0.2

        if opportunity.get('signal_strength'):
            base = max(base, opportunity['signal_strength'])

        signal_factors = opportunity.get('factors', {})
        if volume_ratio and volume_ratio >= 2.0:
            base += 0.05
        if signal_factors.get('rsi_extreme'):
            base += 0.05
        if signal_factors.get('macd_spike'):
            base += 0.05
        if signal_factors.get('breakout_24h'):
            base += 0.05
        if signal_factors.get('funding_extreme'):
            base += 0.05
        if funding_rate and ((funding_rate > 0.02 and opportunity.get('direction') == 'short') or
                             (funding_rate < -0.02 and opportunity.get('direction') == 'long')):
            base += 0.05
        if oi_change and oi_change > 10:
            base += 0.03

        if env.btc_trend == 'bullish' and opportunity.get('trend_alignment', 'with_trend') == 'with_trend':
            base += 0.03
        if env.btc_trend == 'bearish' and opportunity.get('trend_alignment') == 'counter_trend':
            base -= 0.02

        if opportunity.get('data_complete') is False:
            base -= 0.1

        return float(max(0.0, min(0.99, base)))

    def _map_confidence_to_risk(self, confidence: float) -> float:
        if confidence >= 0.85:
            return 0.15
        if confidence >= 0.75:
            return 0.12
        if confidence >= 0.65:
            return 0.08
        return 0.06

    def _map_confidence_to_leverage(self, confidence: float) -> int:
        if confidence >= 0.85:
            return 23
        if confidence >= 0.75:
            return 18
        if confidence >= 0.65:
            return 13
        return 8

    def _symbol_notional_limit(self, symbol: str, initial_capital: float) -> Optional[float]:
        base = symbol.split('/')[0].upper() if '/' in symbol else ''.join([c for c in symbol if c.isalpha()]).upper()
        if base in CORE_SYMBOLS:
            return initial_capital * 0.5
        if base in MAJOR_SYMBOLS:
            return initial_capital * 0.4
        return initial_capital * 0.3

    def _compute_stop_distance(self, opportunity: Dict[str, Any], atr: Optional[float], confidence: float) -> float:
        atr = atr or opportunity.get('entry_price', 0) * 0.008
        volatility_state = opportunity.get('volatility_state', 'normal')
        multiplier = 1.0
        if volatility_state == 'high':
            multiplier = 1.2
        elif opportunity.get('strategy') == 'breakout':
            multiplier = 0.8
        return max(atr * multiplier, opportunity.get('entry_price', 0) * 0.005)

    def _compute_profit_target(self, entry: float, stop_distance: float, confidence: float, direction: str) -> float:
        ratio = 1.5
        if confidence >= 0.85:
            ratio = 2.8
        elif confidence >= 0.75:
            ratio = 2.0
        profit_distance = stop_distance * ratio
        if direction == 'long':
            return entry + profit_distance
        return entry - profit_distance

    def _default_justification(self, opportunity: Dict[str, Any], confidence: float, env: MarketEnvironment) -> str:
        fragments = []
        if opportunity.get('strategy') == 'breakout':
            fragments.append("24h breakout with 200% volume")
        if opportunity.get('strategy') == 'funding_arbitrage':
            fragments.append("Funding rate extreme >0.02%")
        if opportunity.get('strategy') == 'rsi_extreme':
            fragments.append("Extreme RSI reversal signal")
        if not fragments:
            fragments.append("Multi-signal confirmation per DeepSeek rules")
        fragments.append(f"confidence={confidence:.2f}")
        fragments.append(f"btc_trend={env.btc_trend}")
        return ", ".join(fragments)


_strategy_profile = StrategyProfile()
decision_engine = DeepSeekDecisionEngine(_strategy_profile, RISK_CONFIG)


def generate_trade_directives(market_state: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
    """
    暴露给策略控制器的高级接口，返回可直接序列化的交易指令字典。
    控制器可将输出转换为 JSON，以满足“标准化 nine-field schema” 的要求。
    """
    market_state = market_state or {}
    return decision_engine.generate_trade_directives(market_state)


# === 工具函数 ===
def _parse_timeframe_minutes(metadata: Optional[Dict[str, Any]]) -> int:
    """尝试从 metadata 推断单根K线的分钟数，默认 1 分钟。"""
    if not metadata:
        return DEFAULT_TIMEFRAME_MINUTES
    # 常见字段：timeframe, interval, timeframe_minutes...
    candidates = [
        metadata.get('timeframe'),
        metadata.get('interval'),
        metadata.get('timeframe_minutes'),
        metadata.get('tf'),
    ]
    for value in candidates:
        if value is None:
            continue
        if isinstance(value, (int, float)):
            minutes = max(int(value), 1)
            if minutes:
                return minutes
        if isinstance(value, str):
            value = value.strip().lower()
            unit = value[-1]
            try:
                num = float(value[:-1]) if unit.isalpha() else float(value)
            except ValueError:
                continue
            if unit == 'm' or not unit.isalpha():
                return max(int(num), 1)
            if unit == 'h':
                return max(int(num * 60), 1)
            if unit == 'd':
                return max(int(num * 24 * 60), 1)
    return DEFAULT_TIMEFRAME_MINUTES


def _rolling_feature(series: pd.Series, window: int, method: str = 'mean') -> pd.Series:
    if window <= 1:
        return series
    if method == 'mean':
        return series.rolling(window=window, min_periods=1).mean()
    if method == 'max':
        return series.rolling(window=window, min_periods=1).max()
    if method == 'min':
        return series.rolling(window=window, min_periods=1).min()
    if method == 'std':
        return series.rolling(window=window, min_periods=1).std(ddof=0)
    return series


def _normalize(series: pd.Series) -> pd.Series:
    rolling_min = series.rolling(200, min_periods=20).min()
    rolling_max = series.rolling(200, min_periods=20).max()
    denom = (rolling_max - rolling_min).replace(0, np.nan)
    normalized = (series - rolling_min) / denom
    return normalized.clip(0, 1).fillna(0.5)


def _calc_momentum_score(dataframe: pd.DataFrame) -> pd.Series:
    components = []
    if 'macd_hist' in dataframe:
        components.append(dataframe['macd_hist'] / (dataframe['close'].abs() + 1e-9))
    if 'rsi_fast' in dataframe:
        components.append((dataframe['rsi_fast'] - 50) / 50)
    if 'vol_ratio' in dataframe:
        components.append(dataframe['vol_ratio'] - 1)
    if not components:
        return pd.Series(0, index=dataframe.index)
    score = sum(components) / len(components)
    return score.clip(-2, 2)


# === 指标与信号 ===
def populate_indicators(dataframe: pd.DataFrame, metadata: Dict[str, Any]):
    """
    填充多时间框架指标
    """
    if dataframe.empty:
        return dataframe

    close = dataframe['close'].values.astype(np.float64)
    high = dataframe['high'].values.astype(np.float64)
    low = dataframe['low'].values.astype(np.float64)
    volume = dataframe['volume'].values.astype(np.float64)

    dataframe['ema_fast'] = talib.EMA(close, timeperiod=21)
    dataframe['ema_mid'] = talib.EMA(close, timeperiod=55)
    dataframe['ema_trend'] = talib.EMA(close, timeperiod=144)

    dataframe['rsi'] = talib.RSI(close, timeperiod=14)
    dataframe['rsi_fast'] = talib.RSI(close, timeperiod=7)
    dataframe['rsi_slow'] = talib.RSI(close, timeperiod=28)

    macd, macd_signal, macd_hist = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
    dataframe['macd'] = macd
    dataframe['macd_signal'] = macd_signal
    dataframe['macd_hist'] = macd_hist

    dataframe['atr'] = talib.ATR(high, low, close, timeperiod=14)
    dataframe['atr_pct'] = dataframe['atr'] / dataframe['close']

    dataframe['bb_upper'], dataframe['bb_middle'], dataframe['bb_lower'] = talib.BBANDS(
        close, timeperiod=20, nbdevup=2.5, nbdevdn=2.5, matype=0
    )

    dataframe['volume_ma'] = pd.Series(volume).rolling(window=34, min_periods=1).mean()
    dataframe['vol_ratio'] = (dataframe['volume'] / dataframe['volume_ma']).replace([np.inf, -np.inf], np.nan)

    # 多时间框架特征（通过不同窗口的滚动统计模拟）
    base_minutes = _parse_timeframe_minutes(metadata)
    short_window = max(int((SHORT_WINDOW_MINUTES / base_minutes) or 1), 3)
    mid_window = max(int((MID_WINDOW_MINUTES / base_minutes) or 1), 50)

    dataframe['short_high'] = _rolling_feature(dataframe['high'], short_window, 'max')
    dataframe['short_low'] = _rolling_feature(dataframe['low'], short_window, 'min')
    dataframe['mid_high'] = _rolling_feature(dataframe['high'], mid_window, 'max')
    dataframe['mid_low'] = _rolling_feature(dataframe['low'], mid_window, 'min')
    dataframe['mid_trend_mean'] = _rolling_feature(dataframe['close'], mid_window, 'mean')
    dataframe['mid_trend_std'] = _rolling_feature(dataframe['close'], mid_window, 'std')

    dataframe['volatility_rank'] = _normalize(dataframe['atr_pct'])
    dataframe['momentum_score'] = _calc_momentum_score(dataframe)

    dataframe['short_breakout'] = dataframe['close'] >= dataframe['short_high'].shift(1)
    dataframe['short_breakdown'] = dataframe['close'] <= dataframe['short_low'].shift(1)
    dataframe['mid_breakout'] = dataframe['close'] >= dataframe['mid_high'].shift(1)
    dataframe['mid_breakdown'] = dataframe['close'] <= dataframe['mid_low'].shift(1)

    dataframe['extreme_rsi_long'] = dataframe['rsi_fast'] < 18
    dataframe['extreme_rsi_short'] = dataframe['rsi_fast'] > 82

    return dataframe


def populate_entry_trend_long(dataframe: pd.DataFrame, metadata: Dict[str, Any]):
    """
    Long 入场逻辑：短期突破 + 中期趋势向上 + 动量增强
    """
    conditions = [
        dataframe['ema_fast'] > dataframe['ema_mid'],
        dataframe['ema_mid'] > dataframe['ema_trend'],
        dataframe['momentum_score'] > 0.25,
        dataframe['volatility_rank'] > 0.3,
        (dataframe['short_breakout'] | dataframe['extreme_rsi_long']),
        dataframe['vol_ratio'] > 1.1,
    ]
    entry = pd.Series(True, index=dataframe.index)
    for condition in conditions:
        entry &= condition.fillna(False)
    return entry


def populate_entry_trend_short(dataframe: pd.DataFrame, metadata: Dict[str, Any]):
    """
    Short 入场逻辑：短期跌破 + 中期转弱 + 动量下行
    """
    conditions = [
        dataframe['ema_fast'] < dataframe['ema_mid'],
        dataframe['ema_mid'] < dataframe['ema_trend'],
        dataframe['momentum_score'] < -0.25,
        dataframe['volatility_rank'] > 0.3,
        (dataframe['short_breakdown'] | dataframe['extreme_rsi_short']),
        dataframe['vol_ratio'] > 1.1,
    ]
    entry = pd.Series(True, index=dataframe.index)
    for condition in conditions:
        entry &= condition.fillna(False)
    return entry


def populate_exit_trend_long(dataframe: pd.DataFrame, metadata: Dict[str, Any]):
    """激进策略通常交由 custom_exit 管理，这里提供基础防守"""
    exit_conditions = [
        dataframe['close'] < dataframe['ema_fast'],
        dataframe['momentum_score'] < -0.1,
        dataframe['rsi_fast'] < 35,
    ]
    exit_signal = pd.Series(False, index=dataframe.index)
    for condition in exit_conditions:
        exit_signal |= condition.fillna(False)
    return exit_signal


def populate_exit_trend_short(dataframe: pd.DataFrame, metadata: Dict[str, Any]):
    exit_conditions = [
        dataframe['close'] > dataframe['ema_fast'],
        dataframe['momentum_score'] > 0.1,
        dataframe['rsi_fast'] > 65,
    ]
    exit_signal = pd.Series(False, index=dataframe.index)
    for condition in exit_conditions:
        exit_signal |= condition.fillna(False)
    return exit_signal


# === 运行期回调 ===
def before_loop(symbols: List[str]):
    print(f"[激进量化策略] 启动交易循环，可交易对数量: {len(symbols)}")
    if symbols:
        preview = ", ".join(symbols[:5])
        print(f"[激进量化策略] 关注标的: {preview}{'...' if len(symbols) > 5 else ''}")


def after_loop(symbols: List[str]):
    print("[激进量化策略] 交易循环结束，等待下一轮数据刷新")


def order_filled(order, exchange_order):
    symbol = exchange_order.get('symbol')
    price = exchange_order.get('price')
    filled = exchange_order.get('filled')
    print(f"[激进量化策略] 订单 {order.id} 成交: {symbol}, 方向: {order.side}, 数量: {filled}, 价格: {price}")


# === 入场过滤 ===
def entry_conditions(symbol: str, analysis_result: Dict[str, Any]):
    """
    附加风控：限制在极端低波动或流动性不足时入场
    """
    if not analysis_result:
        return True
    volatility_rank = analysis_result.get('volatility_rank')
    if volatility_rank is not None and volatility_rank < 0.2:
        return False
    spread = analysis_result.get('spread_pct')
    if spread and spread > 0.2:  # 点差过大
        return False
    return True


# === 自定义退出与仓位管理 ===
def custom_exit(position, current_price: float):
    """
    激进风险控制：分级止盈 + 移动止盈 + 动态止损
    """
    if not position or not position.entry_price or current_price is None or current_price <= 0:
        return None

    # 计算浮动盈亏
    if position.side == 'long':
        roi = (current_price - position.entry_price) / position.entry_price
    else:
        roi = (position.entry_price - current_price) / position.entry_price

    # 记录最高/最低盈亏用于移动止盈
    peak_attr = '_roi_peak'
    floor_attr = '_roi_floor'
    peak = getattr(position, peak_attr, roi)
    floor = getattr(position, floor_attr, roi)

    if roi > peak:
        setattr(position, peak_attr, roi)
        peak = roi
    if roi < floor:
        setattr(position, floor_attr, roi)
        floor = roi

    # 硬止损
    if roi <= RISK_CONFIG['max_loss_pct']:
        return {
            'price': current_price,
            'reason': 'hard_stop_loss',
            'reduce_percent': 1.0
        }

    # 软止损：亏损超过 soft_stop_pct 且未见快速修复
    if roi <= RISK_CONFIG['soft_stop_pct']:
        if peak - roi < 0.03:  # 亏损阶段没有明显修复
            return {
                'price': current_price,
                'reason': 'soft_stop_loss',
                'reduce_percent': 1.0
            }

    # 分级止盈
    cumulative = 0.0
    for level, reduce in zip(RISK_CONFIG['tp_levels'], RISK_CONFIG['tp_reduce']):
        tag = f'_tp_{level:.2f}_done'
        if roi >= level and not getattr(position, tag, False):
            setattr(position, tag, True)
            return {
                'price': current_price,
                'reason': f'take_profit_{int(level*100)}bp',
                'reduce_percent': min(1.0 - cumulative, reduce)
            }
        cumulative += reduce

    # 移动止盈（回吐超过 trailing_buffer）
    if roi > 0.05 and (peak - roi) >= RISK_CONFIG['trailing_buffer']:
        return {
            'price': current_price,
            'reason': 'trailing_stop',
            'reduce_percent': 1.0
        }

    return None


def adjust_position(position):
    """
    动态加仓（金字塔）或减仓
    """
    if not position or not position.entry_price or position.entry_price <= 0:
        return {'should_adjust': False, 'amount': 0}

    current_price = position.current_price
    if not current_price:
        return {'should_adjust': False, 'amount': 0}

    if position.side == 'long':
        roi = (current_price - position.entry_price) / position.entry_price
    else:
        roi = (position.entry_price - current_price) / position.entry_price

    # 记录当前金字塔层级
    layers_attr = '_pyramid_layers'
    layers = getattr(position, layers_attr, 0)

    # 浮盈加仓
    threshold = PYRAMID_CONFIG['step_roi'] * (layers + 1)
    if roi > threshold and layers < PYRAMID_CONFIG['max_layers']:
        setattr(position, layers_attr, layers + 1)
        amount = max(position.size * PYRAMID_CONFIG['increment_pct'], 0)
        if amount > 0:
            return {
                'should_adjust': True,
                'amount': amount,
                'reason': 'pyramid_add'
            }

    # 浮亏主动减仓（保护本金）
    if roi < -0.05:
        reduce_amount = max(position.size * 0.25, 0)
        if reduce_amount > 0:
            return {
                'should_adjust': True,
                'amount': -reduce_amount,
                'reason': 'defensive_reduce'
            }

    return {'should_adjust': False, 'amount': 0}

