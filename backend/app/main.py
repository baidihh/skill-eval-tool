import copy
import json
import os
import secrets
import threading
import sys
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Body
from fastapi.responses import JSONResponse,HTMLResponse,FileResponse,Response
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from .storage import Repository,DomainError,uid,now
from .service import Service,LIMITS
from .domain import canonical,digest
from .report_export import render_html

DATA=Path(os.environ.get('EVAL_DATA_DIR',Path(__file__).resolve().parents[2]/'.data'))
repo=Repository(DATA);service=Service(repo)
SESSION=secrets.token_urlsafe(32);CSRF=secrets.token_urlsafe(32)
PORT=os.environ.get('EVAL_PORT','8765')
ORIGINS={f'http://127.0.0.1:{PORT}',f'http://localhost:{PORT}','http://127.0.0.1:5173','http://localhost:5173','http://testserver'}

@asynccontextmanager
async def lifespan(app):
    if os.environ.get('EVAL_SEED_DEMO','0')=='1':service.seed()
    yield

app=FastAPI(title='Skill 评测台',version='0.1.0',lifespan=lifespan)

@app.exception_handler(DomainError)
async def domain_error(request,exc):return JSONResponse(status_code=exc.status,content={'code':exc.code,'message':exc.message,'request_id':getattr(request.state,'request_id',uid()),'field_errors':[],'retryable':False})

@app.exception_handler(KeyError)
async def missing_key(request,exc):return JSONResponse(status_code=422,content={'code':'missing_field','message':'缺少必要字段：'+str(exc.args[0]),'request_id':getattr(request.state,'request_id',uid()),'field_errors':[],'retryable':False})

@app.exception_handler(RequestValidationError)
async def validation_error(request,exc):return JSONResponse(status_code=422,content={'code':'validation_error','message':'请求字段格式不正确','field_errors':[{'field':'.'.join(map(str,e['loc'])),'message':e['msg']} for e in exc.errors()],'request_id':getattr(request.state,'request_id',uid()),'retryable':False})

@app.middleware('http')
async def local_security(request,call_next):
    request.state.request_id=uid()
    host=request.headers.get('host','').split(':')[0]
    if host not in ('127.0.0.1','localhost','testserver'):return JSONResponse(status_code=403,content={'code':'invalid_host','message':'仅允许本机访问'})
    origin=request.headers.get('origin')
    if origin and origin not in ORIGINS:return JSONResponse(status_code=403,content={'code':'invalid_origin','message':'不允许该来源'})
    if request.url.path.startswith('/api/') and request.url.path!='/api/v1/session':
        if request.cookies.get('eval_session')!=SESSION:return JSONResponse(status_code=401,content={'code':'session_required','message':'请刷新页面建立本机会话'})
        if request.method not in ('GET','HEAD','OPTIONS') and request.headers.get('x-csrf-token')!=CSRF:return JSONResponse(status_code=403,content={'code':'csrf_required','message':'请求校验失败，请刷新页面'})
    length=request.headers.get('content-length')
    if length and int(length)>100*1024*1024:return JSONResponse(status_code=413,content={'code':'package_limit','message':'请求超过 100 MiB'})
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff';response.headers['Referrer-Policy']='no-referrer';response.headers['X-Request-ID']=request.state.request_id
    if request.url.path.startswith('/api/'):response.headers['Cache-Control']='no-store'
    return response

@app.get('/api/v1/session')
def session():
    response=JSONResponse({'csrf_token':CSRF,'identity':'本地维护者（未组织认证）'})
    response.set_cookie('eval_session',SESSION,httponly=True,samesite='strict',path='/')
    return response

@app.get('/api/v1/health')
def health():return {'status':'ok','version':'0.1.0','mode':'local-single-user'}

def object_view(obj,connection=None):
    result=dict(obj);result['archived']=repo.archive_state('object',obj['id'],connection);return result
@app.get('/api/v1/objects')
def objects(include_archived:bool=False):
    rows=[object_view(x) for x in repo.heads('object')]
    return rows if include_archived else [x for x in rows if not x['archived']]
