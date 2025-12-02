"""
启动脚本
"""
import uvicorn
from app.main import app
# 注意：start_trading_scheduler 已在 app/main.py 的 startup_event 中调用

if __name__ == "__main__":
    # 启动FastAPI应用
    # 排除日志目录和数据库文件，避免文件监控触发过多重载
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_excludes=["logs/*", "*.db", "*.sqlite", "__pycache__/*"]
    )

