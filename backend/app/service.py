import contextlib
import copy
import json
from sqlalchemy import text
from .storage import DomainError,uid,now
from .domain import digest,canonical,summarize,compare_manifests,project_manifest,DIMENSIONS

LIMITS={'max_cases':200,'max_file_bytes':10*1024*1024,'max_package_bytes':100*1024*1024,'max_files':1000,'execution_concurrency':1,'grading_concurrency':1,'expert_timeout_seconds':300,'judge_timeout_seconds':120,'technical_retries':1,'initial_judge_calls_per_case':6}

def validate_cases(cases):
    if not isinstance(cases,list) or not 1<=len(cases)<=200:raise DomainError('invalid_cases','评测集必须包含 1—200 道题目')
    seen=set();result=[]
    for raw in cases:
        case=copy.deepcopy(raw);cid=case.get('case_id')
        if not cid or cid in seen:raise DomainError('duplicate_case','题目 ID 为空或重复：'+str(cid))
        seen.add(cid)
        if not case.get('input') or not isinstance(case['input'],str):raise DomainError('invalid_input',cid+' 缺少任务输入')
        if case.get('messages') or case.get('history'):raise DomainError('unsupported_multiturn',cid+' 首期不支持多轮任务')
        checks=case.get('checks',[])
        if not checks or not any(c.get('required',True) and c.get('applicable',True) for c in checks):raise DomainError('missing_checks',cid+' 必须配置适用的必选检查')
        check_ids=set()
        for check in checks:
            check.setdefault('id',check.get('check_id',uid()));check.setdefault('name',check['id']);check.setdefault('required',True);check.setdefault('applicable',True);check.setdefault('critical',False)
            check.setdefault('dimension','correctness');check.setdefault('type','equals')
            if check['id'] in check_ids:raise DomainError('duplicate_check','重复检查 ID')
            check_ids.add(check['id'])
            if check['critical'] and not check['required']:raise DomainError('invalid_check','关键检查必须为必选')
            if check['type'] not in ('equals','field_exists','number_tolerance','json_type','contains','refund_policy','model'):raise DomainError('unsupported_evaluator','不支持的评估器：'+check['type'])
            if check['dimension'] not in DIMENSIONS:raise DomainError('invalid_dimension','无效评分维度')
            if check['type']=='field_exists' and (not isinstance(check.get('fields'),list) or not check['fields'] or not all(isinstance(v,str) and v for v in check['fields'])):raise DomainError('invalid_evaluator','字段完整性检查必须提供非空字段列表')
            if check['type']=='number_tolerance' and (not isinstance(check.get('tolerance',0),(int,float)) or check.get('tolerance',0)<0):raise DomainError('invalid_evaluator','数值容差必须为非负数')
            if check['type']=='json_type' and check.get('expected') not in ('object','array','string','number','boolean'):raise DomainError('invalid_evaluator','无效 JSON 类型')
        case.setdefault('case_version','1');case.setdefault('tags',[]);case.setdefault('execution_materials',[]);case.setdefault('judge_materials',[])
        case['content_hash']=digest({k:v for k,v in case.items() if k!='content_hash'});result.append(case)
    return result

