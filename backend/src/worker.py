import time, json, logging
from pathlib import Path
from sqlalchemy import select
from redis import Redis
from src.config.database import Session
from src.config.settings import REDIS_URL
from src.models import Job, Dataset, Report
from src.services.business import analyze
from src.services.reports import deliver
from src.services.destruction import process_pending
from src.services.audit import record
logging.basicConfig(level=logging.INFO)
def execute(job_id):
    with Session() as db:
        j=db.get(Job,job_id)
        if not j or j.status!='queued':return
        d=db.get(Dataset,j.dataset_id)
        if d is None or d.sealed:
            # 批次已封存或已销毁：即使任务晚完成，也绝不把结果写回
            j.status='failed';j.error='数据批次已封存销毁，结果禁止写回'
            j.finished_at=time.time()
            record(db,'worker','job.blocked',{'id':j.id})
            db.commit();return
        j.status='running'; db.commit()
        try:
            result=analyze(d.records,j.params)
            json.dumps(result,allow_nan=False)
            # 计算期间可能并发封存：提交前再检查一次，封存即丢弃结果
            db.refresh(d)
            if d.sealed:
                j.status='failed';j.error='数据批次封存在先，结果禁止写回'
                j.finished_at=time.time()
                record(db,'worker','job.blocked',{'id':j.id})
            else:
                j.result=result;j.status='completed';j.finished_at=time.time()
                record(db,'worker','job.completed',{'id':j.id})
        except Exception as e:
            logging.exception('Analysis failed')
            j.status='failed';j.error=str(e)[:990];j.finished_at=time.time()
            record(db,'worker','job.failed',{'id':j.id,'error':j.error})
        db.commit()
def tick():
    with Session() as db:
        queued=list(db.scalars(select(Job.id).where(Job.status=='queued').limit(3)))
    for job_id in queued:execute(job_id)
    with Session() as db:
        for r in db.scalars(select(Report).where(Report.enabled==True,Report.next_run<=time.time())):
            d=deliver(db,r)
            if d:record(db,'worker','report.delivered',{'id':r.id,'delivery':d.id})
        db.commit()
        # 推进销毁：失败项保留待下轮重试，全部清除后才标记已销毁
        process_pending(db)
def main():
    r=Redis.from_url(REDIS_URL,socket_timeout=3)
    # This Compose stack has a single worker. A crash must not strand its jobs.
    with Session() as db:
        for j in db.scalars(select(Job).where(Job.status=='running')):
            d=db.get(Dataset,j.dataset_id)
            if d is not None and d.sealed:
                j.status='failed';j.error='数据批次已封存销毁，结果禁止写回'
            else:
                j.status='queued'
            record(db,'worker','job.recovered',{'id':j.id})
        db.commit()
    while True:
        Path('/tmp/heartbeat').touch()
        try:
            item=r.blpop('analysis:queue',timeout=1)
            if item:execute(int(item[1]))
            tick()
        except Exception:
            logging.exception('Worker retry');time.sleep(2)
if __name__=='__main__':main()
