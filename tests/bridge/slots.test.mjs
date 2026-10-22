import assert from 'node:assert/strict';
import test from 'node:test';
import * as policy from '../../bridge/policy.mjs';
const slots=[{id:'demo/lab/alt-numbers',selection:'random',candidates:['demo/exr-a','demo/exr-b'],assignment:{requirement:'required',workMode:'individual'}},{id:'demo/lab/exr-c',selection:'fixed',candidates:['demo/exr-c'],assignment:{requirement:'optional',workMode:'individual'}}];
const work={id:'lab',slots,completion:{schemaVersion:2,mode:'required-slot-completion',source:'per-slot-results-v2',slotIds:slots.map(s=>s.id),requiredSlotIds:[slots[0].id],atLeast:1,fullyCompletedScore:1}};
const row=(group,id)=>({group_id:group,qualified_id:id,attempt_id:'42',attempt_number:1,score:1,points:1,max_points:1,native_status:'complete',requires_manual_grading:false});
const groups=[{group_id:'10',question_ids:slots[0].candidates,number_choose:1,zone_number_choose:null,zone_best_questions:null},{group_id:'11',question_ids:slots[1].candidates,number_choose:1,zone_number_choose:null,zone_best_questions:null}];
test('native group selected question maps to exactly one slot including singleton',()=>{
 const mapped=policy.assignedSlots(work,[row('10','demo/exr-b'),row('11','demo/exr-c')],{id:'42',number:1},groups);
 assert.equal(mapped.length,2);assert.equal(mapped[0].qualifiedId,'demo/exr-b');assert.equal(policy.completion(work,mapped).completedRequired,1);
 for(const bad of [[],[row('10','demo/exr-a')],[row('10','demo/exr-a'),row('10','demo/exr-b'),row('11','demo/exr-c')],[row('10','demo/exr-c'),row('11','demo/exr-c')],[{...row('10','demo/exr-a'),attempt_id:'43'},row('11','demo/exr-c')]])assert.throws(()=>policy.assignedSlots(work,bad,{id:'42',number:1},groups));
 assert.equal(policy.assignedSlots(work,[row('10','demo/exr-b'),row('11','demo/exr-c')],{id:'42',number:1},[groups[0],{...groups[1],number_choose:null,zone_number_choose:null,zone_best_questions:null}]).length,2);
 assert.deepEqual(policy.assignedSlots(work,[],null,groups),[]);
 assert.throws(()=>policy.assignedSlots(work,[row('10','demo/exr-a')],null,groups));
 assert.throws(()=>policy.validateNativeGroups(work,[{...groups[0],number_choose:2},groups[1]]));
 assert.throws(()=>policy.validateNativeGroups(work,[{...groups[0],question_ids:['demo/exr-a']},groups[1]]));
});
