"""批次销毁：封存 → 拦截 → 逐项永久清除。

设计约束：
- 发起幂等：同一批次重复发起沿用同一条销毁记录，绝不触碰其他批次。
- 中断可恢复：每个清除对象是一条 destruction_item，失败保留状态待重试；
  只有数据行与归档文件全部清除后，销毁单才进入 destroyed。
- 凭证最小化：销毁单只保存编号、计数、时间、操作人与文件名，不保存客流明细。
"""
import os
import time

from fastapi import HTTPException
from sqlalchemy import select

from src.config.settings import ARTIFACT_DIR
from src.models import (
    Dataset, Job, Report, Delivery,
    DestructionOrder, DestructionItem,
)
from src.services.audit import record

# 清除顺序：先归档文件，再分发记录/计划/任务，最后才删除批次行本身
KIND_ORDER = ['file', 'delivery', 'report', 'job', 'dataset']
ACTIVE_ORDER_STATUSES = ('sealed', 'clearing', 'failed')


def _find_order(db, dataset_id):
    return db.scalar(
        select(DestructionOrder)
        .where(DestructionOrder.dataset_id == dataset_id)
        .order_by(DestructionOrder.id.desc())
    )


def _job_ids(db, dataset_id):
    return list(db.scalars(select(Job.id).where(Job.dataset_id == dataset_id)))


def _report_ids(db, job_ids):
    if not job_ids:
        return []
    return list(db.scalars(select(Report.id).where(Report.job_id.in_(job_ids))))


def _deliveries(db, report_ids):
    if not report_ids:
        return []
    return list(db.scalars(select(Delivery).where(Delivery.report_id.in_(report_ids))))


def initiate(db, dataset_id, user):
    """负责人发起批次销毁；同批次重复发起返回同一销毁记录。

    返回 (销毁单, 是否新建)，便于路由区分 201/200。
    """
    existing = _find_order(db, dataset_id)
    if existing:
        return existing, False
    d = db.get(Dataset, dataset_id)
    if not d:
        raise HTTPException(404, '数据批次不存在')
    if d.sealed:
        # 理论上不会走到：封存时必然已建单，防御性兜底
        raise HTTPException(409, '该批次已在销毁流程中')

    now = time.time()
    job_ids = _job_ids(db, dataset_id)
    report_ids = _report_ids(db, job_ids)
    deliveries = _deliveries(db, report_ids)

    # 第一步：立即封存批次，并拦截所有在途分析与分发
    d.sealed = True
    for jid in job_ids:
        j = db.get(Job, jid)
        if j and j.status in ('queued', 'running'):
            j.status = 'failed'
            j.error = '数据批次已封存销毁，任务终止且结果不得写回'
            j.finished_at = now
    for rid in report_ids:
        r = db.get(Report, rid)
        if r:
            r.enabled = False

    code = f'DEST-{int(now):010d}-{dataset_id}'
    order = DestructionOrder(
        code=code, dataset_id=dataset_id, dataset_name=d.name,
        status='sealed', counts={}, created_by=user.id,
        created_by_email=user.email, sealed_at=now, updated_at=now,
    )
    db.add(order)
    db.flush()

    def add_item(kind, ref_id=None, target=''):
        db.add(DestructionItem(
            order_id=order.id, kind=kind, ref_id=ref_id, target=target,
            status='pending', attempts=0, updated_at=now,
        ))

    # 归档文件：每次分发产生 CSV 与同名 JSON 两个文件
    file_targets = []
    for dl in deliveries:
        for suffix in ('', '.json'):
            file_targets.append(dl.filename + suffix)
    for target in file_targets:
        add_item('file', target=target)
    for dl in deliveries:
        add_item('delivery', ref_id=dl.id)
    for rid in report_ids:
        add_item('report', ref_id=rid)
    for jid in job_ids:
        add_item('job', ref_id=jid)
    add_item('dataset', ref_id=dataset_id)

    order.counts = {
        'dataset': 1,
        'job': len(job_ids),
        'report': len(report_ids),
        'delivery': len(deliveries),
        'file': len(file_targets),
    }
    record(db, user.email, 'destruction.initiate', {
        'order': order.id, 'code': code, 'dataset_id': dataset_id,
        'counts': order.counts,
    })
    db.flush()
    return order, True


