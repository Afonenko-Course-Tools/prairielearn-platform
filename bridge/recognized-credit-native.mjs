// Внутренняя административная граница PL; публичного endpoint нет.
import {readFile,realpath} from 'node:fs/promises';
import {isAbsolute,join} from 'node:path';
const FORMAT='NATIVE_RECOGNIZED_CREDIT_V1';
const AI_FIELDS=['courseId','courseInstanceUUID','courseInstanceId','workId','assessmentUUID','assessmentId','assessmentInstanceId','userId','uid'];
const IQ_FIELDS=[...AI_FIELDS,'questionUUID','questionId','assessmentQuestionId','instanceQuestionId'];
const fail=(s)=>{throw new Error(s);};
function canonical(v){if(v instanceof Date){if(!Number.isFinite(v.getTime()))fail('Invalid native timestamp');return JSON.stringify(v.toISOString());}if(v===undefined||typeof v==='function'||typeof v==='symbol')fail('Noncanonical mapping value');if(v===null||typeof v!=='object'){if(typeof v==='number'&&!Number.isFinite(v))fail('Nonfinite mapping');return JSON.stringify(v);}if(Array.isArray(v))return '['+v.map(canonical).join(',')+']';return '{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canonical(v[k])).join(',')+'}';}
const sameMapping=(a,b)=>['source','target','mapping'].every(k=>canonical(a[k])===canonical(b[k]));
function shape(input){
 if(!input||typeof input!=='object'||!input.source||!input.target||!input.mapping)fail('Missing exact source/final mapping');
 const {source:s,target:t,mapping:m}=input;
 for(const [v,keys]of [[s,['autoJobId','submissionId','variantId','instanceQuestionId','assessmentInstanceId','userId']],[t,['courseId','courseInstanceId','assessmentId','questionId','assessmentQuestionId','assessmentInstanceId','instanceQuestionId','userId']]])for(const k of keys)if(typeof v[k]!=='string'||!/^[1-9][0-9]*$/.test(v[k]))fail('Missing exact native mapping '+k);
 for(const [v,keys]of [[s,['questionUUID','workUUID']],[t,['courseUUID','courseInstanceUUID','assessmentUUID','questionUUID']]])for(const k of keys)if(typeof v[k]!=='string'||! /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(v[k]))fail('Missing final UUID mapping '+k);
 if(typeof s.database!=='string'||!s.database||s.uid!==t.uid||s.userId!==t.userId||typeof s.uid!=='string'||!s.uid||typeof t.workId!=='string'||!t.workId||!['identity','accepted-rename'].includes(m.kind)||typeof m.canonicalExerciseId!=='string'||!m.canonicalExerciseId)fail('Unproven UID/task mapping');
 if(typeof input.actorUserId!=='string'||!/^[1-9][0-9]*$/.test(input.actorUserId))fail('Missing native administrator identity');
}
function same(row,expected,keys,label){if(!row||keys.some(k=>row[k]!==expected[k]))fail(label+' native ownership/identity differs');}
async function courseIdentity(row,target){
 if(row?.courseId!==target.courseId||typeof row.coursePath!=='string'||!isAbsolute(row.coursePath)||await realpath(row.coursePath)!==row.coursePath)fail('Native course ID/path differs');
 // Community courses has no UUID column. Its existing infoCourse.json is the
 // canonical course UUID, as in the qualified native course-sync boundary.
 const info=JSON.parse(await readFile(join(row.coursePath,'infoCourse.json'),'utf8'));
 if(info.uuid!==target.courseUUID)fail('Native delivered course UUID differs');
}
function success(row,source){
 same(row,source,['database','autoJobId','submissionId','variantId','instanceQuestionId','assessmentInstanceId','questionUUID','workUUID','uid','userId'],'Source');
 if(!['Internal','External'].includes(row.grading_method)||row.graded_at==null||row.grading_request_canceled_at!=null||row.deleted_at!=null||row.gradable!==true||row.submission_broken!==false||row.correct!==true||typeof row.score!=='number'||!Number.isFinite(row.score)||row.score<1)fail('No complete uncanceled native automatic success');
}
function maximum(row){
 const a=Number(row.max_auto_points??0),m=Number(row.max_manual_points??0),total=Number(row.max_points);
 if(![a,m,total].every(Number.isFinite)||a<0||m<0||total<=0||Math.abs(a+m-total)>1e-9)fail('Native component maxima require qualification');return{auto:a,manual:m,total};
}
function full(row){const n=maximum(row);return row.points===n.total&&row.auto_points===n.auto&&row.manual_points===n.manual&&row.score_perc===100&&row.status==='complete'&&row.requires_manual_grading===false;}
let database;
async function nativeDb(){return database??=(async()=>{const [pg,{z}]=await Promise.all([import('@prairielearn/postgres'),import('zod')]);return{...pg,schema:z.any(),recompute:async(args)=>{const grading=await import(new URL('../dist/lib/assessment-grading.js',import.meta.url));return grading.updateAssessmentInstanceGrade({...args,onlyLogIfScoreUpdated:true});}};})();}
async function repair(db,sql,input,actor){
 const p={assessment_instance_id:input.target.assessmentInstanceId,instance_question_id:input.target.instanceQuestionId,actor};
 const before=await db.queryOptionalRow(sql.context,{assessment_instance_id:p.assessment_instance_id,instanceQuestionId:p.instance_question_id},db.schema);same(before,input.target,IQ_FIELDS,'Target');maximum(before);
 if(!full(before))await db.execute(sql.repair,p);
 const after=await db.queryOptionalRow(sql.readback,{assessment_instance_id:p.assessment_instance_id,instanceQuestionId:p.instance_question_id},db.schema);same(after,input.target,IQ_FIELDS,'Readback');if(!full(after))fail('Native recognized-credit readback incomplete');
 if(after.open!==before.open)fail('Recognition changed closure');return after;
}
function eventRecord(row){const r=row?.record;if(r?.format!==FORMAT||typeof row.authn_user_id!=='string'||r.actorUserId!==row.authn_user_id)fail('Invalid trusted native administrative event');shape(r);return r;}
export async function recognizeCredit(input,approval,injectedDb){
 shape(input);
 if(!approval||approval.actorUserId!==input.actorUserId||!sameMapping(approval,input))fail('Closed approved mapping/scope differs');
 const db=injectedDb??await nativeDb(),sql=db.loadSqlEquiv(import.meta.url);
 return db.runInTransactionAsync(async()=>{
  const params={assessment_instance_id:input.target.assessmentInstanceId,actor:input.actorUserId};
  const ai=await db.queryRow(sql.lock_ai,params,db.schema);same(ai,input.target,AI_FIELDS,'Assessment');await courseIdentity(ai,input.target);if(ai.administrator!==true)fail('Native administrator required');
  const iq=await db.queryOptionalRow(sql.context,{assessment_instance_id:params.assessment_instance_id,instanceQuestionId:input.target.instanceQuestionId},db.schema);
  if(!iq)return{status:'NEEDS_NATIVE_ADMIN_EVENT',reason:'Selected native IQ absent; administrative materialization not implemented; no reopen or alternate slot'};
  same(iq,input.target,IQ_FIELDS,'Target');maximum(iq);
  const source=await db.queryRow(sql.source_success,{autoJobId:input.source.autoJobId},db.schema);success(source,input.source);
  const existing=await db.queryOptionalRow(sql.existing_event,{instance_question_id:input.target.instanceQuestionId},db.schema);
  if(existing){const prior=eventRecord(existing);if(!sameMapping(prior,input))fail('Existing materialization mapping conflict');await repair(db,sql,prior,prior.actorUserId);await db.recompute({assessment_instance_id:prior.target.assessmentInstanceId,authn_user_id:prior.actorUserId,credit:100});return{status:'ALREADY_RECOGNIZED',eventId:existing.id};}
  if(typeof input.checkModifiedAt!=='string'||!Number.isFinite(Date.parse(input.checkModifiedAt))||new Date(iq.modified_at).toISOString()!==new Date(input.checkModifiedAt).toISOString())fail('modified_at conflict; no recognition applied');
  // An unrelated/failed response must never become an import response.
  if(input.destinationSubmissionId!=null&&(input.destinationSubmissionId!==input.source.submissionId||input.target.instanceQuestionId!==input.source.instanceQuestionId))fail('Unsuitable destination submission; use honest no-submission admin event');
  const record={format:FORMAT,source:input.source,target:input.target,mapping:input.mapping,actorUserId:input.actorUserId,explanation:'Признан прежний полный автоматический успех. Ручная часть не требуется. Это административный перенос, не проверка новых тестов и не новый ответ студента.'};
  const event=await db.queryRow(sql.insert_event,{actor:input.actorUserId,userId:input.target.userId,courseInstanceId:input.target.courseInstanceId,instanceQuestionId:input.target.instanceQuestionId,record:canonical(record)},db.schema);
  if(input.destinationSubmissionId!=null)await db.execute(sql.insert_manual_job,{actor:input.actorUserId,submission_id:input.destinationSubmissionId,record:canonical(record),auto_points:iq.max_auto_points??0,manual_points:iq.max_manual_points??0});
  await repair(db,sql,record,input.actorUserId);await db.recompute({assessment_instance_id:record.target.assessmentInstanceId,authn_user_id:input.actorUserId,credit:100});
  return{status:'RECOGNIZED_NATIVE_ADMIN_EVENT',eventId:event.id};
 });
}
// Called only inside an existing native AI transaction/lock. Never invokes the
// aggregate recompute: the caller does so once, after repaired IQ state.
export async function applyRecognizedCredit({assessment_instance_id},injectedDb){
 const db=injectedDb??await nativeDb(),sql=db.loadSqlEquiv(import.meta.url);
 return db.runInTransactionAsync(async()=>{
  const events=await db.queryRows(sql.recognized_events,{assessment_instance_id},db.schema);
  for(const event of events){const record=eventRecord(event);if(record.target.assessmentInstanceId!==assessment_instance_id)fail('Recognition bound to another AI');const ai=await db.queryRow(sql.lock_ai,{assessment_instance_id,actor:record.actorUserId},db.schema);same(ai,record.target,AI_FIELDS,'Assessment');await courseIdentity(ai,record.target);const source=await db.queryRow(sql.source_success,{autoJobId:record.source.autoJobId},db.schema);success(source,record.source);await repair(db,sql,record,record.actorUserId);}
  return events.length;
 });
}

