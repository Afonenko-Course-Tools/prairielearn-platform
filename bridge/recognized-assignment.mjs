// Ограниченный административный переход E; обычный assignmentTransition не меняется.
import {createHash} from 'node:crypto';
import {canonicalJSONString} from './policy.mjs';
export const assignmentDigest=request=>createHash('sha256').update(canonicalJSONString(request)).digest('hex');
const fail=message=>{throw new Error(message);};
const equal=(a,b)=>assignmentDigest(a)===assignmentDigest(b);
function approved({id,request,input,approval}){
 if(typeof id!=='string'||! /^[A-Za-z0-9_-]{1,128}$/.test(id)||approval?.assignmentId!==id||approval.assignmentRequestSha256!==assignmentDigest(request))fail('Closed assignment mapping differs');
 if(! /^[1-9][0-9]*$/.test(input?.actorUserId)||approval.actorUserId!==input.actorUserId||! /^[a-f0-9]{64}$/.test(input.mappingRowHash)||approval.mappingRowHash!==input.mappingRowHash)fail('Approved native administrator/map differs');
 const keys=['deliveryHash','instance','newWork','oldWork','userUid','version'];
 if(!request||Object.keys(request).sort().join(',')!==keys.join(',')||!Number.isSafeInteger(request.version)||request.version<1||! /^[a-f0-9]{64}$/.test(request.deliveryHash)||typeof request.newWork!=='string'||!request.newWork||(request.oldWork!==null&&typeof request.oldWork!=='string')||typeof request.instance!=='string'||!request.instance||typeof request.userUid!=='string'||!request.userUid||request.userUid.length>512||request.userUid!==input?.target?.uid||request.newWork!==input.target.workId||request.deliveryHash!==input.target.deliveryHash)fail('Final assignment ownership/work/delivery differs');
}
async function context(request,input,service){
 const current=await service.verifiedContext(request);
 if(current.uid!==input.target.uid||current.courseInstanceId!==input.target.courseInstanceId||current.workId!==input.target.workId||current.deliveryHash!==request.deliveryHash)fail('Verified native assignment context differs');
 return current;
}
async function verifiedRecognition(input,approval,service){
 const actual=await service.recognition(input,approval);
 for(const key of ['uid','userId','courseInstanceId','workId','assessmentInstanceId'])if(actual[key]!==input.target[key])fail('Trusted native recognition/readback differs: '+key);
 return actual;
}
async function bindLocked(args,service){
 const {id,request,input,approval}=args;
 approved(args);
 const row=await service.read(id);
 if(!row||!equal(row.request,request)||row.userUid!==input.target.uid||row.courseInstanceId!==input.target.courseInstanceId)fail('Inactive or stale current assignment');
 await context(request,input,service);
 const recognition=await verifiedRecognition(input,approval,service);
 if(row.recognizedAssessmentInstanceId!==null&&row.recognizedAssessmentInstanceId!==recognition.assessmentInstanceId)fail('Assignment already bound to another native AI');
 if(row.recognizedAssessmentInstanceId===null)await service.bind(id,recognition.assessmentInstanceId);
 return{assessmentInstanceId:recognition.assessmentInstanceId,duplicate:row.recognizedAssessmentInstanceId===recognition.assessmentInstanceId};
}
export async function bindRecognizedAssignment(args,service){
 return service.transaction(async()=>{await service.lock(args.id,args.input);return bindLocked(args,service);});
}
export async function migrateRecognizedAssignment(args,service){
 const {id,priorRequest:prior,request,input,approval}=args;
 approved(args);
 if(approval.priorAssignmentRequestSha256!==assignmentDigest(prior)||!Number.isSafeInteger(prior?.version)||request.version!==prior.version+1||request.userUid!==prior.userUid||request.instance!==prior.instance||request.oldWork!==prior.newWork)fail('Exact prior assignment transition differs');
 return service.transaction(async()=>{
  await service.lock(id,input);
  const row=await service.read(id);
  // Readback, rather than a retry of the ACL/write, reconciles an already committed transition.
  if(row&&equal(row.request,request))return bindLocked(args,service);
  if(!row||!equal(row.request,prior)||row.userUid!==request.userUid)fail('Prior assignment version/hash differs');
  const destination=await context(request,input,service);
  await verifiedRecognition(input,approval,service);
  await service.reconcileNativeAcl({prior,request,destination,input});
  await service.store(id,request,destination);
  return bindLocked(args,service);
 });
}
