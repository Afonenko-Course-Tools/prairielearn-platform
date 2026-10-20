import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {assignedSlots,completion,validateNativeGroups,BridgeError} from '../../bridge/policy.mjs';
const source=await readFile(new URL('../../bridge/server.mjs',import.meta.url),'utf8');
const validateBody=source.slice(source.indexOf('async function validateWork('),source.indexOf('async function apply('));
const chain=source.slice(source.indexOf('async function nativeStudentWorkContext('),source.indexOf('async function workLaunch('));
const work={id:'lab',slots:[{id:'fixture/lab/exr-q1',selection:'fixed',candidates:['fixture/q1'],assignment:{requirement:'required',workMode:'individual'}}],completion:{slotIds:['fixture/lab/exr-q1'],requiredSlotIds:['fixture/lab/exr-q1'],atLeast:1,fullyCompletedScore:1}};
const groups=[{group_id:'7',question_ids:['fixture/q1'],number_choose:null,zone_number_choose:null,zone_number_choose:null,zone_best_questions:null}];
const request={userUid:'u',instance:'fixture',deliveryHash:'a'.repeat(64),workId:'lab'};
const shape=new Proxy(()=>shape,{get:()=>shape,apply:()=>shape});
const z=new Proxy({},{get:()=>shape});
for (const started of [false,true]) {
 const attempt={id:'100',number:1};let groupsRead=0,resultsRead=0;
 const db={queryRows:async sql=>{if(sql==='groups'){groupsRead++;return groups;}resultsRead++;return [{attempt_id:'100',attempt_number:1,group_id:'7',qualified_id:'fixture/q1',points:1,max_points:1,score:1,native_status:'complete',requires_manual_grading:false,attempt_points:1,attempt_max_points:1}];},queryOptionalRow:async()=>started?{attempt}:null};
 const context=async()=>({binding:{delivery:{instances:{fixture:{works:['lab']}},works:[work]}},ci:{id:'1',modern_publishing:true},user:{id:'2',uid:'u'}});
 const enrollment={selectOptionalEnrollmentByUserId:async()=>({status:'joined'})};
 const access={resolveModernAssessmentAccess:async()=>({authorized:true}),resolveModernAssessmentInstanceAccess:async()=>({authorized:true})};
 const select={selectAssessmentByTid:async()=>({modern_access_control:true,team_work:false})};
 const args={db,sql:{validate_assessment:'groups',select_work_attempt:'attempt',select_work_results:'results'},z,validateNativeGroups,context,BridgeError,enrollments:enrollment,system:{},assignmentRow:{},labels:{},studentAccess:{calculateModernCourseInstanceStudentAccess:async()=>({has_student_access_with_enrollment:true})},nativeAssessment:select,AssessmentInstanceSchema:{},assessmentAccess:access,workResultRow:{},assignedSlots,completion};
 const run=new Function(...Object.keys(args),validateBody+chain+';return workResults;')(...Object.values(args));
 const result=await run(request);
 assert.equal(groupsRead,1);assert.equal(resultsRead,started?1:0);
 assert.equal(result.state,started?'started':'not-started');assert.equal(result.completion.requiredCount,1);
 assert.equal(result.slots.length,started?1:0);assert.equal(result.completion.passed,started);
}
console.log('PASS real work context carries validated native group inventory to started/not-started results');
