#!/usr/bin/env python3
"""Inventory and explicitly verify declared checks; never auto-discover projects."""
import argparse
import json
from pathlib import Path
import shutil
from delivery_verification import classification,package_integrity,delivery_receipt
from delivery4 import code_ids
from grading_job import JobError,ProjectDefect,inventory,prepare_job,run_job,verify_results,safe,validate,scenario_inventory,preserve_build_logs

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',nargs='?',default='verify',choices=['inventory','verify']);p.add_argument('--inventory',dest='command',action='store_const',const='inventory');p.add_argument('--ready-only',action='store_true');p.add_argument('--manifest',required=True,type=Path);p.add_argument('--snapshot',type=Path);p.add_argument('--scope',choices=['declared','delivery'],default='declared');p.add_argument('--delivery',type=Path);p.add_argument('--backend',choices=['host','container'],default='container');p.add_argument('--id',action='append');p.add_argument('--scenario',action='append');p.add_argument('--output',required=True,type=Path);p.add_argument('--runtime-registry',type=Path);a=p.parse_args()
 report={}
 try:
  registry=json.loads(a.runtime_registry.read_text()) if a.runtime_registry else None
  m=json.loads(a.manifest.read_text());projects=inventory(m)
  delivery=json.loads(a.delivery.read_text()) if a.delivery else None
  if a.scope=='delivery':
   if not delivery:raise JobError('--delivery is required for delivery scope')
   methods=classification(delivery);auto_ids=code_ids(delivery)
   report['packageIntegrity']=package_integrity(delivery,a.delivery.parent,m)
   if a.id and set(a.id)-set(methods):raise JobError('Unknown selected delivery ID')
   projects=[x for x in projects if x['qualifiedId'] in auto_ids]
  if a.ready_only and a.scope!='declared':raise JobError('--ready-only is permitted only for declared scope')
  if a.ready_only:projects=[x for x in projects if x.get('readiness',{}).get('ready',bool(x.get('sources') and x.get('trustedTests')))]
  selected=[x for x in projects if not a.id or x['qualifiedId'] in a.id]
  if a.scope!='delivery' and a.id and set(a.id)-{x['qualifiedId'] for x in selected}:raise JobError('Unknown selected ID')
  report['inventory']=[{'qualifiedId':x['qualifiedId'],'projectRoot':x['projectRoot'],'runtime':x['check'].get('runtime'),'readiness':x.get('readiness',{'ready':bool(x.get('sources') and x.get('trustedTests')),'missing':[]})} for x in selected]
  if a.command=='inventory':status=0
  else:
   if not a.snapshot:raise JobError('--snapshot is required for verify')
   job_delivery=dict(delivery,_root=str(a.delivery.parent.resolve())) if delivery is not None else None
   required=scenario_inventory(m,a.snapshot,auto_ids if a.scope=='delivery' and delivery else {x['qualifiedId'] for x in selected})
   results=[];expectations={};unavailable=[];expected_jobs={}
   for project in selected:
    scenarios=a.scenario or [x['scenario'] for x in required if x['qualifiedId']==project['qualifiedId']]
    for scenario in scenarios:
     try:job=prepare_job(m,a.snapshot,project['qualifiedId'],scenario,a.scope,job_delivery,registry)
     except JobError as error:
      if str(error).startswith('reference-unavailable:'):unavailable.append({'qualifiedId':project['qualifiedId'],'scenario':scenario,'status':'reference-unavailable'});continue
      raise
     try:expected_jobs[(job['qualifiedId'],job['scenario'])]={**{field:dict(job[field]) for field in ('sourceHashes','testsHashes')},**({'jobSchemaVersion':2,'nativeSelectionScopeHash':job['nativeSelectionScopeHash']} if job['schemaVersion']==2 else {})};results.append(run_job(job,a.backend,registry));expectations[project['qualifiedId']+':'+scenario]=job['expectations']
     finally:
      try:preserve_build_logs(job,a.output)
      finally:shutil.rmtree(job.root)
   if a.scope=='delivery' and not auto_ids:
    report.update(automatic={'state':'not-applicable','reason':'all-questions-manual'},results=[])
    if a.scenario or a.id and set(a.id)!=set(methods):report.update(coverage='partial');status=1
    else:report['receipt']=delivery_receipt(delivery,a.delivery.parent,m,registry=registry);status=0
   elif not results:
    report.update(coverage='partial',automatic={'state':'not-verified','reason':'partial-selection'},results=[]);status=1
   else:
    receipt=verify_results(results,expectations,required,unavailable,registry,expected_jobs);report.update(results=results,receipt=receipt,unavailable=unavailable);status=receipt['exitCode']
    if a.scope=='delivery' and status==0 and receipt['coverage']=='complete' and a.backend=='container' and (not a.id or set(a.id)==set(methods)):
     report['receipt']=delivery_receipt(delivery,a.delivery.parent,m,receipt,registry)
    elif a.scope=='delivery':report['coverage']='partial'
 except ProjectDefect as error:report.update(error=str(error),classification='project-defect');status=1
 except (JobError,OSError,ValueError,KeyError) as error:report.update(error=str(error),classification='infrastructure-failure');status=2
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,sort_keys=True,indent=2)+'\n');return status
if __name__=='__main__':raise SystemExit(main())
