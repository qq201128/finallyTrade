"""
FastAPI应用主入口
"""
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from app.core.database import engine, Base
from app.core.config import settings
from app.api import auth, strategies, trades, websocket
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 创建数据库表
Base.metadata.create_all(bind=engine)

# 创建FastAPI应用
app = FastAPI(
    title=settings.APP_NAME,
    description="多策略多用户永续合约交易系统",
    version="1.0.0"
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应该限制具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 添加请求验证异常处理
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """处理请求验证错误"""
    errors = []
    for error in exc.errors():
        field = ".".join(str(loc) for loc in error["loc"] if loc != "body")
        errors.append({
            "field": field,
            "message": error["msg"],
            "type": error["type"]
        })
    logger.warning(f"请求验证失败: {request.url.path} - {errors}")
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "detail": "Validation error",
            "errors": errors
        }
    )

# 注册路由
app.include_router(auth.router)
app.include_router(strategies.router)
app.include_router(trades.router)
app.include_router(websocket.router)


@app.get("/")
async def root():
    """根路径"""
    return {"message": "Trading System API", "version": "1.0.0"}


@app.on_event("startup")
async def startup_event():
    """应用启动事件"""
    logger.info("应用启动成功")
    
    # 恢复所有启用的策略
    try:
        from app.services.trading_scheduler import start_trading_scheduler
        logger.info("正在恢复所有启用的策略...")
        start_trading_scheduler()
    except Exception as e:
        logger.error(f"恢复策略失败: {e}", exc_info=True)


@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭事件"""
    logger.info("正在关闭应用...")
    
    # 停止所有策略
    try:
        from app.services.trading_scheduler import stop_trading_scheduler
        stop_trading_scheduler()
    except Exception as e:
        logger.error(f"停止策略失败: {e}", exc_info=True)
    
    logger.info("应用关闭")

