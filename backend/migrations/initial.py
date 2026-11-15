from sqlalchemy import inspect, text
from src.config.database import engine, Base
from src import models

def _existing_columns(conn, table):
    inspector = inspect(conn)
    try:
        return {c['name'] for c in inspector.get_columns(table)}
    except Exception:
        return set()

# 存量库的增量补丁：表已存在时补齐销毁功能所需列，保证中断升级可重复执行
_PATCHES = {
    'datasets': [
        ('sealed', "BOOLEAN NOT NULL DEFAULT FALSE"),
    ],
}

def migrate():
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for table, columns in _PATCHES.items():
            present = _existing_columns(conn, table)
            if not present:
                continue
            for name, ddl in columns:
                if name not in present:
                    conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}'))

if __name__ == '__main__':
    migrate()
