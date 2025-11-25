"""
简单监控模块：支持指标采样与降级日志
"""
import logging
import random
from time import perf_counter
from typing import Dict, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


class MonitoringClient:
    def __init__(self):
        self.enabled = settings.MONITORING_ENABLED
        self.namespace = settings.MONITORING_NAMESPACE
        self.sample_rate = max(0.0, min(1.0, settings.MONITORING_SAMPLE_RATE))

    def _should_sample(self) -> bool:
        if not self.enabled:
            return False
        if self.sample_rate >= 1.0:
            return True
        return random.random() <= self.sample_rate

    def record_event(self, name: str, value: float = 1.0, tags: Optional[Dict[str, str]] = None):
        if not self._should_sample():
            return
        tag_str = ", ".join([f"{k}={v}" for k, v in (tags or {}).items()])
        logger.info(f"[metrics] {self.namespace}.{name} value={value} {tag_str}")

    def record_latency(self, name: str, duration: float, tags: Optional[Dict[str, str]] = None):
        if not self._should_sample():
            return
        tag_str = ", ".join([f"{k}={v}" for k, v in (tags or {}).items()])
        logger.info(f"[metrics] {self.namespace}.{name}.latency duration={duration:.4f}s {tag_str}")

    def time_block(self, name: str, tags: Optional[Dict[str, str]] = None):
        """
        用作上下文管理器：
        with monitoring.time_block("exchange.fetch", {"exchange": "binance"}):
            ...
        """

        class _TimerCtx:
            def __enter__(self_inner):
                self_inner.start = perf_counter()

            def __exit__(self_inner, exc_type, exc, tb):
                duration = perf_counter() - self_inner.start
                self.record_latency(name, duration, tags)

        return _TimerCtx()


monitoring = MonitoringClient()




