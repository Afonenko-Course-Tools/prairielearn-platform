#!/usr/bin/env python3
"""Inventory and explicitly verify declared checks; never auto-discover projects."""
import argparse
import json
import tempfile
from pathlib import Path
from typing import Literal
from delivery_verification import classification,package_integrity
from delivery4 import code_ids
from delivery_types import GradingMethod
from grading_types import CheckResult, Expectations, UnavailableReference
from grading_job import JobError,ProjectDefect,inventory,prepare_job,run_job,verify_results,scenario_inventory,preserve_build_logs,cleanup_job
from json_boundary import json_object

class _Options(argparse.Namespace):
 command: Literal['inventory', 'verify']
 ready_only: bool
 manifest: Path
 snapshot: Path | None
 scope: Literal['declared', 'delivery']
 delivery: Path | None
 backend: Literal['host', 'container']
 id: list[str] | None
 scenario: list[str] | None
 output: Path
 runtime_registry: Path | None

def save_report(output: Path, report: dict[str, object]) -> None:
 """Атомарно заменить только штатный отчёт, сохраняя прежний при обрыве записи."""
 output.parent.mkdir(parents=True, exist_ok=True)
 pending: Path | None = None
 try:
  with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=output.parent,
                                  prefix='.' + output.name + '-', delete=False) as stream:
   pending = Path(stream.name)
   stream.write(json.dumps(report, sort_keys=True, indent=2) + '\n')
  pending.replace(output)
 finally:
  if pending is not None:
   pending.unlink(missing_ok=True)

def main() -> int:
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',nargs='?',default='verify',choices=['inventory','verify']);p.add_argument('--inventory',dest='command',action='store_const',const='inventory');p.add_argument('--ready-only',action='store_true');p.add_argument('--manifest',required=True,type=Path);p.add_argument('--snapshot',type=Path);p.add_argument('--scope',choices=['declared','delivery'],default='declared');p.add_argument('--delivery',type=Path);p.add_argument('--backend',choices=['host','container'],default='container');p.add_argument('--id',action='append');p.add_argument('--scenario',action='append');p.add_argument('--output',required=True,type=Path);p.add_argument('--runtime-registry',type=Path);a=p.parse_args(namespace=_Options())
 report: dict[str, object] = {}
 methods: dict[str, GradingMethod] = {}
 auto_ids: set[str] = set()
 try:
  registry: object=json.loads(a.runtime_registry.read_text()) if a.runtime_registry else None
  m=json_object(json.loads(a.manifest.read_text()));projects=inventory(m)
  delivery=json_object(json.loads(a.delivery.read_text())) if a.delivery else None
  if a.scope=='delivery':
   if not delivery or a.delivery is None:raise JobError('--delivery is required for delivery scope')
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
   job_delivery: dict[str, object] | None = None
   if delivery is not None:
    if a.delivery is None:raise JobError('--delivery path is required')
    job_delivery=dict(delivery,_root=str(a.delivery.parent.resolve()))
   required_ids=sorted(auto_ids) if a.scope=='delivery' and delivery else [x['qualifiedId'] for x in selected]
   required=scenario_inventory(m,a.snapshot,required_ids)
   results: list[CheckResult]=[];report['results']=results
   expectations: dict[str, Expectations]={}
   unavailable: list[UnavailableReference]=[]
   remaining=[{'qualifiedId':project['qualifiedId'],'scenario':scenario}
              for project in selected
              for scenario in (a.scenario or [x['scenario'] for x in required if x['qualifiedId']==project['qualifiedId']])]
   report.update(coverage='partial',remaining=remaining,unavailable=unavailable)
   save_report(a.output, report)
   for project in selected:
    scenarios=a.scenario or [x['scenario'] for x in required if x['qualifiedId']==project['qualifiedId']]
    for scenario in scenarios:
     project_manifest: dict[str, object]=dict(m)
     project_manifest['projects']=[project]
     try:job=prepare_job(project_manifest,a.snapshot,project['qualifiedId'],scenario,a.scope,job_delivery,registry)
     except JobError as error:
      if str(error).startswith('reference-unavailable:'):
       unavailable.append({'qualifiedId':project['qualifiedId'],'scenario':scenario,'status':'reference-unavailable'})
       remaining.pop(0);save_report(a.output, report);continue
      raise
     interrupted=False
     try:
      results.append(run_job(job,a.backend,registry))
      payload=job.checked_payload()
      if 'expectations' not in payload:raise KeyError('expectations')
      expectations[project['qualifiedId']+':'+scenario]=payload['expectations']
      remaining.pop(0);save_report(a.output, report)
     except KeyboardInterrupt:
      interrupted=True
      raise
     finally:
      try:
       try:preserve_build_logs(job,a.output)
       except Exception as error:
        if not interrupted:raise
        report['logPreservationError']=str(error)
      finally:
       try:cleanup_job(job,a.backend)
       except KeyboardInterrupt as error:
        report['cleanupRequired']={'qualifiedId':project['qualifiedId'],'scenario':scenario,
                                   'scratch':str(job.root),'error':str(error)}
        raise
       except Exception as error:
        if not interrupted:raise
        report['cleanupRequired']={'qualifiedId':project['qualifiedId'],'scenario':scenario,
                                   'scratch':str(job.root),'error':str(error)}
   if a.scope=='delivery' and not auto_ids:
    if delivery is None:raise JobError('--delivery is required for delivery scope')
    report.update(automatic={'state':'not-applicable','reason':'all-questions-manual' if delivery['schemaVersion']==3 else 'no-project-automatic'},results=[])
    if a.scenario or a.id and set(a.id)!=set(methods):report.update(coverage='partial');status=1
    else:report.pop('coverage',None);status=0
   elif not results:
    report.update(coverage='partial',automatic={'state':'not-verified','reason':'partial-selection'},results=[]);status=1
   else:
    summary=verify_results(results,expectations,required,unavailable,registry);report.pop('coverage',None);report.update(results=results,summary=summary,unavailable=unavailable);status=summary['exitCode']
 except KeyboardInterrupt:report.update(error='Проверка прервана; остаток не исполнен',classification='interrupted',coverage='partial');status=130
 except ProjectDefect as error:report.update(error=str(error),classification='project-defect');status=1
 except (JobError,OSError,ValueError,KeyError) as error:report.update(error=str(error),classification='infrastructure-failure');status=2
 save_report(a.output, report);return status
if __name__=='__main__':raise SystemExit(main())
