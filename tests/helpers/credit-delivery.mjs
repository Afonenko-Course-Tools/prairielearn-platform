import {createHash} from 'node:crypto';import {mkdtemp,mkdir,writeFile,rm} from 'node:fs/promises';import {join} from 'node:path';import {tmpdir} from 'node:os';
import {canonicalJSONString} from '../../bridge/policy.mjs';
export const CI_UUID='11111111-1111-4111-8111-111111111111';
const sha=b=>createHash('sha256').update(b).digest('hex');
export async function deliveryFixture(workId='new-work',courseId='fixture'){
 const root=await mkdtemp(join(tmpdir(),'credit-delivery-'));const info=Buffer.from(JSON.stringify({uuid:CI_UUID}));const q=courseId+'/exr-task',slot=`${courseId}/${workId}/exr-task`,file='courseInstances/fall/infoCourseInstance.json';await mkdir(join(root,'courseInstances/fall'),{recursive:true});await writeFile(join(root,file),info);await writeFile(join(root,'infoCourse.json'),JSON.stringify({uuid:CI_UUID}));
 const delivery={schemaVersion:5,courseId,bookRoot:'fixture',questions:[q],gradingPayloads:{[q]:{kind:'native-answer',uuid:'22222222-2222-4222-8222-222222222222',grading:{method:'manual'},answerType:'manual',responseSlots:[{name:'answer',type:'manual',anchor:'a'}],upstreamGradingMethod:'Manual'}},works:[{id:workId,slots:[{id:slot,selection:'fixed',candidates:[q],assignment:{requirement:'required',workMode:'individual'}}],policy:{assignment:{'student-label':workId+'-label'}},completion:{schemaVersion:2,mode:'required-slot-completion',source:'per-slot-results-v2',slotIds:[slot],requiredSlotIds:[slot],atLeast:1,fullyCompletedScore:1}}],instances:{fall:{works:[workId],selfEnrollment:false}},files:[file]};
 await writeFile(join(root,'delivery.json'),JSON.stringify(delivery));return{root,delivery,cleanup:()=>rm(root,{recursive:true,force:true})};
}
