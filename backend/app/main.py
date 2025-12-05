"""
FastAPI应用主入口
"""
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.middleware.base import BaseHTTPMiddleware
from app.core.database import engine, Base, SessionLocal
from app.core.config import settings
from app.core.logging_config import setup_logging
from app.api import auth, strategies, trades, websocket
import logging
import time

# 配置日志（包括文件输出）
setup_logging()
logger = logging.getLogger(__name__)

# 创建数据库表
Base.metadata.create_all(bind=engine)

# 创建FastAPI应用
app = FastAPI(
    title=settings.APP_NAME,
    description="多策略多用户永续合约交易系统",
    version="1.0.0"
)

# 添加GZip压缩中间件（在CORS之前）
app.add_middleware(GZipMiddleware, minimum_size=1000)  # 只压缩大于1KB的响应

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应该限制具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 响应缓存中间件（为GET请求添加缓存头）
class CacheControlMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        
        # 为GET请求添加缓存头（根据路径决定缓存时间）
        if request.method == "GET":
            path = request.url.path
            
            # 静态数据可以缓存更久
            if "/api/strategies/" in path and "/user" not in path:
                response.headers["Cache-Control"] = "public, max-age=300"  # 5分钟
            # 用户数据缓存时间较短
            elif "/api/trades/positions" in path or "/api/trades/orders" in path:
                response.headers["Cache-Control"] = "public, max-age=10"  # 10秒
            # 其他API响应不缓存
            else:
                response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
                response.headers["Pragma"] = "no-cache"
                response.headers["Expires"] = "0"
        
        return response

app.add_middleware(CacheControlMiddleware)

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

    # 自动扫描并注册策略文件到数据库
    try:
        await auto_register_strategies()
    except Exception as e:
        logger.error(f"自动注册策略失败: {e}", exc_info=True)

    # 恢复所有启用的策略
    try:
        from app.services.trading_scheduler import start_trading_scheduler, start_thread_monitor
        logger.info("正在恢复所有启用的策略...")
        start_trading_scheduler()

        # 启动线程监控器，定期检查线程健康状态
        start_thread_monitor()
    except Exception as e:
        logger.error(f"恢复策略失败: {e}", exc_info=True)


async def auto_register_strategies():
    """
    自动扫描策略目录，将新策略注册到数据库

    这样每次启动时会自动发现新的策略文件，无需手动运行 init_db.py
    策略描述从策略文件的 docstring 中自动提取
    """
    import os
    import ast
    from app.models.strategy import Strategy

    strategies_dir = "./app/strategies"
    if not os.path.exists(strategies_dir):
        logger.warning(f"策略目录不存在: {strategies_dir}")
        return

    strategy_files = [f for f in os.listdir(strategies_dir) if f.endswith('.py') and f != '__init__.py' and not f.startswith('base_')]

    if not strategy_files:
        logger.info("未找到策略文件")
        return

    db = SessionLocal()
    try:
        registered_count = 0
        updated_count = 0

        for file in strategy_files:
            strategy_name = file.replace('.py', '')
            file_path = os.path.abspath(os.path.join(strategies_dir, file))

            # 从策略文件中提取 docstring 作为描述
            description = extract_docstring_from_file(file_path) or f"策略文件: {file}"

            # 检查策略是否已存在
            existing = db.query(Strategy).filter(Strategy.name == strategy_name).first()
            if existing:
                # 更新文件路径和描述（以防文件内容变化）
                changed = False
                if existing.file_path != file_path:
                    existing.file_path = file_path
                    changed = True
                if existing.description != description:
                    existing.description = description
                    changed = True
                if changed:
                    updated_count += 1
            else:
                # 创建新策略
                strategy = Strategy(
                    name=strategy_name,
                    description=description,
                    file_path=file_path,
                    is_active=True,
                    config={}
                )
                db.add(strategy)
                registered_count += 1
                logger.info(f"[自动注册] 新策略: {strategy_name}")

        db.commit()

        if registered_count > 0 or updated_count > 0:
            logger.info(f"策略自动注册完成: 新增 {registered_count} 个, 更新 {updated_count} 个")
        else:
            logger.debug(f"策略检查完成: {len(strategy_files)} 个策略均已注册")
    except Exception as e:
        logger.error(f"自动注册策略失败: {e}", exc_info=True)
        db.rollback()
    finally:
        # 使用 scoped_session 的 remove() 方法清理线程本地会话
        SessionLocal.remove()


def extract_docstring_from_file(file_path: str) -> str:
    """
    从 Python 文件中提取模块级别的 docstring

    Args:
        file_path: 策略文件路径

    Returns:
        docstring 的第一段（简短描述），如果没有则返回 None
    """
    import ast

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            source = f.read()

        # 使用 AST 解析文件，提取模块 docstring
        tree = ast.parse(source)
        docstring = ast.get_docstring(tree)

        if docstring:
            # 取第一段作为简短描述（遇到空行截止）
            lines = docstring.strip().split('\n')
            first_paragraph = []
            for line in lines:
                stripped = line.strip()
                if stripped == '':
                    break
                first_paragraph.append(stripped)

            if first_paragraph:
                return ' '.join(first_paragraph)

        return None
    except Exception as e:
        logger.debug(f"提取 docstring 失败 ({file_path}): {e}")
        return None


@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭事件"""
    logger.info("正在关闭应用...")
    
    # 停止所有策略和监控器
    try:
        from app.services.trading_scheduler import stop_trading_scheduler, stop_thread_monitor
        stop_thread_monitor()
        stop_trading_scheduler()
    except Exception as e:
        logger.error(f"停止策略失败: {e}", exc_info=True)
    
    logger.info("应用关闭")

