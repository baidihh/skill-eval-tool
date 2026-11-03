"""Durable local worker. No vendor API is assumed or silently emulated."""
import fcntl
import os
import signal
import time
from pathlib import Path
from sqlalchemy import text
from .storage import Repository
from .service import Service

def main():
    root=Path(os.environ.get('EVAL_DATA_DIR',Path(__file__).resolve().parents[2]/'.data'))
    repo=Repository(root);service=Service(repo);running=True
    def stop(*args):
        nonlocal running
        running=False
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    with open(root/'worker.lock','a+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise SystemExit('Worker already running')
        # Offline deterministic jobs can resume from durable queued state. Never resubmit live jobs.
        with repo.write() as c:
            rows=c.execute(text('SELECT experiment_id FROM jobs WHERE state IN ("pending","running")')).all()
            for row in rows:
                ex=repo.experiment(row[0],c)
                if ex['source']=='live':continue
                if ex['status']=='running':ex['status']='queued';repo.update_experiment(c,ex)
        while running:
            if (root/'maintenance').exists():time.sleep(.25);continue
            with repo.engine.connect() as c:
                row=c.execute(text('SELECT experiment_id FROM jobs WHERE state="pending" ORDER BY rowid LIMIT 1')).first()
            if row:
                try:service.process(row[0])
                except Exception as error:
                    with repo.write() as c:
                        c.execute(text('UPDATE jobs SET state="failed",error=:error WHERE experiment_id=:id'),{'id':row[0],'error':type(error).__name__})
                        ex=repo.experiment(row[0],c)
                        if ex['status'] not in ('completed','cancelled','failed','partial_failure'):
                            ex['status']='failed';ex['initial_terminal_status']='failed';repo.update_experiment(c,ex)
                        repo.event(c,row[0],'worker_error',{'error_type':type(error).__name__})
            else:time.sleep(.35)
if __name__=='__main__':main()