@app.post('/api/v1/objects')
def create_object(data:dict=Body(...)):return object_view(service.create_object(data))
@app.get('/api/v1/objects/{id}')
def object_detail(id:str):return object_view(repo.get(id,'object'))
@app.post('/api/v1/objects/{id}/versions')
def create_version(id:str,data:dict=Body(...)):return object_view(service.add_object_version(id,data))
@app.post('/api/v1/objects/{id}/archive')
def archive_object(id:str,data:dict=Body(...)):return service.set_archive('object',id,'archive',data.get('operation_id'))
@app.post('/api/v1/objects/{id}/unarchive')
def unarchive_object(id:str,data:dict=Body(...)):return service.set_archive('object',id,'unarchive',data.get('operation_id'))

@app.get('/api/v1/datasets')
def datasets():return repo.heads('dataset')
@app.post('/api/v1/datasets')
def create_dataset(data:dict=Body(...)):return service.create_dataset(data)
@app.get('/api/v1/datasets/{id}')
def dataset_detail(id:str):return repo.get(id,'dataset')
@app.put('/api/v1/datasets/{id}')
def edit_dataset(id:str,data:dict=Body(...)):return service.update_dataset(id,data)
@app.post('/api/v1/datasets/{id}/publish')
def publish(id:str):return service.publish(id)

@app.get('/api/v1/experiments')
def experiments(include_archived:bool=False,source:str=None,status:str=None):return repo.experiments(include_archived,source,status)
@app.post('/api/v1/experiments')
def create_experiment(data:dict=Body(...)):
    if data.get('source')=='imported' and data.get('records'):raise DomainError('import_preview_required','运行记录须经过导入预览和确认')
    return service.create_experiment(data)
@app.get('/api/v1/experiments/{id}')
def experiment(id:str):return repo.experiment(id)
@app.post('/api/v1/experiments/{id}/start')
def start(id:str):return service.start(id)
@app.post('/api/v1/experiments/{id}/cancel')
def cancel(id:str):return service.cancel(id)
@app.post('/api/v1/experiments/{id}/archive')
def archive_experiment(id:str,data:dict=Body(...)):return service.set_archive('experiment',id,'archive',data.get('operation_id'))
@app.post('/api/v1/experiments/{id}/unarchive')
def unarchive_experiment(id:str,data:dict=Body(...)):return service.set_archive('experiment',id,'unarchive',data.get('operation_id'))
@app.post('/api/v1/experiments/{id}/copy')
def copy_experiment(id:str):
    ex=repo.experiment(id)
    return service.create_experiment({**ex,'name':ex['name']+' · 副本','records':[]})
@app.get('/api/v1/experiments/{id}/events')
def events(id:str,after:int=0):
    repo.experiment(id)
    with repo.engine.connect() as c:
        return [{'seq':row[0],**json.loads(row[1])} for row in c.execute(text('SELECT seq,payload FROM events WHERE experiment_id=:id AND seq>:after ORDER BY seq LIMIT 200'),{'id':id,'after':after})]

@app.get('/api/v1/reports/{id}/revisions')
def revisions(id:str):
    repo.experiment(id)
    return [{'revision_id':r['revision_id'],'previous_revision_id':r.get('previous_revision_id'),'reason':r.get('reason'),'gate':r.get('gate'),'source':r.get('source'),'status':r.get('status'),'summary':r.get('summary'),'content_hash':r.get('content_hash'),'created_at':r.get('created_at')} for r in repo.list('report') if r['experiment_id']==id]
