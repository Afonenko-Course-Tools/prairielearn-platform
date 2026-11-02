// Внутренний E-вызов в уже инициализированном native admin runtime. Endpoint нет.
import {readFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import {loadVerifiedBindings} from '../bridge/bindings.mjs';
import {assertProductionRuntime,resolveAssignment,validateNativeGroups} from '../bridge/policy.mjs';
import {bindRecognizedAssignment,migrateRecognizedAssignment} from '../bridge/recognized-assignment.mjs';
import {verifyRecognizedCredit,recognizedPrivateFilesApi} from '../bridge/recognized-credit-native.mjs';
import {verifyRecognizedPrivateFiles} from './recognized-credit-files.mjs';

async function nativeServices(args,bindingSettings){
 const root=process.env.PL_ROOT??'/PrairieLearn';
 const native=path=>import(pathToFileURL(`${root}/apps/prairielearn/dist/${path}.js`).href);
 const [db,{z},instances,users,enrollments,labels,{dangerousFullSystemAuthz},{config}]=await Promise.all([
  import('@prairielearn/postgres'),import('zod'),native('models/course-instances'),native('models/user'),native('models/enrollment'),native('models/student-label'),native('lib/authz-data-lib'),native('lib/config')]);
 assertProductionRuntime(process.env.NODE_ENV,config);
 const bindings=await loadVerifiedBindings(bindingSettings),system=dangerousFullSystemAuthz();
 const sql=db.loadSqlEquiv(new URL('../bridge/native.mjs',import.meta.url).href);
 async function context(request){
  const binding=bindings.find(b=>b.delivery.deliveryHash===request.deliveryHash&&b.delivery.instances[request.instance]);
  if(!binding)throw Error('Exact source/final delivery binding missing');
  // The source oldWork is historical. Only this bounded operation validates
  // old/new delivered works separately; ordinary policy still forbids migration.
  resolveAssignment({...request,oldWork:null},binding.delivery);
  const ci=await instances.selectCourseInstanceById(binding.courseInstanceId);
  const info=JSON.parse(await readFile(`${binding.deliveryPath}/courseInstances/${request.instance}/infoCourseInstance.json`,'utf8'));
  const user=await users.selectOptionalUserByUid(request.userUid);
  if(ci.deleted_at!==null||ci.uuid!==info.uuid||!user)throw Error('Native course-instance/UID binding differs');
  const work=binding.delivery.works.find(w=>w.id===request.newWork);
  const groups=await db.queryRows(sql.validate_assessment,{course_instance_id:ci.id,work_id:work.id},z.any());validateNativeGroups(work,groups);
  const managed=new Set(binding.delivery.instances[request.instance].works.map(id=>binding.delivery.works.find(w=>w.id===id)?.policy?.assignment?.['student-label']).filter(Boolean));
  return{binding,ci,user,work,managed,courseInstanceId:ci.id,uid:user.uid,workId:work.id,deliveryHash:binding.delivery.deliveryHash};
 }
 async function enrollment(c,ensure=false){
  const options={userId:c.user.id,courseInstance:c.ci,authzData:system,requiredRole:['System']};
  const e=ensure?await enrollments.ensureUncheckedEnrollment({...options,actionDetail:'implicit_joined'}):await enrollments.selectOptionalEnrollmentByUserId(options);
  if(ensure&&(!e||e.status!=='joined'))throw Error('Native destination enrollment unavailable');return e;
 }
 return{
  transaction:fn=>db.runInTransactionAsync(fn),
  lock:async()=>{
   const contexts=await Promise.all([context(args.request),...(args.priorRequest?[context(args.priorRequest)]:[])]);
   for(const ci of [...new Set(contexts.map(c=>c.ci.id))].sort())await db.execute(sql.lock,{lock_key:`gateway:${ci}:${args.request.userUid}`});
  },
  read:async id=>{const row=await db.queryOptionalRow(sql.select_assignment,{id},z.any());return row&&{request:row.request,courseInstanceId:row.course_instance_id,userUid:row.user_uid,recognizedAssessmentInstanceId:row.recognized_assessment_instance_id};},
  verifiedContext:context,
  recognition:async(input,approval)=>{
   const credit=await verifyRecognizedCredit(input,approval);
   const api=await recognizedPrivateFilesApi(input,approval);
   await verifyRecognizedPrivateFiles({refs:input.mapping.privateFiles,target:input.target,actorUserId:input.actorUserId,approvedManifestSha256:approval.fileManifestSha256},api);
   return credit;
  },
  reconcileNativeAcl:async({prior,request,destination})=>{
   const old=await context(prior),next=destination;
   const slot=await db.queryOptionalRow(sql.select_slot,{course_instance_id:next.ci.id,user_uid:next.user.uid},z.any());if(slot&&slot.id!==args.id)throw Error('Destination assignment slot already bound');
   const oldEnrollment=await enrollment(old),nextEnrollment=await enrollment(next,true);
   if(oldEnrollment){
    const all=await labels.selectStudentLabelsInCourseInstance(old.ci);
    for(const label of all.filter(l=>old.managed.has(l.name)))await labels.removeLabelFromEnrollment({enrollment:oldEnrollment,label,authzData:system});
    if((await labels.selectStudentLabelsForEnrollment(oldEnrollment)).some(l=>old.managed.has(l.name)))throw Error('Old managed ACL revocation incomplete');
   }
   const target=next.work.policy.assignment['student-label'],all=await labels.selectStudentLabelsInCourseInstance(next.ci);
   if(!all.some(l=>l.name===target))throw Error('Native destination label missing');
   for(const label of all.filter(l=>next.managed.has(l.name))){
    if(label.name===target)await labels.addLabelToEnrollment({enrollment:nextEnrollment,label,authzData:system});
    else await labels.removeLabelFromEnrollment({enrollment:nextEnrollment,label,authzData:system});
   }
   const actual=(await labels.selectStudentLabelsForEnrollment(nextEnrollment)).filter(l=>next.managed.has(l.name)).map(l=>l.name).sort();
   if(actual.length!==1||actual[0]!==target)throw Error('Destination native ACL reconciliation incomplete');
  },
  store:async(id,request,destination)=>{await db.queryRow(sql.migrate_recognized_assignment,{id,request:JSON.stringify(request),prior_request:JSON.stringify(args.priorRequest),course_instance_id:destination.ci.id,user_uid:destination.user.uid},z.any());},
  bind:async(id,ai)=>{const row=await db.queryRow(sql.bind_recognized_assignment,{id,assessment_instance_id:ai,request:JSON.stringify(args.request),course_instance_id:args.input.target.courseInstanceId,user_uid:args.input.target.uid},z.any());if(row.recognized_assessment_instance_id!==ai)throw Error('Native assignment FK readback differs');},
 };
}
export async function bindRecognizedGatewayAssignment(args,bindingSettings){return bindRecognizedAssignment(args,await nativeServices(args,bindingSettings));}
export async function migrateRecognizedGatewayAssignment(args,bindingSettings){return migrateRecognizedAssignment(args,await nativeServices(args,bindingSettings));}
