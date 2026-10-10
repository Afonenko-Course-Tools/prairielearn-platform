#!/usr/bin/env python3
"""Inventory and explicitly verify declared checks; never auto-discover projects."""
import argparse
import json
from pathlib import Path
import shutil
from grading_job import JobError,ProjectDefect,inventory,prepare_job,run_job,verify_results,safe,validate,scenario_inventory

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',nargs='?',default='verify',choices=['inventory','verify']);p.add_argument('--inventory',dest='command',action='store_const',const='inventory');p.add_argument('--ready-only',action='store_true');p.add_argument('--manifest',required=True,type=Path);p.add_argument('--snapshot',type=Path);p.add_argument('--scope',choices=['declared','delivery'],default='declared');p.add_argument('--delivery',type=Path);p.add_argument('--backend',choices=['host','container'],default='container');p.add_argument('--id',action='append');p.add_argument('--scenario',action='append');p.add_argument('--output',required=True,type=Path);a=p.parse_args()
 report={}
 try:
  m=json.loads(a.manifest.read_text());projects=inventory(m)
  delivery=json.loads(a.delivery.read_text()) if a.delivery else None
  if a.scope=='delivery':
   if not delivery:raise JobError('--delivery is required for delivery scope')
   projects=[x for x in projects if x['qualifiedId'] in delivery['questions']]
  if a.ready_only and a.scope!='declared':raise JobError('--ready-only is permitted only for declared scope')
  if a.ready_only:projects=[x for x in projects if x.get('readiness',{}).get('ready',bool(x.get('sources') and x.get('trustedTests')))]
  selected=[x for x in projects if not a.id or x['qualifiedId'] in a.id]
  if a.id and set(a.id)-{x['qualifiedId'] for x in selected}:raise JobError('Unknown selected ID')
  report['inventory']=[{'qualifiedId':x['qualifiedId'],'projectRoot':x['projectRoot'],'runtime':x['check'].get('runtime'),'readiness':x.get('readiness',{'ready':bool(x.get('sources') and x.get('trustedTests')),'missing':[]})} for x in selected]
  if a.command=='inventory':status=0
  else:
   if not a.snapshot:raise JobError('--snapshot is required for verify')
   if delivery is not None:delivery['_root']=str(a.delivery.parent.resolve())
   required=scenario_inventory(m,a.snapshot,set(delivery['questions']) if a.scope=='delivery' and delivery else {x['qualifiedId'] for x in selected})
   results=[];expectations={};unavailable=[]
   for project in selected:
    scenarios=a.scenario or [x['scenario'] for x in required if x['qualifiedId']==project['qualifiedId']]
    for scenario in scenarios:
     try:job=prepare_job(m,a.snapshot,project['qualifiedId'],scenario,a.scope,delivery)
     except JobError as error:
      if str(error).startswith('reference-unavailable:'):unavailable.append({'qualifiedId':project['qualifiedId'],'scenario':scenario,'status':'reference-unavailable'});continue
      raise
     try:results.append(run_job(job,a.backend));expectations[project['qualifiedId']+':'+scenario]=job['expectations']
     finally:shutil.rmtree(job.root)
   receipt=verify_results(results,expectations,required,unavailable);report.update(results=results,receipt=receipt,unavailable=unavailable);status=receipt['exitCode']
 except ProjectDefect as error:report.update(error=str(error),classification='project-defect');status=1
 except (JobError,OSError,ValueError,KeyError) as error:report.update(error=str(error),classification='infrastructure-failure');status=2
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,sort_keys=True,indent=2)+'\n');return status
if __name__=='__main__':raise SystemExit(main())
