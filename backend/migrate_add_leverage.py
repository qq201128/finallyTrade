"""
数据库迁移脚本：为 positions 表添加 leverage 字段
"""
import sqlite3
import os
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from app.core.config import settings

def migrate():
    """添加 leverage 字段到 positions 表"""
    # 从 DATABASE_URL 中提取数据库文件路径
    db_url = settings.DATABASE_URL
    if db_url.startswith('sqlite:///'):
        db_path = db_url.replace('sqlite:///', '')
    else:
        db_path = 'trading_system.db'
    
    if not os.path.exists(db_path):
        print(f"[ERROR] 数据库文件不存在: {db_path}")
        return False
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 检查 leverage 字段是否已存在
        cursor.execute("PRAGMA table_info(positions)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'leverage' in columns:
            print(f"[INFO] leverage 字段已存在，跳过迁移")
            conn.close()
            return True
        
        # 添加 leverage 字段
        print(f"[INFO] 正在添加 leverage 字段到 positions 表...")
        cursor.execute("ALTER TABLE positions ADD COLUMN leverage INTEGER DEFAULT 1")
        conn.commit()
        
        print(f"[OK] 成功添加 leverage 字段")
        conn.close()
        return True
        
    except Exception as e:
        print(f"[ERROR] 迁移失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("=" * 50)
    print("数据库迁移：添加 leverage 字段")
    print("=" * 50)
    success = migrate()
    if success:
        print("\n[OK] 迁移完成！")
    else:
        print("\n[ERROR] 迁移失败！")
        sys.exit(1)