export async function recognizedPrivateFilesApi(input,approval,injectedDb,injectedStore){
 shape(input);
 if(!approval||approval.actorUserId!==input.actorUserId||!sameMapping(approval,input))fail('Closed approved file owner mapping differs');
 const db=injectedDb??await nativeDb(),sql=db.loadSqlEquiv(import.meta.url);
 const store=injectedStore??await import(new URL('../dist/lib/file-store.js',import.meta.url));
 const p={assessment_instance_id:input.target.assessmentInstanceId,actor:input.actorUserId};
 const context=()=>db.runInTransactionAsync(async()=>{
  const ai=await db.queryRow(sql.lock_ai,p,db.schema);same(ai,input.target,AI_FIELDS,'File assessment');await courseIdentity(ai,input.target);if(ai.administrator!==true)fail('Native administrator required for private code transfer');
  const iq=await db.queryOptionalRow(sql.context,{assessment_instance_id:p.assessment_instance_id,instanceQuestionId:input.target.instanceQuestionId},db.schema);same(iq,input.target,IQ_FIELDS,'File owner');
  const event=await db.queryOptionalRow(sql.existing_event,{instance_question_id:input.target.instanceQuestionId},db.schema);const record=eventRecord(event);
  if(!sameMapping(record,input)||!full(iq))fail('Private files require exact current recognized IQ');
  return{...input.target,actorUserId:input.actorUserId,allowPersonalNotes:iq.allow_personal_notes===true,recognizedCredit:true};
 });
 return{context,
  readSourceReference:async ref=>db.runInTransactionAsync(async()=>{
   const ai=await db.queryRow(sql.lock_ai,p,db.schema);same(ai,input.target,AI_FIELDS,'Source-file operator');await courseIdentity(ai,input.target);if(ai.administrator!==true)fail('Native administrator required for source file read');
   const s=ref.source;
   if(!s||ref.uid!==input.source.uid||s.userId!==input.source.userId||s.assessmentInstanceId!==input.source.assessmentInstanceId||s.instanceQuestionId!==input.source.instanceQuestionId)fail('Foreign source file UID/AI/IQ');
   const expected=['database','uid','userId','assessmentInstanceId','instanceQuestionId','workUUID','questionUUID'];let bytes;
   if(s.kind==='submission'){
    const row=await db.queryOptionalRow(sql.source_private_submission,{submissionId:s.submissionId},db.schema);same(row,input.source,expected,'Source submission');
    if(row.submissionId!==s.submissionId||row.variantId!==s.variantId||!Number.isSafeInteger(s.fileIndex)||s.fileIndex<0)fail('Source submission/variant/index differs');
    if(!['raw','submitted'].includes(s.answerField))fail('Explicit native raw/submitted reference required');
    const f=(s.answerField==='raw'?row.raw_answer:row.submitted_answer)?._files?.[s.fileIndex];
    if(!f||f.name!==s.filename||typeof f.contents!=='string'||!/^[A-Za-z0-9+/]*={0,2}$/.test(f.contents))fail('Native raw submission file absent/different');
    bytes=Buffer.from(f.contents,'base64');if(bytes.toString('base64').replace(/=+$/,'')!==f.contents.replace(/=+$/,''))fail('Native raw submission file base64 differs');
   }else if(s.kind==='native-file'){
    const row=await db.queryOptionalRow(sql.source_private_file,{fileId:s.fileId},db.schema);same(row,input.source,expected,'Source native file');
    const saved=await store.getFile(s.fileId),f=saved.file;
    if(f.id!==s.fileId||f.user_id!==s.userId||f.assessment_instance_id!==s.assessmentInstanceId||f.instance_question_id!==s.instanceQuestionId||f.display_filename!==s.filename||f.type!=='student_upload'||f.deleted_at!=null)fail('Source native file storage owner differs');
    bytes=saved.contents;
   }else fail('Unknown exact native private reference kind');
   if(!Buffer.isBuffer(bytes)||bytes.length>1048576)fail('Source private bytes differ from native reference');
   return bytes;
  }),
  findFiles:async name=>{await context();return db.queryRows(sql.find_private_files,{assessmentId:input.target.assessmentId,assessment_instance_id:p.assessment_instance_id,instanceQuestionId:input.target.instanceQuestionId,userId:input.target.userId,display_filename:name},db.schema);},
  uploadFile:async options=>{const owner=await context();if(!owner.allowPersonalNotes)fail('Private code visibility requires delivered personal notes');if(options.type!=='student_upload'||options.user_id!==input.target.userId||options.authn_user_id!==input.actorUserId||options.assessment_id!==input.target.assessmentId||options.assessment_instance_id!==input.target.assessmentInstanceId||options.instance_question_id!==input.target.instanceQuestionId)fail('Native private upload authority differs');return store.uploadFile(options);},
  getFile:async fileId=>{await context();const row=await db.queryOptionalRow(sql.owned_private_file,{assessmentId:input.target.assessmentId,assessment_instance_id:p.assessment_instance_id,instanceQuestionId:input.target.instanceQuestionId,userId:input.target.userId,file_id:fileId},db.schema);if(!row)fail('Foreign or deleted native private file');return store.getFile(fileId);},
 };
}

