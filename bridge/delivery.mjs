import {z} from 'zod';
import {canonicalJSONString} from './policy.mjs';
const hashSchema = z.string().regex(/^[a-f0-9]{64}$/);
const idsSchema = z
  .array(z.string().min(1))
  .refine((v) => new Set(v).size === v.length, 'Duplicate IDs');
const relativePath=z.string().min(1).refine(p=>!p.startsWith('/')&&!/^[A-Za-z]:/.test(p)&&!/[\x00-\x1f\x7f]/.test(p)&&!p.includes('\\')&&!p.split('/').some(s=>['','.','..'].includes(s)));
const submission=z.strictObject({mode:z.enum(['upload','editor']),aceMode:z.string().regex(/^ace\/mode\/[a-z][a-z0-9_]*$/).optional()}).refine(s=>s.mode==='editor'||s.aceMode===undefined);
const commonBinding={uuid:z.string().uuid(),submission,sourceRoot:relativePath};
const gradingBinding=z.union([
 z.strictObject({...commonBinding,grading:z.strictObject({method:z.literal('manual')})}).refine(b=>b.submission.mode==='upload'),
 z.strictObject({...commonBinding,grading:z.strictObject({method:z.enum(['external','mixed'])}),projectCheck:z.string().min(1),runtime:z.string().min(1),sources:z.array(z.strictObject({projectRelativePath:relativePath,submissionRelativePath:relativePath,sha256:hashSchema})).min(1)})
]);
const slotSchema=z.strictObject({id:z.string(),selection:z.enum(['fixed','random','choice']),candidates:idsSchema.min(1),assignment:z.strictObject({stage:z.enum(['demonstration','classroom','homework']).optional(),requirement:z.enum(['required','optional']),workMode:z.enum(['individual','pair','group'])})}).refine(slot=>slot.selection==='fixed'?slot.candidates.length===1&&slot.id.split('/').at(-1)===slot.candidates[0].split('/').at(-1):slot.candidates.length>=2&&/^alt-[a-z0-9][a-z0-9-]*$/.test(slot.id.split('/').at(-1))).refine(slot=>slot.selection!=='choice'||slot.assignment.requirement==='required');
const completionSchema=z.strictObject({schemaVersion:z.literal(2),mode:z.literal('required-slot-completion'),source:z.literal('per-slot-results-v2'),slotIds:idsSchema.min(1),requiredSlotIds:idsSchema.min(1),atLeast:z.number().int().positive(),fullyCompletedScore:z.literal(1)}).refine(c=>c.atLeast<=c.requiredSlotIds.length&&c.requiredSlotIds.every(id=>c.slotIds.includes(id)));
const deliveryBase=z.strictObject({
 schemaVersion:z.literal(3),courseId:z.string().regex(/^[a-z][a-z0-9-]*$/),bookRoot:z.string(),sourceSnapshotHash:hashSchema,inventoryHash:hashSchema,verificationInventoryHash:hashSchema,deliveryHash:hashSchema,questions:idsSchema.min(1),gradingPayloads:z.record(z.string(),gradingBinding),
 works:z.array(z.strictObject({id:z.string().regex(/^[a-z][a-z0-9-]*$/),slots:z.array(slotSchema).min(1),policy:z.record(z.string(),z.json()),completion:completionSchema,relatedExercise:z.string().optional()})).min(1),
 instances:z.record(z.string(),z.strictObject({works:idsSchema.min(1),selfEnrollment:z.boolean()})),files:z.record(z.string(),hashSchema),candidate:z.boolean().optional()
});
const inventoryValid=d=>canonicalJSONString(Object.keys(d.gradingPayloads).sort())===canonicalJSONString([...d.questions].sort())&&new Set(Object.values(d.gradingPayloads).map(b=>b.uuid)).size===d.questions.length&&new Set(d.works.map(w=>w.id)).size===d.works.length&&Object.values(d.instances).every(i=>i.works.every(id=>d.works.some(w=>w.id===id)))&&d.works.every(w=>{
 const ids=w.slots.map(s=>s.id),candidates=w.slots.flatMap(s=>s.candidates),required=w.slots.filter(s=>s.assignment.requirement==='required').map(s=>s.id);
 return new Set(ids).size===ids.length&&new Set(candidates).size===candidates.length&&w.slots.every(s=>new RegExp('^'+d.courseId+'/'+w.id+'/(exr|alt)-[a-z0-9][a-z0-9-]*$').test(s.id)&&s.candidates.every(q=>new RegExp('^'+d.courseId+'/exr-[a-z0-9][a-z0-9-]*$').test(q)&&d.questions.includes(q)))&&canonicalJSONString(ids)===canonicalJSONString(w.completion.slotIds)&&canonicalJSONString(required)===canonicalJSONString(w.completion.requiredSlotIds);
});
export const bridgeDelivery3Schema=deliveryBase.refine(inventoryValid,'Invalid v3 grading/slot inventory');


