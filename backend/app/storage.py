"""SQLite-backed repository. Immutable snapshots are enforced in SQLite itself."""
import contextlib
import fcntl
import json
import os
import secrets
import uuid
from datetime import datetime,timezone
from pathlib import Path
from sqlalchemy import create_engine,text,event
from .domain import canonical,digest

def uid(): return str(uuid.uuid4())
def now(): return datetime.now(timezone.utc).isoformat()

class DomainError(Exception):
    def __init__(self,code,message,status=422):
        super().__init__(message); self.code=code;self.status=status;self.message=message

class Repository:
    def __init__(self,data_dir):
        self.root=Path(data_dir); self.root.mkdir(parents=True,exist_ok=True)
        (self.root/'objects').mkdir(exist_ok=True)
        self.engine=create_engine('sqlite:///'+str(self.root/'evaluation.db'),connect_args={'check_same_thread':False,'timeout':10})
        @event.listens_for(self.engine,'connect')
        def configure(dbapi_connection,connection_record):
            dbapi_connection.execute('PRAGMA foreign_keys=ON')
            dbapi_connection.execute('PRAGMA busy_timeout=10000')
        with self.engine.connect() as c:
            c.exec_driver_sql('PRAGMA journal_mode=WAL')
        from alembic import command
        from alembic.config import Config
        config=Config()
        config.set_main_option('script_location',str(Path(__file__).resolve().parents[1]/'migrations'))
        with open(self.root/'migration.lock','a+') as migration_lock:
            fcntl.flock(migration_lock,fcntl.LOCK_EX)
            with self.engine.begin() as c:
                config.attributes['connection']=c
                command.upgrade(config,'head')
    @contextlib.contextmanager
    def write(self):
        # Shared lock is held across both content-file and metadata mutation.
        with open(self.root/'write.lock','a+') as lock:
            fcntl.flock(lock,fcntl.LOCK_SH)
            if (self.root/'maintenance').exists(): raise DomainError('maintenance','正在维护，请稍后重试',503)
            with self.engine.connect() as c:
                c.exec_driver_sql('BEGIN IMMEDIATE')
                try:
                    yield c;c.commit()
                except Exception:
                    c.rollback();raise
            fcntl.flock(lock,fcntl.LOCK_UN)
    def record(self,c,kind,payload,record_id=None):
        payload=dict(payload); payload.setdefault('id',record_id or uid());payload.setdefault('created_at',now())
        c.execute(text('INSERT INTO records VALUES (:id,:kind,:payload,:created_at)'),{'id':payload['id'],'kind':kind,'payload':canonical(payload),'created_at':payload['created_at']})
        return payload
    def get(self,record_id,kind=None,c=None):
        if c is None:
            with self.engine.connect() as conn:return self.get(record_id,kind,conn)
        row=c.execute(text('SELECT kind,payload FROM records WHERE id=:id'),{'id':record_id}).first()
        if not row or (kind and row[0]!=kind):raise DomainError('not_found','记录不存在',404)
        return json.loads(row[1])
    def list(self,kind,c=None):
        if c is None:
            with self.engine.connect() as conn:return self.list(kind,conn)
        return [json.loads(r[0]) for r in c.execute(text('SELECT payload FROM records WHERE kind=:kind ORDER BY created_at DESC'),{'kind':kind})]
    def heads(self,kind,c=None):
        """Latest visible version of each logical object/dataset (records linked by parent_id)."""
        if c is None:
            with self.engine.connect() as conn:return self.heads(kind,conn)
        rows=c.execute(text('''SELECT payload FROM records r WHERE kind=:kind AND NOT EXISTS
            (SELECT 1 FROM records child WHERE child.kind=:kind AND json_extract(child.payload,'$.parent_id')=r.id)
            ORDER BY created_at DESC'''),{'kind':kind}).all()
        return [json.loads(r[0]) for r in rows]
    def experiment(self,id,c=None):
        if c is None:
            with self.engine.connect() as conn:return self.experiment(id,conn)
        row=c.execute(text('SELECT payload,current_revision FROM experiments WHERE id=:id'),{'id':id}).first()
        if not row:raise DomainError('not_found','实验不存在',404)
        result=json.loads(row[0]);result['current_revision_id']=row[1]
        result['current_summary']=result['current_gate']=None
        if row[1]:
            index=c.execute(text("SELECT json_extract(payload,'$.summary'),json_extract(payload,'$.gate') FROM records WHERE id=:id AND kind='report'"),{'id':row[1]}).first()
            if index:
                result['current_summary']=json.loads(index[0]) if index[0] else None
                result['current_gate']=index[1]
        progress=c.execute(text("SELECT payload FROM events WHERE experiment_id=:id AND json_extract(payload,'$.type')='case_progress' ORDER BY seq DESC LIMIT 1"),{'id':id}).first()
        result['progress']=json.loads(progress[0]).get('details') if progress else None
        job=c.execute(text('SELECT state FROM jobs WHERE experiment_id=:id'),{'id':id}).first()
        result['job_state']=job[0] if job else None
        return result
    def experiments(self,include_archived=False,source=None,status=None):
        with self.engine.connect() as c:
            rows=[self.experiment(r[0],c) for r in c.execute(text('SELECT id FROM experiments ORDER BY created_at DESC'))]
        return [x for x in rows if (include_archived or not x.get('archived_at')) and (not source or x.get('source')==source) and (not status or x.get('status')==status)]
    def archive_state(self,kind,target_id,c=None):
        if c is None:
            with self.engine.connect() as conn:return self.archive_state(kind,target_id,conn)
        row=c.execute(text("SELECT payload FROM records WHERE kind='archive' AND json_extract(payload,'$.target_kind')=:kind AND json_extract(payload,'$.target_id')=:id ORDER BY rowid DESC LIMIT 1"),{'kind':kind,'id':target_id}).first()
        return bool(row and json.loads(row[0]).get('action')=='archive')
    def put_experiment(self,c,payload):
        data=dict(payload); revision=data.pop('current_revision_id',None)
        c.execute(text('INSERT INTO experiments(id,payload,current_revision,created_at) VALUES(:id,:payload,:revision,:created_at)'),{'id':data['id'],'payload':canonical(data),'revision':revision,'created_at':data['created_at']})
    def update_experiment(self,c,ex):
        data=dict(ex)
        for transient in ('current_revision_id','current_summary','current_gate','progress','job_state'):data.pop(transient,None)
        c.execute(text('UPDATE experiments SET payload=:payload WHERE id=:id'),{'id':data['id'],'payload':canonical(data)})
    def event(self,c,id,type,details=None):
        c.execute(text('INSERT INTO events(experiment_id,payload) VALUES(:id,:payload)'),{'id':id,'payload':canonical({'type':type,'details':details or {},'created_at':now()})})
    def store_content(self,content):
        data=content.encode('utf-8') if isinstance(content,str) else content
        if len(data)>10*1024*1024:raise DomainError('file_limit','单文件超过 10 MiB')
        import hashlib
        sha=hashlib.sha256(data).hexdigest();path=self.root/'objects'/sha
        if not path.exists():
            tmp=path.with_suffix('.'+secrets.token_hex(6)+'.tmp');tmp.write_bytes(data);os.replace(str(tmp),str(path))
        return sha