@app.get('/api/v1/reports/{id}/revisions/{revision}')
def report(id:str,revision:str):return service.report(id,revision)
@app.get('/api/v1/reports/{id}')
def current_report(id:str):return service.report(id)
@app.post('/api/v1/reviews')
def review(data:dict=Body(...)):return service.review(data)
@app.post('/api/v1/gradings')
def regrade(data:dict=Body(...)):return service.regrade(data['experiment_id'],data['expected_revision_id'],data['operation_id'])
@app.post('/api/v1/experiments/{id}/usage')
def observe_usage(id:str,data:dict=Body(...)):return service.observe_usage(id,data)
@app.post('/api/v1/reviews/undo')
def undo_review(data:dict=Body(...)):return service.undo_review(data)
@app.post('/api/v1/gradings/{id}/adopt')
def adopt_grading(id:str,data:dict=Body(...)):return service.adopt_grading(id,data)
@app.post('/api/v1/comparisons')
def comparisons(data:dict=Body(...)):return service.compare(data)
@app.get('/api/v1/evidence/{id}')
def evidence(id:str):return repo.get(id,'evidence')
@app.get('/api/v1/reports/{id}/revisions/{revision}/export')
def export(id:str,revision:str,format:str='json'):
    data=service.report(id,revision)
    if format=='html':
        content=render_html(data)
        return HTMLResponse(content,headers={'Content-Disposition':'attachment; filename="report-%s.html"' % data['revision_id'][:8],'Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'"})
    return Response(json.dumps(data,ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':'attachment; filename="report.json"'})

def validate_import_preview(data):
    if data.get('schema_version')!='1.0':raise DomainError('schema_version','仅支持 schema_version 1.0')
    obj=repo.get(data.get('object_id'),'object');ds=repo.get(data.get('dataset_id'),'dataset')
    records=data.get('records',[])
    if not isinstance(records,list) or not records or len(records)>200:raise DomainError('invalid_records','运行包必须包含 1—200 条记录')
    ids=set();valid={x['case_id'] for x in ds['cases']};external=set()
    for record in records:
        cid=record.get('case_id')
        if cid not in valid or cid in ids:raise DomainError('invalid_record','题目不存在或重复：'+str(cid))
        ids.add(cid)
        if record.get('status') not in ('succeeded','failed','timed_out','outcome_unknown','cancelled'):raise DomainError('invalid_status','无效执行状态')
        if record.get('attempt_seq')!=1:raise DomainError('invalid_attempt_seq','必须明确提供首次执行 attempt_seq=1')
        ext=record.get('external_run_id')
        if not ext:raise DomainError('missing_external_id','导入记录必须包含 external_run_id')
        if ext in external:raise DomainError('duplicate_external_run','一个外部执行不能归属多个题目')
        external.add(ext)
        if len(canonical(record).encode())>10*1024*1024:raise DomainError('file_limit','单题记录超过 10 MiB')
    with repo.write() as c:return repo.record(c,'import',{'status':'validated','content_hash':digest(data),'payload':data,'preview':{'name':data.get('name','外部执行导入'),'record_count':len(records),'dataset_name':ds['name'],'source':'imported','missing_cases':len(valid-ids)}})
@app.post('/api/v1/imports')
async def preview_import(request:Request):
    raw=await request.body()
    if len(raw)>100*1024*1024:raise DomainError('package_limit','压缩包或 JSON 超过 100 MiB')
    files={}
    if request.headers.get('content-type','').split(';')[0] in ('application/zip','application/x-zip-compressed'):
        sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
        from package_io import read_package
        try:data,files=read_package(raw)
        except ValueError as error:raise DomainError('invalid_package',str(error))
        if data.get('document_type')=='report':
            try:original=json.loads(files['report.json'])
            except (KeyError,ValueError,UnicodeDecodeError):raise DomainError('invalid_archive','报告归档缺少有效 report.json')
            if digest({k:v for k,v in original.items() if k!='content_hash'})!=original.get('content_hash'):raise DomainError('invalid_archive','报告内容哈希不匹配')
            if original.get('content_hash')!=data.get('content_hash'):raise DomainError('invalid_archive','归档清单与报告不匹配')
            with repo.write() as c:
                return repo.record(c,'import',{'status':'validated','document_type':'report','content_hash':digest(original),'original_report':original,'preview':{'name':original['name'],'record_count':len(original['cases']),'source':'imported','original_source':original['source'],'read_only_archive':True}})
    else:
        try:data=json.loads(raw)
        except (ValueError,UnicodeDecodeError):raise DomainError('invalid_json','请提供 UTF-8 JSON 或标准 ZIP 包')
    if not isinstance(data,dict):raise DomainError('invalid_package','清单必须为对象')
    if files:
        # Registration fixes exact attachment bytes, but does not silently treat arbitrary files as parsed evidence.
        with repo.write() as c:
            refs=[{'path':path,'sha256':repo.store_content(content),'size':len(content),'state':'acquired'} for path,content in files.items()]
        data={**data,'attachment_objects':refs}
        for record in data.get('records',[]):
            artifact=record.get('output_evidence_path')
            if artifact:
                if artifact not in files:raise DomainError('missing_artifact','执行记录引用了缺失附件：'+str(artifact))
                if not artifact.lower().endswith('.json'):raise DomainError('unsupported_artifact','首期结构化产物核验支持 JSON；其他附件仅保存不判通过')
                try:output=json.loads(files[artifact].decode('utf-8'))
                except (ValueError,UnicodeDecodeError):raise DomainError('artifact_parse_error','结构化产物 JSON 解析失败')
                record['final_reply']=record.get('output')
                record['output']=output
                record['output_artifact']={'path':artifact,'sha256':next(x['sha256'] for x in refs if x['path']==artifact)}
    return validate_import_preview(data)

@app.get('/api/v1/reports/{id}/revisions/{revision}/export.zip')
def export_zip(id:str,revision:str):
    report=service.report(id,revision)
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
    from package_io import write_package
    files={'report.json':json.dumps(report,ensure_ascii=False,indent=2).encode('utf-8')}
    for case in report['cases']:
        for evidence in case['evidence']:
            files['evidence/'+evidence['id']+'.txt']=evidence['content'].encode('utf-8')
    manifest={'schema_version':'1.0','document_type':'report','source':report['source'],'report_revision_id':report['revision_id'],'content_hash':report['content_hash'],'object_snapshot':repo.get(repo.experiment(id)['object_id'],'object') if repo.experiment(id).get('object_id') else None,'dataset_snapshot':repo.get(repo.experiment(id)['dataset_id'],'dataset') if repo.experiment(id).get('dataset_id') else None}
    try:payload=write_package(manifest,files)
    except ValueError as error:raise DomainError('package_limit',str(error))
    return Response(payload,media_type='application/zip',headers={'Content-Disposition':'attachment; filename="report-evidence.zip"'})

@app.post('/api/v1/imports/{id}/confirm')
def confirm_import(id:str,data:dict=Body(...)):
    preview=repo.get(id,'import')
    if preview.get('document_type')=='report':return service.confirm_archive(preview,data)
    return service.confirm_import(preview,data)

@app.post('/api/v1/demo/seed')
def seed():service.seed();return {'status':'ready','source':'demo'}
@app.get('/api/v1/connections')
def connections():
    from .judge import HttpJudge
    judge_ready=HttpJudge.from_environment() is not None
    return [{'id':'company-platform','name':'公司专家平台','status':'unconfigured','capabilities':{'submit':False,'poll':False,'idempotency':False,'cancel':False,'configuration':False,'artifacts':False},'message':'等待经核实的 API、测试身份和环境；未启用真实调用'},{'id':'model-judge','name':'模型裁判服务','status':'configured' if judge_ready else 'unconfigured','capabilities':{},'message':'当前可使用内置规则及人工复核；模型裁判未接入'}]
@app.get('/api/v1/settings')
def settings():return {'limits':LIMITS,'mode':'local-single-user','identity':'本地维护者（未组织认证）','storage':{'object_count':len(list((DATA/'objects').iterdir())),'bytes':sum(p.stat().st_size for p in (DATA/'objects').iterdir() if p.is_file())},'live_enabled':False,'judge_enabled':False,'version':'0.1.0'}

FRONTEND=Path(os.environ.get('EVAL_FRONTEND_DIR',Path(__file__).resolve().parents[2]/'frontend'/'dist'))
if (FRONTEND/'assets').exists():app.mount('/assets',StaticFiles(directory=str(FRONTEND/'assets')),name='assets')
@app.get('/{path:path}')
def frontend(path:str):
    if path.startswith('api/'):raise DomainError('not_found','接口不存在',404)
    if (FRONTEND/'index.html').exists():return FileResponse(FRONTEND/'index.html')
    return HTMLResponse('<h1>Skill 评测台 API 已启动</h1><p>请先构建 frontend，然后重新启动。</p>')
