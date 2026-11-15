import hashlib, json
def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
def dataset_dict(d):
    return {'id':d.id, 'name':d.name, 'source':d.source, 'rows':len(d.records), 'checksum':d.checksum, 'created_at':d.created_at, 'sealed':getattr(d,'sealed',False)}
def job_dict(j):
    return {k:getattr(j,k) for k in ['id','name','dataset_id','params','status','result','error','approved','created_at','finished_at']}
def report_dict(r):
    return {k:getattr(r,k) for k in ['id','name','job_id','destination','interval_seconds','next_run','enabled']}
def delivery_dict(d):
    return {k:getattr(d,k) for k in ['id','report_id','created_at','checksum','filename','destination']}
def destruction_item_dict(i):
    # 未清除项才暴露定位信息；不含任何客流内容，文件项仅有文件名
    data={'id':i.id,'kind':i.kind,'status':i.status,'attempts':i.attempts,
          'updated_at':i.updated_at,'last_error':i.last_error}
    if i.status!='cleared':
        data['ref_id']=i.ref_id
        data['target']=i.target
    return data
def destruction_order_dict(o, items=None):
    # 销毁凭证：只保留编号、计数、时间与操作人，不留客流明细
    data={'id':o.id,'code':o.code,'dataset_id':o.dataset_id,
          'dataset_name':o.dataset_name,'status':o.status,'counts':o.counts,
          'created_by_email':o.created_by_email,'sealed_at':o.sealed_at,
          'updated_at':o.updated_at,'finished_at':o.finished_at,
          'last_error':o.last_error}
    if items is not None:
        data['items']=[destruction_item_dict(i) for i in items]
    return data
