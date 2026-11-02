import {createHash} from 'node:crypto';import {mkdtemp,mkdir,writeFile,rm} from 'node:fs/promises';import {join} from 'node:path';import {tmpdir} from 'node:os';
import {canonicalJSONString} from '../../bridge/policy.mjs';
export const CI_UUID='11111111-1111-4111-8111-111111111111';
const sha=b=>createHash('sha256').update(b).digest('hex');
export async function deliveryFixture(workId='new-work'){
 const root=await mkdtemp(join(tmpdir(),'credit-delivery-'));const info=Buffer.from(JSON.stringify({uuid:CI_UUID}));const q='fixture/exr-task',slot=`fixture/${workId}/exr-task`,file='courseInstances/fall/infoCourseInstance.json';await mkdir(join(root,'courseInstances/fall'),{recursive:true});await writeFile(join(root,file),info);
 const delivery={schemaVersion:4,courseId:'fixture',bookRoot:'fixture',sourceSnapshotHash:'a'.repeat(64),inventoryHash:'b'.repeat(64),verificationInventoryHash:'c'.repeat(64),questions:[q],gradingPayloads:{[q]:{kind:'native-answer',uuid:'22222222-2222-4222-8222-222222222222',grading:{method:'manual'},answerType:'manual',responseSlots:[{name:'answer',type:'manual',anchor:'a'}],upstreamGradingMethod:'Manual'}},works:[{id:workId,slots:[{id:slot,selection:'fixed',candidates:[q],assignment:{requirement:'required',workMode:'individual'}}],policy:{assignment:{'student-label':workId+'-label'}},completion:{schemaVersion:2,mode:'required-slot-completion',source:'per-slot-results-v2',slotIds:[slot],requiredSlotIds:[slot],atLeast:1,fullyCompletedScore:1}}],instances:{fall:{works:[workId],selfEnrollment:false}},files:{[file]:sha(info)}};
 delivery.deliveryHash=sha(canonicalJSONString(delivery));await writeFile(join(root,'delivery.json'),JSON.stringify(delivery));return{root,delivery,cleanup:()=>rm(root,{recursive:true,force:true})};
}
