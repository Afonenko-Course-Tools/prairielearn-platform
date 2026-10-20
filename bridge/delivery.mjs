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
export const bridgeDeliverySchema=z.strictObject({
 schemaVersion:z.literal(3),courseId:z.string().regex(/^[a-z][a-z0-9-]*$/),bookRoot:z.string(),sourceSnapshotHash:hashSchema,inventoryHash:hashSchema,verificationInventoryHash:hashSchema,deliveryHash:hashSchema,questions:idsSchema.min(1),gradingPayloads:z.record(z.string(),gradingBinding),
 works:z.array(z.strictObject({id:z.string().regex(/^[a-z][a-z0-9-]*$/),slots:z.array(slotSchema).min(1),policy:z.record(z.string(),z.json()),completion:completionSchema,relatedExercise:z.string().optional()})).min(1),
 instances:z.record(z.string(),z.strictObject({works:idsSchema.min(1),selfEnrollment:z.boolean()})),files:z.record(z.string(),hashSchema),candidate:z.boolean().optional()
}).refine(d=>canonicalJSONString(Object.keys(d.gradingPayloads).sort())===canonicalJSONString([...d.questions].sort())&&new Set(Object.values(d.gradingPayloads).map(b=>b.uuid)).size===d.questions.length&&new Set(d.works.map(w=>w.id)).size===d.works.length&&Object.values(d.instances).every(i=>i.works.every(id=>d.works.some(w=>w.id===id)))&&d.works.every(w=>{
 const ids=w.slots.map(s=>s.id),candidates=w.slots.flatMap(s=>s.candidates),required=w.slots.filter(s=>s.assignment.requirement==='required').map(s=>s.id);
 return new Set(ids).size===ids.length&&new Set(candidates).size===candidates.length&&w.slots.every(s=>new RegExp('^'+d.courseId+'/'+w.id+'/(exr|alt)-[a-z0-9][a-z0-9-]*$').test(s.id)&&s.candidates.every(q=>new RegExp('^'+d.courseId+'/exr-[a-z0-9][a-z0-9-]*$').test(q)&&d.questions.includes(q)))&&canonicalJSONString(ids)===canonicalJSONString(w.completion.slotIds)&&canonicalJSONString(required)===canonicalJSONString(w.completion.requiredSlotIds);
}),'Invalid v3 grading/slot inventory');