class Service:
    def __init__(self,repo):self.repo=repo
    def seed(self):
        if any(obj.get('source')=='demo' for obj in self.repo.list('object')):return
        with self.repo.write() as c:
            versions=[]
            for version,hours in [('v1',360),('v2',168)]:
                content='# 退款审核\n按商家政策审核。退款时限为 '+str(hours)+' 小时。\n'
                sha=self.repo.store_content(content)
                versions.append({'id':uid(),'version':version,'hash':sha,'trust':'content_verified','content':content})
            obj=self.repo.record(c,'object',{'name':'refund-review','description':'退款审核 Skill · 仅为演示夹具，不代表公司政策','target_skill':'refund-review','versions':versions,'expert':{'expert_id':'demo-mirror','model':'deterministic-fixture-v1','system_prompt':'仅在演示环境核验退款政策','verified':True},'source':'demo'})
            cases=[]
            samples=[('RF01',0),('RF02',72),('RF03',167.99),('RF04',168),('RF05',168.01),('RF06',192),('RF07',360),('RF08',384)]
            for cid,hours in samples:
                cases.append({'case_id':cid,'case_version':'1','input':f'请按商家政策审核订单 {cid}：签收后 {hours} 小时申请，已付款、未拆封、未损坏，交付审核 JSON，不输出电话，不执行真实退款。','evaluation_time':'2026-11-04T12:00:00+08:00','initial_state':{'fixture':'refund-v1','hours_since_receipt':hours},'execution_materials':[{'name':'商家政策','text':'仅为演示政策：签收后连续 168 小时内（含边界）可退款，超过不可退款。'}],'judge_materials':[{'name':'权威政策','text':'退款期限连续 168 小时，包含边界。'}],'reference':{'eligible':hours<=168,'refund_cents':6000 if hours<=168 else 0},'checks':[{'id':'correctness','name':'退款期限与金额符合权威政策','dimension':'correctness','type':'refund_policy','required':True,'critical':True},{'id':'completion','name':'审核表必需字段齐全','dimension':'completion','type':'field_exists','fields':['eligible','refund_cents'],'required':True},{'id':'privacy','name':'不泄露客户电话','dimension':'constraints','type':'equals','path':'customer_phone','expected':None,'required':True}], 'tags':['正常' if hours<168 else '边界' if hours<169 else '历史失败']})
            cases=validate_cases(cases)
            ds=self.repo.record(c,'dataset',{'name':'退款审核回归集','status':'published','version':'1.0.0','description':'8 道固定时刻边界题，168 小时包含边界；仅供演示','cases':cases,'content_hash':digest(cases),'source':'demo'})
        for variant,name in [('before','修复前 · 15 天错误期限'),('after','修复后 · 7 天政策期限')]:
            ex=self.create_experiment({'name':name,'source':'demo','object_id':obj['id'],'dataset_id':ds['id'],'variant':variant})
            self.start(ex['id']);self.process(ex['id'])
    def create_dataset(self,data):
        cases=validate_cases(data.get('cases',[]))
        with self.repo.write() as c:return self.repo.record(c,'dataset',{'name':data.get('name') or '未命名评测集','description':data.get('description',''),'status':'draft','version':data.get('version','1'),'cases':cases,'content_hash':digest(cases),'source':'user'})
    def update_dataset(self,id,data):
        old=self.repo.get(id,'dataset')
        if old['status']!='draft':raise DomainError('dataset_published','已发布版本只读；请另存为新版本',409)
        cases=validate_cases(data.get('cases',old['cases']))
        with self.repo.write() as c:
            return self.repo.record(c,'dataset',{**{k:v for k,v in old.items() if k not in ('id','created_at')},'parent_id':id,'name':data.get('name') or old.get('name'),'description':data.get('description',old.get('description','')),'version':data.get('version',old.get('version','1')),'cases':cases,'content_hash':digest(cases)})
    def publish(self,id):
        ds=self.repo.get(id,'dataset');cases=validate_cases(ds['cases'])
        if ds['status']=='published':return ds
        with self.repo.write() as c:
            for other in self.repo.list('dataset',c):
                if other['id']!=id and other['status']=='published' and other.get('name')==ds.get('name') and other.get('version')==ds.get('version') and other.get('content_hash')!=digest(cases):
                    raise DomainError('version_conflict','同名同版本已发布且内容不同；请修改版本号',409)
            return self.repo.record(c,'dataset',{**{k:v for k,v in ds.items() if k not in ('id','created_at')},'status':'published','parent_id':id,'cases':cases,'content_hash':digest(cases)})
    def create_object(self,data):
        content=data.get('content','# '+data.get('name','Skill'))
        if not data.get('name'):raise DomainError('missing_name','请输入 Skill 名称')
        with self.repo.write() as c:
            sha=self.repo.store_content(content)
            return self.repo.record(c,'object',{'name':data['name'],'description':data.get('description',''),'target_skill':data['name'],'versions':[{'id':uid(),'version':data.get('version','v1'),'hash':sha,'content':content,'trust':'content_verified'}],'expert':data.get('expert',{'expert_id':'','model':None,'system_prompt':None,'verified':False}),'source':'user'})
    def add_object_version(self,id,data):
        content=data.get('content','');label=data.get('version','new')
        if not isinstance(content,str) or not content.strip():raise DomainError('missing_content','请提供 Skill 版本内容')
        with self.repo.write() as c:
            old=self.repo.get(id,'object',c)
            if any(v.get('version')==label and v.get('hash')!=digest(content) for v in old['versions']):
                raise DomainError('version_conflict','同一版本号已有不同内容；请使用新版本号',409)
            sha=self.repo.store_content(content)
            version={'id':uid(),'version':label,'hash':sha,'content':content,'trust':'content_verified'}
            return self.repo.record(c,'object',{**{k:v for k,v in old.items() if k not in ('id','created_at')},'parent_id':id,'versions':old['versions']+[version]})
    def set_archive(self,kind,target_id,action,operation_id):
        if kind not in ('object','experiment'):raise DomainError('invalid_target','不支持该归档对象')
        if action not in ('archive','unarchive'):raise DomainError('invalid_action','归档动作必须为 archive 或 unarchive')
        if not operation_id:raise DomainError('missing_operation','必须提供 operation_id')
        request={'kind':kind,'target_id':target_id,'action':action}
        with self.repo.write() as c:
            receipt=c.execute(text('SELECT request_hash,response FROM receipts WHERE operation_id=:id'),{'id':operation_id}).first()
            if receipt:
                if receipt[0]!=digest(request):raise DomainError('operation_conflict','同一归档操作内容不同',409)
                return json.loads(receipt[1])
            if kind=='object':
                obj=self.repo.get(target_id,'object',c)
                archived=self.repo.archive_state('object',target_id,c)
                result={'id':obj['id'],'kind':'object','archived':action=='archive'}
            else:
                ex=self.repo.experiment(target_id,c)
                if ex.get('read_only_archive'):raise DomainError('archive_readonly','只读导入归档不能改变状态')
                archived=bool(ex.get('archived_at'))
                result={'id':ex['id'],'kind':'experiment','archived':action=='archive'}
            if archived!=(action=='archive'):
                if kind=='object':
                    self.repo.record(c,'archive',{'target_kind':'object','target_id':target_id,'action':action,'identity':'本地维护者（未组织认证）'})
                else:
                    ex['archived_at']=now() if action=='archive' else None
                    self.repo.update_experiment(c,ex);self.repo.event(c,target_id,'archived' if action=='archive' else 'unarchived')
            c.execute(text('INSERT INTO receipts VALUES(:id,:hash,:response)'),{'id':operation_id,'hash':digest(request),'response':canonical(result)})
            return result
    def create_experiment(self,data,connection=None):
        source=data.get('source','demo')
        if source not in ('live','imported','demo'):raise DomainError('invalid_source','无效运行来源')
        obj=self.repo.get(data['object_id'],'object');ds=self.repo.get(data['dataset_id'],'dataset')
        if self.repo.archive_state('object',obj['id']):raise DomainError('object_archived','评测对象已归档，不能创建新实验')
        if ds['status']!='published':raise DomainError('unpublished_dataset','只能使用已发布评测集')
        validate_cases(ds['cases'])
        variant=data.get('variant','before');versions=obj['versions']
        if data.get('skill_version_id') and not any(v['id']==data['skill_version_id'] for v in versions):raise DomainError('invalid_skill_version','所选 Skill 版本不属于评测对象')
        version=next((v for v in versions if v['id']==data.get('skill_version_id')),versions[-1] if variant=='after' else versions[0])
        expert=obj['expert'];manifest={'source':source,'target_skill':obj['target_skill'],'skills':[{'name':obj['target_skill'],'hash':version['hash'],'version':version['version']}], 'model':expert.get('model'),'system_prompt':expert.get('system_prompt'),'verified':bool(expert.get('verified')),'dataset_hash':ds['content_hash'],'policy':'baseline-v1','generation_parameters':{'mode':'deterministic_fixture'} if source=='demo' else {'state':'unknown'},'tools':[],'environment':{'mode':'demo-fixture'} if source=='demo' else {'state':'unknown'},'memory':{'enabled':False} if source=='demo' else {'state':'unknown'},'initial_state':[x.get('initial_state',{'state':'not_applicable'}) for x in ds['cases']],'judge':{'mode':'builtin-rules-v1'},'limits':LIMITS,'attempt_selection':'first-planned','evaluation_time':[x.get('evaluation_time',{'state':'not_applicable'}) for x in ds['cases']],'authoritative_policy_hash':digest([x['judge_materials'] for x in ds['cases']]),'trigger_mode':'fixture' if source=='demo' else 'unknown','expert_id':expert.get('expert_id')}
        records=data.get('records',[])
        if source=='imported':self.validate_records(records,ds,allow_empty=True)
        ex={'id':uid(),'name':data.get('name') or '未命名实验','source':source,'status':'draft','object_id':obj['id'],'dataset_id':ds['id'],'variant':variant,'skill_version_id':version['id'],'manifest':manifest,'created_at':now(),'records':data.get('records',[]),'initial_terminal_status':None,'archived_at':None}
        with (contextlib.nullcontext(connection) if connection is not None else self.repo.write()) as c:
            self.repo.put_experiment(c,ex);self.repo.event(c,ex['id'],'created',{'source':source})
            return self.repo.experiment(ex['id'],c)
    def confirm_archive(self,preview,data):
        operation=data.get('operation_id')
        if not operation:raise DomainError('missing_operation','必须提供 operation_id')
        with self.repo.write() as c:
            receipt=c.execute(text('SELECT request_hash,response FROM receipts WHERE operation_id=:id'),{'id':operation}).first()
            if receipt:
                if receipt[0]!=preview['content_hash']:raise DomainError('operation_conflict','操作键内容冲突',409)
                return json.loads(receipt[1])
            original=preview['original_report'];source_blob=self.repo.record(c,'archive_original',{'original_report':original,'original_hash':original['content_hash'],'source':'imported'})
            manifest=copy.deepcopy(original['manifest']);manifest['source']='imported';manifest['archive_provenance']={'original_hash':original['content_hash'],'original_source':original['source']}
            ex={'id':uid(),'name':original['name']+' · 导入归档','source':'imported','status':original['status'],'object_id':None,'dataset_id':None,'variant':'archive','manifest':manifest,'created_at':now(),'initial_terminal_status':original.get('initial_terminal_status'),'read_only_archive':True,'original_archive_id':source_blob['id']}
            self.repo.put_experiment(c,ex)
            cases=copy.deepcopy(original['cases'])
            for case in cases:
                mapping={e['id']:uid() for e in case['evidence']}
                for evidence in case['evidence']:
                    evidence['id']=mapping[evidence['id']]
                    self.repo.store_content(evidence['content'])
                    self.repo.record(c,'evidence',{**evidence,'experiment_id':ex['id'],'case_id':case['case_id']})
                for check in case['checks']:check['evidence_refs']=[mapping.get(ref,ref) for ref in check.get('evidence_refs',[])]
            self._append(c,ex,cases,'archive-import','archive-report:'+ex['id'],usage=original['usage'])
            result=self.repo.experiment(ex['id'],c)
            c.execute(text('INSERT INTO receipts VALUES(:id,:hash,:response)'),{'id':operation,'hash':preview['content_hash'],'response':canonical(result)})
            return result
    def validate_records(self,records,ds,allow_empty=False):
        if not isinstance(records,list) or len(records)>200 or (not records and not allow_empty):raise DomainError('invalid_records','运行包必须包含 1—200 条记录')
        seen=set();external=set();valid={x['case_id'] for x in ds['cases']}
        for record in records:
            cid=record.get('case_id');ext=record.get('external_run_id')
            if cid not in valid or cid in seen:raise DomainError('invalid_record','题目不存在或重复：'+str(cid))
            if not ext or ext in external:raise DomainError('invalid_external_id','外部运行 ID 缺失或重复')
            if record.get('status') not in ('succeeded','failed','timed_out','outcome_unknown','cancelled'):raise DomainError('invalid_status','无效执行状态')
            if record.get('attempt_seq')!=1:raise DomainError('unsupported_attempt','首期导入主记录必须为第一次执行；后续尝试另行支持')
            if len(canonical(record).encode())>10*1024*1024:raise DomainError('file_limit','单题超过 10 MiB')
            seen.add(cid);external.add(ext)
    def confirm_import(self,preview,data):
        payload=preview['payload'];operation=data.get('operation_id')
        if not operation:raise DomainError('missing_operation','必须提供 operation_id')
        with self.repo.write() as c:
            receipt=c.execute(text('SELECT request_hash,response FROM receipts WHERE operation_id=:id'),{'id':operation}).first()
            if receipt:
                if receipt[0]!=preview['content_hash']:raise DomainError('operation_conflict','操作键内容冲突',409)
                return self.repo.experiment(json.loads(receipt[1])['id'],c)
            content_operation='import-content:'+preview['content_hash']
            prior=c.execute(text('SELECT response FROM receipts WHERE operation_id=:id'),{'id':content_operation}).first()
            if prior:
                ex=self.repo.experiment(json.loads(prior[0])['id'],c)
            else:
                ds=self.repo.get(payload['dataset_id'],'dataset',c);self.validate_records(payload['records'],ds)
                namespace=payload.get('namespace','imported-local')
                for record in payload['records']:
                    previous=c.execute(text('SELECT request_hash FROM external_ownership WHERE namespace=:ns AND external_run_id=:id'),{'ns':namespace,'id':record['external_run_id']}).first()
                    if previous:raise DomainError('external_run_conflict','外部执行已导入，不能制造第二次执行',409)
                ex=self.create_experiment({'name':payload.get('name','外部执行导入'),'source':'imported','object_id':payload['object_id'],'dataset_id':payload['dataset_id'],'records':payload['records']},connection=c)
                ex['status']='queued';self.repo.update_experiment(c,ex)
                c.execute(text('INSERT INTO jobs(id,experiment_id,state) VALUES(:id,:eid,"pending")'),{'id':uid(),'eid':ex['id']})
                for record in payload['records']:
                    c.execute(text('INSERT INTO external_ownership VALUES(:ns,:ext,:eid,:cid,:hash)'),{'ns':namespace,'ext':record['external_run_id'],'eid':ex['id'],'cid':record['case_id'],'hash':digest(record)})
                c.execute(text('INSERT INTO receipts VALUES(:id,:hash,:response)'),{'id':content_operation,'hash':preview['content_hash'],'response':canonical(ex)})
            c.execute(text('INSERT INTO receipts VALUES(:id,:hash,:response)'),{'id':operation,'hash':preview['content_hash'],'response':canonical(ex)})
            return ex
    def start(self,id):
        with self.repo.write() as c:
            ex=self.repo.experiment(id,c)
            if ex['status']!='draft':return ex
            if ex['source']=='live':raise DomainError('platform_unconfigured','尚未配置经核实的公司专家适配器；真实调用未启用。不能以演示替代真实运行。')
            if ex['source']=='imported' and not ex.get('records'):
                ex['status']='awaiting_import';self.repo.update_experiment(c,ex);return ex
            ex['status']='queued';self.repo.update_experiment(c,ex)
            c.execute(text('INSERT INTO jobs(id,experiment_id,state) VALUES(:id,:eid,"pending")'),{'id':uid(),'eid':id})
            self.repo.event(c,id,'queued');return ex
    def cancel(self,id):
        with self.repo.write() as c:
            ex=self.repo.experiment(id,c)
            if ex['status']=='cancel_requested':return ex
            if ex['status'] not in ('draft','awaiting_import','queued','running'):raise DomainError('invalid_state','实验已到终态，不能取消')
            if ex['status']=='running':
                # Stop new work first; the worker finalizes the fact after preserving results.
                ex['status']='cancel_requested';self.repo.update_experiment(c,ex)
                c.execute(text('UPDATE jobs SET state="cancelled" WHERE experiment_id=:id'),{'id':id})
                self.repo.event(c,id,'cancel_requested',{'note':'已停止提交新任务；在途外部任务可能仍会继续计费'})
                return ex
            ex['status']='cancelled';ex['initial_terminal_status']='cancelled';self.repo.update_experiment(c,ex)
            c.execute(text('UPDATE jobs SET state="cancelled" WHERE experiment_id=:id'),{'id':id});self.repo.event(c,id,'cancelled')
            return ex
    def _value(self,output,path):
        value=output
        for piece in path.split('.') if path else []:
            if not isinstance(value,dict):return None
            value=value.get(piece)
        return value
    def grade_case(self,case,record,attempt):
        output=record.get('output');status=record.get('status','succeeded');eid=uid();evidence=[]
        if output is not None:
            content=canonical(output);sha=self.repo.store_content(content)
            evidence=[{'id':eid,'type':'json','content':content,'sha256':sha,'state':'parsed','attempt_id':attempt['id'],'location':{'json_path':'$'}}]
        checks=[];grading_error=False;data_error=False
        for spec in case['checks']:
            check=copy.deepcopy(spec);check.update({'evidence_refs':[eid] if evidence else [],'reviewed':False,'origin':'automatic'})
            result='insufficient_evidence';reason='未取得成功执行的可解析产物'
            if not spec.get('applicable',True):result='not_applicable';reason='发布时固定为不适用'
            elif status=='succeeded' and output is not None:
                typ=spec.get('type','equals');path=spec.get('path','');actual=self._value(output,path)
                if typ=='refund_policy':
                    hours=case.get('initial_state',{}).get('hours_since_receipt');reference=case.get('reference',{})
                    if hours is None:reason='缺少固定签收时长'
                    elif reference.get('eligible')!=(hours<=168):
                        data_error=True;reason='参考答案与权威政策 168 小时冲突';check['error']='data_error'
                    else:
                        good=isinstance(output,dict) and output.get('eligible')==(hours<=168) and output.get('refund_cents')==reference.get('refund_cents')
                        result='pass' if good else 'fail';reason=f'固定签收时长 {hours} 小时；政策允许 ≤168 小时。实际 eligible={output.get("eligible") if isinstance(output,dict) else None}，预期={hours<=168}。'
                elif typ=='field_exists':
                    good=isinstance(output,dict) and all(field in output for field in spec.get('fields',[]));result='pass' if good else 'fail';reason='核对实际 JSON 必需字段：'+', '.join(spec.get('fields',[]))
                elif typ=='model':
                    grading_error=True;check['error']='grading_error';reason='裁判服务尚未配置，此检查不能自动通过'
                else:
                    expected=spec.get('expected',case.get('reference'))
                    if typ=='equals':good=actual==expected
                    elif typ=='number_tolerance':good=isinstance(actual,(int,float)) and not isinstance(actual,bool) and isinstance(expected,(int,float)) and abs(actual-expected)<=spec.get('tolerance',0)
                    elif typ=='contains':good=isinstance(actual,str) and str(expected) in actual
                    elif typ=='json_type':good={'object':isinstance(actual,dict),'array':isinstance(actual,list),'string':isinstance(actual,str),'number':isinstance(actual,(int,float)) and not isinstance(actual,bool),'boolean':isinstance(actual,bool)}.get(spec.get('expected'),False)
                    else:good=False
                    result='pass' if good else 'fail';reason='根据固定规则核对实际产物，'+('符合要求' if good else '不符合要求')
            check.update({'result':result,'reason':reason});checks.append(check)
        return {'case_id':case['case_id'],'case_version':case['case_version'],'content_hash':case['content_hash'],'input':case['input'],'reference':case.get('reference'),'tags':case['tags'],'status':status,'output':output,'checks':checks,'evidence':evidence,'attempts':[attempt],'grading_error':grading_error,'data_error':data_error,'review_history':[]}
    def process(self,id):
        with self.repo.write() as c:
            ex=self.repo.experiment(id,c)
            if ex['status'] not in ('queued','cancel_requested'):return
            if ex['status']=='cancel_requested':
                ex['status']='cancelled';ex['initial_terminal_status']='cancelled';self.repo.update_experiment(c,ex)
                c.execute(text('UPDATE jobs SET state="cancelled" WHERE experiment_id=:id'),{'id':id});self.repo.event(c,id,'cancelled',{'partial_cases':0})
                return
            ex['status']='running';self.repo.update_experiment(c,ex);self.repo.event(c,id,'running',{'total':len(self.repo.get(ex['dataset_id'],'dataset',c)['cases'])})
        ds=self.repo.get(ex['dataset_id'],'dataset');cases=[];records={r['case_id']:r for r in ex.get('records',[])};total=len(ds['cases'])
        for index,case in enumerate(ds['cases']):
            if self.repo.experiment(id)['status'] in ('cancel_requested','cancelled'):break
            attempt={'id':uid(),'attempt_seq':1,'is_primary':True,'status':'succeeded','created_at':now(),'source':ex['source'],'external_run_id':None}
            if ex['source']=='demo':
                hours=case.get('initial_state',{}).get('hours_since_receipt')
                if hours is None:record={'status':'failed','output':None,'error':'示例执行器仅支持退款夹具；请导入执行记录'}
                else:
                    eligible=hours<=(360 if ex['variant']=='before' else 168);record={'status':'succeeded','output':{'eligible':eligible,'refund_cents':6000 if eligible else 0}}
            else:record=records.get(case['case_id'],{'status':'failed','output':None,'error':'缺少外部执行记录'})
            attempt['status']=record.get('status','succeeded');attempt['external_run_id']=record.get('external_run_id');attempt['request_hash']=digest({'input':case['input'],'execution_materials':case['execution_materials']})
            with self.repo.write() as c:
                self.repo.record(c,'attempt',{**attempt,'experiment_id':id,'case_id':case['case_id'],'submitted_input':{'input':case['input'],'execution_materials':case['execution_materials']}})
                graded=self.grade_case(case,record,attempt)
                for evidence in graded['evidence']:self.repo.record(c,'evidence',{**evidence,'experiment_id':id,'case_id':case['case_id']})
            # Network is strictly outside metadata/file write permits and DB transactions.
            if any(check.get('type')=='model' for check in graded['checks']):self.evaluate_model(ex,case,graded)
            cases.append(graded)
            with self.repo.write() as c:
                self.repo.event(c,id,'case_progress',{'done':index+1,'total':total,'executed':sum(1 for x in cases if x['status']=='succeeded'),'graded':sum(1 for x in cases if not x['grading_error'] and not x['data_error'])})
        with self.repo.write() as c:
            current=self.repo.experiment(id,c)
            if current['status'] in ('cancel_requested','cancelled'):
                current['status']='cancelled';current['initial_terminal_status']='cancelled';self.repo.update_experiment(c,current)
                c.execute(text('UPDATE jobs SET state="cancelled" WHERE experiment_id=:id'),{'id':id})
                if cases:self._append(c,current,cases,'cancelled-partial','cancelled:'+id)
                self.repo.event(c,id,'cancelled',{'partial_cases':len(cases),'note':'已停止后续提交；保留已产生结果，取消不代表外部操作已回滚'})
                return
            errors=any(x['status']!='succeeded' or x['grading_error'] or x['data_error'] for x in cases)
            status='partial_failure' if errors and any(x['status']=='succeeded' for x in cases) else 'failed' if errors else 'completed'
            current['status']=status;current['initial_terminal_status']=status;self.repo.update_experiment(c,current)
            self._append(c,current,cases,'initial-results','initial:'+id)
            c.execute(text('UPDATE jobs SET state="completed" WHERE experiment_id=:id'),{'id':id});self.repo.event(c,id,'finished',{'status':status})
    def evaluate_model(self,ex,case,graded):
        from .judge import HttpJudge
        from .ledger import Ledger
        adapter=HttpJudge.from_environment()
        if adapter is None:return
        model_checks=[check for check in graded['checks'] if check.get('type')=='model' and check.get('applicable',True)]
        ledger=Ledger(self.repo)
        for dimension in dict.fromkeys(check['dimension'] for check in model_checks):
            group=[check for check in model_checks if check['dimension']==dimension]
            frozen={'checks':[{key:value for key,value in check.items() if key not in ('result','reason','error','evidence_refs','reviewed','origin')} for check in group],'task':case['input'],'reference':case.get('reference'),'judge_materials':case['judge_materials'],'output':graded['output'],'evidence':graded['evidence']}
            key='initial-judge:'+ex['id']+':'+case['case_id']+':'+dimension
            call=ledger.reserve_call(ex['id'],case['case_id'],'judge','initial:'+graded['attempts'][0]['id'],'configured-judge',key,frozen)
            transport=ledger.reserve_transport(call['id'],key+':transport1')
            try:
                result,usage=adapter.evaluate(frozen,call['id'])
                ledger.observe_usage(call['id'],call['id']+':fee',transport['id']+':usage',{'amount':usage.get('amount'),'currency':usage.get('currency'),'tokens':usage.get('tokens'),'basis':usage.get('basis','unknown')})
                for item in result.checks:
                    check=next(check for check in group if check['id']==item.check_id)
                    check.pop('error',None);check.update({'result':item.result,'reason':item.reason,'evidence_refs':[ref.evidence_id for ref in item.evidence_refs],'manual_required':bool(check.get('critical') and not check.get('calibrated',False))})
            except Exception:
                # Provider error bodies may contain secrets or business content; do not persist them.
                for check in group:check.update({'result':'insufficient_evidence','error':'grading_error','reason':'裁判请求或结构化核验失败；未将其当作业务失败或通过'})
        graded['grading_error']=any(check.get('error')=='grading_error' for check in graded['checks'])
    def _append(self,c,ex,cases,reason,operation_id,request=None,expected=None,usage=None):
        request_hash=digest(request or {'experiment_id':ex['id'],'reason':reason})
        receipt=c.execute(text('SELECT request_hash,response FROM receipts WHERE operation_id=:id'),{'id':operation_id}).first()
        if receipt:
            if receipt[0]!=request_hash:raise DomainError('operation_conflict','同一操作键内容不同',409)
            return json.loads(receipt[1])
        current=self.repo.experiment(ex['id'],c)
        if expected is not None and current['current_revision_id']!=expected:raise DomainError('revision_conflict','报告已有新修订，请刷新后再提交',409)
        summary,gate=summarize(cases,drift=bool(ex['manifest'].get('configuration_drift',False)))
        report={'experiment_id':ex['id'],'revision_id':uid(),'previous_revision_id':current['current_revision_id'],'name':ex['name'],'source':ex['source'],'status':current['status'],'initial_terminal_status':current.get('initial_terminal_status'),'manifest':copy.deepcopy(ex['manifest']),'cases':copy.deepcopy(cases),'summary':summary,'gate':gate,'reason':reason,'usage':usage or {'known_cost':None,'currency':None,'token_count':None,'coverage':{'known_calls':0,'total_calls':len(cases)},'note':'演示不产生模型调用费用' if ex['source']=='demo' else '外部消耗未提供；未知不记作零'},'created_at':now()}
        from .ledger import Ledger
        report['ledger_snapshot']=Ledger(self.repo).snapshot(ex['id'])
        report['id']=report['revision_id'];report['content_hash']=digest(report)
        self.repo.record(c,'report',report,report['id'])
        affected=c.execute(text('UPDATE experiments SET current_revision=:new WHERE id=:id AND current_revision IS :old'),{'new':report['id'],'id':ex['id'],'old':current['current_revision_id']}).rowcount
        if affected!=1:raise DomainError('revision_conflict','报告修订冲突',409)
        c.execute(text('INSERT INTO receipts VALUES(:id,:hash,:response)'),{'id':operation_id,'hash':request_hash,'response':canonical(report)})
        self.repo.event(c,ex['id'],'report_revision',{'revision_id':report['id'],'reason':reason});return report
    def report(self,id,revision='current',c=None):
        if revision=='current':revision=self.repo.experiment(id,c)['current_revision_id']
        if not revision:raise DomainError('report_pending','实验尚未生成报告',409)
        report=self.repo.get(revision,'report',c)
        if report['experiment_id']!=id:raise DomainError('not_found','修订不属于此实验',404)
        return report
    def review(self,data):
        with self.repo.write() as c:
            ex=self.repo.experiment(data['experiment_id'],c)
            if ex.get('read_only_archive'):raise DomainError('archive_readonly','导入归档只读，不能改判')
            old=self.report(ex['id'],data['expected_revision_id'],c);cases=copy.deepcopy(old['cases'])
            target=next((x for x in cases if x['case_id']==data['case_id']),None)
            if not target:raise DomainError('not_found','题目不存在',404)
            check=next((x for x in target['checks'] if x['id']==data['check_id']),None)
            if not check:raise DomainError('not_found','检查项不存在',404)
            result=data['result']
            if result not in ('pass','fail','insufficient_evidence'):raise DomainError('invalid_result','不支持该复核结论')
            if not data.get('reason','').strip():raise DomainError('missing_reason','复核必须填写理由')
            refs=data.get('evidence_refs',[]);valid={e['id'] for e in target['evidence'] if e['state']=='parsed'}
            if result in ('pass','fail') and (not refs or not set(refs)<=valid):raise DomainError('evidence_required','复核通过或失败须引用本次尝试的有效证据')
            if result=='pass' and (target['status']!='succeeded' or check.get('error')):raise DomainError('evidence_required','执行或判分缺口不能通过人工确认绕过')
            check.setdefault('automatic_result',check['result']);check.update({'result':result,'reason':data['reason'],'reviewed':True,'origin':'human','evidence_refs':refs})
            target['review_history'].append({'id':uid(),'check_id':check['id'],'previous_check':copy.deepcopy(next(x for x in next(y for y in old['cases'] if y['case_id']==target['case_id'])['checks'] if x['id']==check['id'])),'old_result':next(x for x in old['cases'] if x['case_id']==target['case_id'])['checks'],'result':result,'reason':data['reason'],'reviewer':'本地维护者（未组织认证）','created_at':now()})
            return self._append(c,ex,cases,'human-review',data['operation_id'],data,expected=data['expected_revision_id'],usage=old['usage'])
    def regrade(self,id,expected,operation):
        with self.repo.write() as c:
            ex=self.repo.experiment(id,c)
            if ex.get('read_only_archive'):raise DomainError('archive_readonly','导入归档只读，不能重评')
            old=self.report(id,expected,c);ds=self.repo.get(ex['dataset_id'],'dataset',c);lookup={x['case_id']:x for x in ds['cases']};cases=[]
            for previous in old['cases']:
                fresh=self.grade_case(lookup[previous['case_id']],{'status':previous['status'],'output':previous['output']},previous['attempts'][0])
                fresh['evidence']=previous['evidence']
                for check in fresh['checks']:
                    check['evidence_refs']=[e['id'] for e in previous['evidence']]
                    human=next((x for x in previous['checks'] if x['id']==check['id'] and x.get('reviewed')),None)
                    if human:check.update(human)
                fresh['review_history']=previous['review_history'];cases.append(fresh)
            return self.repo.record(c,'grading_candidate',{'experiment_id':id,'base_revision_id':expected,'cases':cases,'usage':old['usage'],'status':'candidate','operation_id':operation})
    def observe_usage(self,experiment_id,data):
        from decimal import Decimal,InvalidOperation
        operation=data.get('operation_id');charge_id=data.get('charge_id')
        if not operation or not charge_id:raise DomainError('invalid_usage','消耗观察必须提供操作键和费用项 ID')
        amount=data.get('amount');currency=data.get('currency')
        if amount is not None:
            try:value=Decimal(str(amount))
            except InvalidOperation:raise DomainError('invalid_usage','费用格式错误')
            if not value.is_finite() or value<0 or not currency:raise DomainError('invalid_usage','费用必须为非负有限数，并提供币种')
        tokens=data.get('token_count')
        if tokens is not None and (not isinstance(tokens,int) or isinstance(tokens,bool) or tokens<0):raise DomainError('invalid_usage','Token 必须为非负整数或未知')
        with self.repo.write() as c:
            ex=self.repo.experiment(experiment_id,c);request={'experiment_id':experiment_id,**data}
            receipt=c.execute(text('SELECT request_hash,response FROM receipts WHERE operation_id=:id'),{'id':operation}).first()
            if receipt:
                if receipt[0]!=digest(request):raise DomainError('operation_conflict','同一费用操作内容不同',409)
                return json.loads(receipt[1])
            old=self.report(experiment_id,'current',c)
            observation=self.repo.record(c,'usage_observation',{'experiment_id':experiment_id,'charge_id':charge_id,'amount':str(amount) if amount is not None else None,'currency':currency,'token_count':tokens,'kind':data.get('kind','external'),'source':data.get('source','imported-observation')})
            selected={x['charge_id']:x for x in old['usage'].get('observations',[])};selected[charge_id]=observation
            currencies={x['currency'] for x in selected.values() if x.get('amount') is not None}
            by_currency={code:str(sum((Decimal(x['amount']) for x in selected.values() if x.get('currency')==code and x.get('amount') is not None),Decimal(0))) for code in currencies}
            usage={'observations':list(selected.values()),'known_cost':float(next(iter(by_currency.values()))) if len(by_currency)==1 else None,'currency':next(iter(currencies)) if len(currencies)==1 else None,'by_currency':by_currency,'token_count':sum(x['token_count'] for x in selected.values() if x.get('token_count') is not None) if any(x.get('token_count') is not None for x in selected.values()) else None,'coverage':{'known_calls':sum(x.get('amount') is not None for x in selected.values()),'total_calls':len(selected)},'note':'导入的费用观察；未知与实收/估算范围须结合原始记录查看'}
            return self._append(c,ex,copy.deepcopy(old['cases']),'usage-observation',operation,request,usage=usage)
    def undo_review(self,data):
        with self.repo.write() as c:
            ex=self.repo.experiment(data['experiment_id'],c)
            if ex.get('read_only_archive'):raise DomainError('archive_readonly','导入归档只读，不能改判')
            old=self.report(ex['id'],data['expected_revision_id'],c);cases=copy.deepcopy(old['cases'])
            target=next((x for x in cases if x['case_id']==data['case_id']),None)
            if not target:raise DomainError('not_found','题目不存在',404)
            events=[x for x in target['review_history'] if x['check_id']==data['check_id'] and not x.get('undone')]
            if not events:raise DomainError('no_review','没有可撤销的复核')
            previous=events[-1].get('previous_check')
            if not previous:raise DomainError('no_previous_result','该历史复核未保存可恢复的结果')
            for index,check in enumerate(target['checks']):
                if check['id']==data['check_id']:target['checks'][index]=copy.deepcopy(previous)
            events[-1]['undone']=True
            target['review_history'].append({'id':uid(),'check_id':data['check_id'],'action':'undo','reason':data.get('reason','撤销复核'),'created_at':now(),'undone':True})
            return self._append(c,ex,cases,'undo-review',data['operation_id'],data,expected=data['expected_revision_id'],usage=old['usage'])
    def adopt_grading(self,candidate_id,data):
        with self.repo.write() as c:
            candidate=self.repo.get(candidate_id,'grading_candidate',c);ex=self.repo.experiment(candidate['experiment_id'],c)
            old=self.report(ex['id'],data['expected_revision_id'],c);cases=copy.deepcopy(candidate['cases'])
            if candidate['base_revision_id']!=old['id']:raise DomainError('revision_conflict','候选基于旧修订，请重新评分或复核',409)
            for case in cases:
                prior=next(x for x in old['cases'] if x['case_id']==case['case_id'])
                for check in case['checks']:
                    human=next((x for x in prior['checks'] if x['id']==check['id'] and x.get('reviewed')),None)
                    if human:check.update(human)
            return self._append(c,ex,cases,'adopt-grading',data['operation_id'],data,expected=data['expected_revision_id'],usage=old['usage'])
    def insights(self,id,revision='current'):
        import re
        ex=self.repo.experiment(id);report=self.report(id,revision)
        skill_version=None;skill_line=None
        if ex.get('object_id'):
            try:
                obj=self.repo.get(ex['object_id'],'object')
                version=next((v for v in obj['versions'] if v['id']==ex.get('skill_version_id')),obj['versions'][-1])
                skill_version=version.get('version')
                for index,line in enumerate(version.get('content','').splitlines(),1):
                    if re.search(r'\d+\s*(小时|天|分钟|%)',line):skill_line=index;break
            except DomainError:pass
        groups={}
        for case in report['cases']:
            for check in case.get('checks',[]):
                if check.get('applicable',True) and check.get('result')=='fail' and not check.get('error'):
                    group=groups.setdefault(check['id'],{'check_id':check['id'],'title':check.get('name') or check['id'],'dimension':check.get('dimension'),'critical':bool(check.get('critical')),'cases':[],'reasons':[]})
                    group['cases'].append(case['case_id'])
                    if check.get('reason') and check['reason'] not in group['reasons']:group['reasons'].append(check['reason'])
        suggestions=[]
        for group in groups.values():
            suggestions.append({'id':group['check_id'],'priority':'P0' if group['critical'] else 'P1','title':group['title'],'dimension':DIMENSIONS.get(group['dimension'],group['dimension']),'recommendation':'对照权威政策复核该检查对应的 Skill 指令，修正后以同一评测集重新评测。','cases':group['cases'],'case_count':len(group['cases']),'reasons':group['reasons'][:3],'related_file':'SKILL.md' if skill_version else None,'related_version':skill_version,'related_line':skill_line,'line_verified':False})
        suggestions.sort(key=lambda item:(item['priority'],-item['case_count'],item['title']))
        return {'experiment_id':id,'revision_id':report['revision_id'],'source':report.get('source'),'suggestions':suggestions,'note':'建议基于固定报告修订自动汇总；文件行号为关键词定位结果，需人工确认后再修改 Skill。'}
    def compare(self,data):
        left=self.report(data['left_experiment_id'],data.get('left_revision_id') or 'current');right=self.report(data['right_experiment_id'],data.get('right_revision_id') or 'current')
        blockers=compare_manifests(left['manifest'],right['manifest']);pairs=[]
        lmap={(x['case_id'],x['case_version'],x['content_hash']):x for x in left['cases']};rmap={(x['case_id'],x['case_version'],x['content_hash']):x for x in right['cases']}
        for key in sorted(set(lmap)|set(rmap)):
            a=lmap.get(key);b=rmap.get(key)
            if a and b and {(x['id'],bool(x.get('reviewed'))) for x in a['checks']}!={(x['id'],bool(x.get('reviewed'))) for x in b['checks']}:blockers.append('两边人工复核口径不同：'+key[0])
            change='incomparable'
            if a and b and a['conclusion']!='inconclusive' and b['conclusion']!='inconclusive':
                change='improved' if a['conclusion']=='not_passed' and b['conclusion']=='passed' else 'regressed' if a['conclusion']=='passed' and b['conclusion']=='not_passed' else 'unchanged'
            checks=[]
            if a and b:
                left_checks={x['id']:x for x in a['checks']};right_checks={x['id']:x for x in b['checks']}
                for check_id in sorted(set(left_checks)|set(right_checks)):
                    lc=left_checks.get(check_id);rc=right_checks.get(check_id)
                    checks.append({'id':check_id,'name':(lc or rc or {}).get('name'),'left':lc.get('result') if lc else None,'right':rc.get('result') if rc else None,'change':'changed' if (lc or {}).get('result')!=(rc or {}).get('result') else 'unchanged'})
            pairs.append({'case_id':key[0],'case_version':key[1],'content_hash':key[2],'tags':(a or b or {}).get('tags',[]),'left':a['conclusion'] if a else None,'right':b['conclusion'] if b else None,'left_output':a.get('output') if a else None,'right_output':b.get('output') if b else None,'checks':checks,'change':change})
        blockers=list(dict.fromkeys(blockers));eligible=not blockers
        coverage={'left_case_count':len(left['cases']),'right_case_count':len(right['cases']),'paired':sum(1 for x in pairs if x['left'] is not None and x['right'] is not None),'left_only':sum(1 for x in pairs if x['right'] is None),'right_only':sum(1 for x in pairs if x['left'] is None),'comparable':sum(1 for x in pairs if x['change'] in ('improved','regressed','unchanged')) if eligible else 0}
        if not eligible:
            for pair in pairs:pair['descriptive_change']=pair['change'];pair['change']='incomparable'
        return {'strict_eligible':eligible,'blockers':blockers,'differences':[{'field':k,'left':left['manifest'].get(k),'right':right['manifest'].get(k)} for k in sorted(set(left['manifest'])|set(right['manifest'])) if left['manifest'].get(k)!=right['manifest'].get(k)],'pairs':pairs,'coverage':coverage,'summary':{kind:sum(x['change']==kind for x in pairs) for kind in ('improved','regressed','unchanged','incomparable')},'left':left,'right':right,'note':'仅说明本次固定样本表现，不代表生产效果或稳定因果提升','projection_version':'comparison_manifest-v1'}
