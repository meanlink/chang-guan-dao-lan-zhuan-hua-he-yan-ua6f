from enum import Enum
class Role(str, Enum):
    admin = 'admin'
    analyst = 'analyst'
    viewer = 'viewer'
class JobStatus(str, Enum):
    queued = 'queued'
    running = 'running'
    completed = 'completed'
    failed = 'failed'
class DestructionStatus(str, Enum):
    # 已封存，等待/正在清除
    sealed = 'sealed'
    clearing = 'clearing'
    # 存在清除失败项，等待重试
    failed = 'failed'
    # 数据与文件全部清除完成
    destroyed = 'destroyed'
