import assert from 'node:assert/strict';
import test from 'node:test';
import {assignedSlots,completion,validateNativeGroups} from '../../bridge/policy.mjs';
const work={id:'lab',slots:[{id:'demo/lab/alt-books',selection:'choice',candidates:['demo/exr-a','demo/exr-b'],assignment:{requirement:'required',workMode:'individual'}}],completion:{slotIds:['demo/lab/alt-books'],requiredSlotIds:['demo/lab/alt-books'],atLeast:1,fullyCompletedScore:1}};
const attempt={id:'attempt',number:1};
const groups=[{group_id:'1',zone_id:'z-choice',number_choose:null,zone_number_choose:null,zone_best_questions:1,question_ids:['demo/exr-a']},{group_id:'2',zone_id:'z-choice',number_choose:null,zone_number_choose:null,zone_best_questions:1,question_ids:['demo/exr-b']}];
const rows=(a,b)=>[a,b].map((score,i)=>({attempt_id:'attempt',attempt_number:1,group_id:String(i+1),qualified_id:'demo/exr-'+(i?'b':'a'),points:score*2,max_points:2,score,native_status:'correct',requires_manual_grading:false}));
test('choice checks both native candidates and counts only one fully accepted alternative',()=>{
 for(const [a,b,count] of [[.5,.5,0],[1,.5,1],[0,1,1],[1,1,1]]){
  const result=assignedSlots(work,rows(a,b),attempt,groups);assert.equal(result.length,1);assert.equal(result[0].score,Math.max(a,b));assert.equal(result[0].maxPoints,2);assert.equal(result[0].points,Math.max(a,b)*2);assert.equal(completion(work,result).completedRequired,count);
  assert.deepEqual(assignedSlots(work,rows(a,b).reverse(),attempt,groups),result,'DB order must not pick a representative');
 }
});
test('pending teacher blocks automatic full acceptance unless another choice is fully complete',()=>{
 let r=rows(1,.5);r[0].requires_manual_grading=true;let result=assignedSlots(work,r,attempt,groups);assert.equal(result[0].status,'grading');assert.equal(completion(work,result).passed,false);
 r=rows(1,1);r[0].requires_manual_grading=true;result=assignedSlots(work,r,attempt,groups);assert.equal(result[0].qualifiedId,'demo/exr-b');assert.equal(completion(work,result).passed,true);
});
test('choice rejects missing/extra/foreign/duplicate candidates and native zone weakening',()=>{
 const originals=rows(.5,.5);
 for(const bad of [[originals[0]],[...originals,originals[0]],[originals[0],{...originals[1],qualified_id:'demo/exr-foreign'}],[originals[0],{...originals[1],group_id:'1'}],[originals[0],{...originals[1],attempt_number:2}],[originals[0],{...originals[1],score:NaN}],[originals[0],{...originals[1],native_status:'FOREIGN_STATUS'}],[originals[0],{...originals[1],requires_manual_grading:null}],[originals[0],{...originals[1],max_points:3}]])assert.throws(()=>assignedSlots(work,bad,attempt,groups));
 for(const bad of [groups.slice(0,1),groups.map(g=>({...g,zone_best_questions:null})),groups.map(g=>({...g,zone_number_choose:1})),[groups[0],{...groups[1],zone_id:'another'}],[...groups,{...groups[0],group_id:'3',question_ids:['demo/exr-c']}],groups.map(g=>({...g,number_choose:2}))])assert.throws(()=>validateNativeGroups(work,bad));
});
test('choice public row never borrows pending status from another candidate',()=>{
 const candidates=rows(.8,.5);candidates[1].requires_manual_grading=true;
 const [result]=assignedSlots(work,candidates,attempt,groups);
 const source=candidates.find(row=>row.qualified_id===result.qualifiedId);
 assert.equal(result.status,source.requires_manual_grading?'grading':'complete','representative fields must describe the same actual candidate');
});

test('pending loser leaves numeric winner exact; pending winner remains pending',()=>{
 for(const [a,b,pending,expectedId,status,passed] of [[.6,.2,1,'demo/exr-a','complete',false],[.6,.8,1,'demo/exr-b','grading',false],[1,.8,1,'demo/exr-a','complete',true]]){
  const values=rows(a,b);values[pending].requires_manual_grading=true;const selected=assignedSlots(work,values,attempt,groups);
  assert.equal(selected[0].qualifiedId,expectedId);assert.equal(selected[0].status,status);assert.equal(completion(work,selected).passed,passed);
  assert.deepEqual(assignedSlots(work,values.reverse(),attempt,groups),selected);
 }
});
