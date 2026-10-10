#!/usr/bin/env python3
"""Inspect explicit verification evidence without claiming live PL/Moodle success."""
import argparse,json
from pathlib import Path
from grading_job import validate_receipt_integrity,JobError

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--report',required=True,type=Path);a=p.parse_args()
 try:
  report=json.loads(a.report.read_text());receipt=report['receipt'];validate_receipt_integrity(receipt)
  if receipt['exitCode']!=0:return receipt['exitCode']
  if receipt['coverage']!='complete':
   print('Partial diagnostic verification receipt; release coverage is incomplete.')
   return 1
  print('Verification receipt valid. Native PL sync, Student ACL, and Moodle launch/AGS require separate live evidence.')
  return 0
 except (JobError,KeyError,OSError,ValueError) as error:p.exit(2,str(error)+'\n')
if __name__=='__main__':raise SystemExit(main())
