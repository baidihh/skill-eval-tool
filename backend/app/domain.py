"""Pure evaluation rules shared by reports, exports and comparisons."""
import copy
import hashlib
import json

DIMENSIONS = {
 'completion':'任务完成度','correctness':'结果正确性','constraints':'约束遵守度',
 'skill_adherence':'Skill 遵循度','evidence':'证据可靠性','robustness':'过程稳健度'
}

def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)

def digest(value):
    return hashlib.sha256(('canonical-json-v1\n'+canonical(value)).encode()).hexdigest()

def rate(n,d):
    return {'numerator':n,'denominator':d,'percent':round(100*n/d,1) if d else None}

def summarize(cases, drift=False):
    total=len(cases); counts={'passed':0,'not_passed':0,'inconclusive':0}
    complete=success=critical=0
    dimensions={key:{'name':label,'pass':0,'fail':0,'insufficient_evidence':0,'not_applicable':0,'grading_error':0,'enabled':0} for key,label in DIMENSIONS.items()}
    for case in cases:
        checks=[c for c in case.get('checks',[]) if c.get('required',True) and c.get('applicable',True)]
        success+=case['status']=='succeeded'
        failed=any(c.get('result')=='fail' and not c.get('error') and (not c.get('manual_required') or c.get('reviewed')) for c in checks)
        full=bool(checks) and case['status']=='succeeded' and not case.get('grading_error') and not case.get('data_error') and all(c.get('result') in ('pass','fail') and (not c.get('manual_required') or c.get('reviewed')) for c in checks)
        passed=full and all(c.get('result')=='pass' for c in checks)
        conclusion='not_passed' if failed else 'passed' if passed else 'inconclusive'
        case['conclusion']=conclusion; case['complete']=full
        counts[conclusion]+=1; complete+=full
        for c in case.get('checks',[]):
            critical+=bool(c.get('critical') and c.get('applicable',True) and not c.get('error') and c.get('result')=='fail' and (not c.get('manual_required') or c.get('reviewed')))
            dim=dimensions.setdefault(c['dimension'],{'name':c['dimension'],'pass':0,'fail':0,'insufficient_evidence':0,'not_applicable':0,'grading_error':0,'enabled':0})
            dim['enabled']+=1
            result=c.get('result','insufficient_evidence')
            dim[result]=dim.get(result,0)+1
    scores=[]
    for dim in dimensions.values():
        graded=dim.get('pass',0)+dim.get('fail',0)
        dim['graded']=graded
        dim['score']=round(100*dim['pass']/graded,1) if graded else None
        if dim['score'] is not None:scores.append(dim['score'])
    composite=round(sum(scores)/len(scores),1) if scores else None
    summary={**counts,'total':total,'critical_failures':critical,'dimensions':dimensions,
      'composite_score':{'value':composite,'dimensions_counted':len(scores),'note':'仅汇总存在已判定检查的维度，用于界面展示，不参与门禁判定'},
      'execution_success_rate':rate(success,total),'determined_coverage':rate(counts['passed']+counts['not_passed'],total),
      'complete_coverage':rate(complete,total),'all_sample_pass_rate':rate(counts['passed'],total),
      'determined_pass_rate':rate(counts['passed'],counts['passed']+counts['not_passed'])}
    gate='not_passed' if counts['not_passed'] else 'passed' if total and counts['passed']==total and complete==total and not drift else 'inconclusive'
    return summary,gate

# This whitelist is deliberately narrow. Unclassified behavior fields block strict comparison.
BEHAVIOR_FIELDS={'source','target_skill','skills','model','system_prompt','verified','dataset_hash','policy','generation_parameters','tools','environment','memory','initial_state','judge','limits','attempt_selection','evaluation_time','authoritative_policy_hash','trigger_mode','extensions'}
IGNORED_IDENTITIES={'expert_id','snapshot_id','captured_at','object_id','skill_version_id'}

def project_manifest(manifest):
    blockers=[]
    for key in set(manifest)-BEHAVIOR_FIELDS-IGNORED_IDENTITIES:
        blockers.append('未分类的行为字段：'+key)
    required=('source','target_skill','skills','model','system_prompt','dataset_hash','policy','generation_parameters','tools','environment','memory','initial_state','judge','limits','attempt_selection','evaluation_time','authoritative_policy_hash','trigger_mode')
    for key in required:
        if key not in manifest or manifest[key] is None: blockers.append('必要配置未知：'+key)
    if not manifest.get('verified'): blockers.append('专家行为配置未经核验')
    def has_unknown(value):
        if value is None:return True
        if isinstance(value,dict):return value.get('state')=='unknown' or any(has_unknown(v) for v in value.values())
        if isinstance(value,list):return any(has_unknown(v) for v in value)
        return value=='unknown'
    for key in required:
        if key in manifest and has_unknown(manifest[key]):blockers.append('必要行为条件未核实：'+key)
    if manifest.get('extensions'): blockers.append('存在未分类的行为扩展')
    result={key:copy.deepcopy(manifest[key]) for key in BEHAVIOR_FIELDS if key in manifest}
    skills=result.get('skills',[])
    slots=[i for i,skill in enumerate(skills) if skill.get('name')==manifest.get('target_skill')]
    if len(slots)!=1: blockers.append('目标 Skill 槽位无法唯一确定')
    else:
        slot=skills[slots[0]]
        result['skills'][slots[0]]={key:value for key,value in slot.items() if key not in ('version','hash','version_id','id')}
        result['skills'][slots[0]]['package']='TARGET_PACKAGE'
    return result,blockers

def compare_manifests(left,right):
    a,ab=project_manifest(left); b,bb=project_manifest(right)
    blockers=list(dict.fromkeys(ab+bb))
    for key in sorted(set(a)|set(b)):
        if a.get(key)!=b.get(key): blockers.append('对照条件不同：'+key)
    return blockers
