from sqlalchemy import String, JSON, Double, ForeignKey, Boolean, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base
class DestructionOrder(Base):
    __tablename__ = 'destruction_orders'
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    dataset_id: Mapped[int] = mapped_column(Integer, index=True)
    dataset_name: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(20), default='sealed', index=True)
    # 只保存各类型对象的计数，不保存任何客流明细内容
    counts: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_by_email: Mapped[str] = mapped_column(String(150))
    sealed_at: Mapped[float] = mapped_column(Double)
    updated_at: Mapped[float] = mapped_column(Double)
    finished_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default='')
class DestructionItem(Base):
    __tablename__ = 'destruction_items'
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey('destruction_orders.id'), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    ref_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 仅保留文件名/相对路径，用于文件清除重试；不含客流数据内容
    target: Mapped[str] = mapped_column(String(255), default='')
    status: Mapped[str] = mapped_column(String(20), default='pending', index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str] = mapped_column(String(500), default='')
    updated_at: Mapped[float] = mapped_column(Double)
