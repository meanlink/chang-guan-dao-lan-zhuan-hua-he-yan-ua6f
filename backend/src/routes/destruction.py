from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from src.config.database import get_db
from src.middlewares.auth import current_user, admin_only
from src.models import DestructionOrder, DestructionItem
from src.schemas.destruction import DestructionInitiate
from src.services import destruction
from src.services.audit import record
from src.utils.serialization import destruction_order_dict

router = APIRouter(prefix='/destructions')


@router.get('')
def listing(db=Depends(get_db), u=Depends(current_user)):
    orders = db.scalars(
        select(DestructionOrder).order_by(DestructionOrder.id.desc())
    ).all()
    items = {o.id: list(db.scalars(
        select(DestructionItem)
        .where(DestructionItem.order_id == o.id)
        .order_by(DestructionItem.id)
    )) for o in orders}
    return [destruction_order_dict(o, items[o.id]) for o in orders]


@router.post('')
def initiate(data: DestructionInitiate, response: Response,
             db=Depends(get_db), u=Depends(admin_only)):
    # 重复发起沿用同一销毁记录：新建 201，复用既有单 200
    o, created = destruction.initiate(db, data.dataset_id, u)
    response.status_code = 201 if created else 200
    db.commit()
    items = list(db.scalars(
        select(DestructionItem).where(DestructionItem.order_id == o.id)
    ))
    return destruction_order_dict(o, items)


@router.get('/{id}')
def detail(id: int, db=Depends(get_db), u=Depends(current_user)):
    o = db.get(DestructionOrder, id)
    if not o:
        from fastapi import HTTPException
        raise HTTPException(404, '销毁记录不存在')
    items = list(db.scalars(
        select(DestructionItem)
        .where(DestructionItem.order_id == o.id)
        .order_by(DestructionItem.id)
    ))
    return destruction_order_dict(o, items)


@router.post('/{id}/retry')
def retry(id: int, db=Depends(get_db), u=Depends(admin_only)):
    o = destruction.retry(db, id, u)
    items = list(db.scalars(
        select(DestructionItem)
        .where(DestructionItem.order_id == o.id)
        .order_by(DestructionItem.id)
    ))
    return destruction_order_dict(o, items)