def _lock_order(db, order_id):
    order = db.get(DestructionOrder, order_id)
    if not order or order.status == 'destroyed':
        return None
    try:
        db.refresh(order, with_for_update={'skip_locked': True})
    except Exception:
        # SQLite 等不支持行锁的后端依靠单 worker 与短事务保证
        db.refresh(order)
    return order


def _clear_file(item):
    path = os.path.join(ARTIFACT_DIR, item.target)
    if not os.path.exists(path):
        return True, ''  # 文件不存在视为已清除，保证重试幂等
    try:
        os.remove(path)
        return True, ''
    except OSError as e:
        return False, f'文件清除失败：{type(e).__name__} {e}'[:480]


def _clear_row(db, kind, ref_id):
    model = {'delivery': Delivery, 'report': Report,
             'job': Job, 'dataset': Dataset}[kind]
    row = db.get(model, ref_id) if ref_id is not None else None
    if row is None:
        return True, ''  # 已被清除，幂等
    try:
        db.delete(row)
        db.flush()
        return True, ''
    except Exception as e:
        return False, f'{kind} 清除失败：{type(e).__name__} {e}'[:480]


def process_order(db, order_id):
    """推进一张销毁单；可被 worker 周期性重入调用。"""
    order = _lock_order(db, order_id)
    if order is None:
        return None
    items = list(db.scalars(
        select(DestructionItem)
        .where(DestructionItem.order_id == order.id)
    ))
    rank = {k: i for i, k in enumerate(KIND_ORDER)}
    items.sort(key=lambda it: (rank.get(it.kind, 99), it.id))

    now = time.time()
    touched = False
    for item in items:
        if item.status == 'cleared':
            continue
        # 严格分阶段：前一阶段还有未清除项时，不删除后续数据行
        stage = rank[item.kind]
        blocked = any(
            rank.get(i.kind, 99) < stage and i.status != 'cleared'
            for i in items
        )
        if blocked:
            break
        item.attempts += 1
        item.updated_at = now
        if item.kind == 'file':
            ok, err = _clear_file(item)
        else:
            ok, err = _clear_row(db, item.kind, item.ref_id)
        if ok:
            item.status = 'cleared'
            item.last_error = ''
        else:
            item.status = 'failed'
            item.last_error = err
            order.last_error = err
        touched = True
        db.flush()

    remaining = [i for i in items if i.status != 'cleared']
    if not remaining:
        order.status = 'destroyed'
        order.finished_at = time.time()
        order.last_error = ''
        record(db, 'worker', 'destruction.destroyed',
               {'order': order.id, 'code': order.code,
                'counts': order.counts})
    elif any(i.status == 'failed' for i in remaining):
        order.status = 'failed'
    elif touched:
        order.status = 'clearing'
    order.updated_at = time.time()
    db.flush()
    return order


def process_pending(db):
    """Worker 每轮调用：推进所有未完成销毁单，失败项自动留待下轮重试。"""
    rows = db.scalars(
        select(DestructionOrder.id)
        .where(DestructionOrder.status.in_(ACTIVE_ORDER_STATUSES))
    ).all()
    for order_id in rows:
        process_order(db, order_id)
    db.commit()


def retry(db, order_id, user):
    order = db.get(DestructionOrder, order_id)
    if not order:
        raise HTTPException(404, '销毁记录不存在')
    if order.status == 'destroyed':
        return order
    reset = 0
    for item in db.scalars(select(DestructionItem)
                           .where(DestructionItem.order_id == order_id,
                                  DestructionItem.status == 'failed')):
        item.status = 'pending'
        item.updated_at = time.time()
        reset += 1
    if order.status == 'failed':
        order.status = 'clearing'
    order.updated_at = time.time()
    record(db, user.email, 'destruction.retry',
           {'order': order.id, 'reset_items': reset})
    db.commit()
    # 立即尝试一轮，仍失败则继续保留待重试状态
    process_order(db, order_id)
    db.commit()
    return order