const responseSlot=z.strictObject({name:z.string().min(1),type:z.enum(['manual','numeric','single-choice','matching']),anchor:z.string().min(1),labelAnchor:z.string().min(1).optional(),ordinal:z.number().int().nonnegative().optional(),options:z.array(z.strictObject({anchor:z.string().min(1),ordinal:z.number().int().nonnegative()})).min(1).optional()});
function validAnswer(b) {
 const slots=b.responseSlots,k=b.answerType,keys=s=>Object.keys(s).sort().join(',');
 if(new Set(slots.map(s=>s.anchor)).size!==slots.length)return false;
 const simple=(t)=>slots.length===1&&slots[0].name==='answer'&&slots[0].type===t&&keys(slots[0])==='anchor,name,type';
 const valid=k==='manual'||k==='numeric'?simple(k):k==='single-choice'?slots.length>=2&&slots.every((s,i)=>s.name==='answer'&&s.type===k&&s.ordinal===i&&keys(s)==='anchor,labelAnchor,name,ordinal,type'):k==='matching'?slots.every((s,i)=>s.name==='match-'+i&&s.type===k&&s.ordinal===i&&keys(s)==='anchor,labelAnchor,name,options,ordinal,type'&&canonicalJSONString(s.options)===canonicalJSONString(slots[0].options)&&s.options.every((o,j)=>o.ordinal===j)&&new Set(s.options.map(o=>o.anchor)).size===s.options.length):k==='multipart'&&new Set(slots.map(s=>s.name)).size===slots.length&&slots.every(s=>['manual','numeric'].includes(s.type)&&keys(s)==='anchor,labelAnchor,name,type');
 const types=new Set(slots.map(s=>s.type)),method=types.has('manual')?types.size===1?'manual':'mixed':'external';
 return valid&&b.grading.method===method&&b.upstreamGradingMethod===(method==='manual'?'Manual':'Internal');
}
const nativeAnswer=z.strictObject({kind:z.literal('native-answer'),uuid:z.string().uuid(),grading:z.strictObject({method:z.enum(['manual','mixed','external'])}),answerType:z.enum(['manual','numeric','single-choice','matching','multipart']),responseSlots:z.array(responseSlot).min(1).max(4096),upstreamGradingMethod:z.enum(['Manual','Internal'])}).refine(validAnswer);
const workspaceOptions=z.strictObject({image:z.string().regex(/^[^\s]+@sha256:[a-f0-9]{64}$/),home:z.string().regex(/^\/(?:[a-zA-Z0-9_-]+\/?)+$/),port:z.number().int().min(1024).max(65535),gradedFiles:z.array(relativePath).min(1).max(128),rewriteUrl:z.boolean().optional(),enableNetworking:z.boolean().optional()}).refine(o=>new Set(o.gradedFiles).size===o.gradedFiles.length&&['work/**','work/.git/**','work/.*','explanation.m[d]','.pl-seed/identity.jso[n]'].every(f=>o.gradedFiles.includes(f)));
const workspace=z.strictObject({kind:z.literal('workspace'),uuid:z.string().uuid(),grading:z.strictObject({method:z.literal('manual')}),sourceRoot:relativePath,submission:z.strictObject({mode:z.literal('workspace'),workspaceOptions}),seed:z.strictObject({schema:z.literal('pl-git-workspace-seed-v1'),archive:z.literal('workspace/.pl-seed/starter.zip'),archiveSha256:hashSchema,manifest:z.literal('workspace/.pl-seed/manifest.json'),manifestSha256:hashSchema}),upstreamGradingMethod:z.literal('Manual'),singleVariant:z.literal(true)});
const project4=z.object({kind:z.literal('project')}).passthrough().refine(b=>{const {kind,...project}=b;return gradingBinding.safeParse(project).success;});
export const bridgeDelivery4Schema=deliveryBase.extend({schemaVersion:z.literal(4),gradingPayloads:z.record(z.string(),z.union([project4,nativeAnswer,workspace]))}).refine(inventoryValid,'Invalid v4 grading/slot inventory');
export const bridgeDeliverySchema=z.union([bridgeDelivery3Schema,bridgeDelivery4Schema]);