// Read-only binding gate: no new score event, repair, response or upload.
export async function verifyRecognizedCredit(input,approval,injectedDb){
 shape(input);
 if(!approval||approval.actorUserId!==input.actorUserId||!sameMapping(approval,input))fail('Closed approved recognition mapping differs');
 const db=injectedDb??await nativeDb(),sql=db.loadSqlEquiv(import.meta.url);
 return db.runInTransactionAsync(async()=>{
  const p={assessment_instance_id:input.target.assessmentInstanceId,actor:input.actorUserId};
  const ai=await db.queryRow(sql.lock_ai,p,db.schema);same(ai,input.target,AI_FIELDS,'Recognized assessment');await courseIdentity(ai,input.target);if(ai.administrator!==true)fail('Native administrator required');
  const iq=await db.queryOptionalRow(sql.context,{assessment_instance_id:p.assessment_instance_id,instanceQuestionId:input.target.instanceQuestionId},db.schema);same(iq,input.target,IQ_FIELDS,'Recognized IQ');if(!full(iq))fail('Native recognized credit is not currently full');
  const event=eventRecord(await db.queryOptionalRow(sql.existing_event,{instance_question_id:input.target.instanceQuestionId},db.schema));
  if(!sameMapping(event,input))fail('Native recognition mapping differs');
  const source=await db.queryRow(sql.source_success,{autoJobId:input.source.autoJobId},db.schema);success(source,input.source);
  return{...input.target,recognizedCredit:true};
 });
}
