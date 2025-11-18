"""
启动脚本
"""
import uvicorn
from app.main import app
from app.services.trading_scheduler import start_trading_scheduler

if __name__ == "__main__":
    # 启动交易调度器
    start_trading_scheduler()
    
    # 启动FastAPI应用
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )

