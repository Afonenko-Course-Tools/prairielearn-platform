// Служебный адаптер Native file-store; все файлы читаются по настоящим owner refs.
function ordered(refs){return [...refs].sort((a,b)=>a.sourceReference.localeCompare(b.sourceReference));}
function checkOwner(context,target,actor,needsNotes=true){if(!context||['uid','userId','assessmentId','assessmentInstanceId','instanceQuestionId'].some(k=>context[k]!==target[k])||context.recognizedCredit!==true||(needsNotes&&context.allowPersonalNotes!==true)||context.actorUserId!==actor)throw Error('Native owner/recognized credit/personal-notes delivery required');}
function checkFile(row,target,name){if(!row||row.user_id!==target.userId||row.assessment_id!==target.assessmentId||row.assessment_instance_id!==target.assessmentInstanceId||row.instance_question_id!==target.instanceQuestionId||row.type!=='student_upload'||row.display_filename!==name||row.deleted_at!=null)throw Error('Existing native private file ownership conflict');}
function references(refs,target){
 if(!Array.isArray(refs)||refs.length>128)throw Error('Private reference count limit');
 const seen=new Set();for(const r of refs){
  if(typeof r.sourceReference!=='string'||!r.sourceReference||seen.has(r.sourceReference)||r.uid!==target.uid||typeof r.relativeName!=='string'||!r.relativeName||r.relativeName.startsWith('/')||r.relativeName.includes('\\')||r.relativeName.split('/').some(p=>['','.','..'].includes(p)))throw Error('Duplicate/foreign/invalid source file reference');seen.add(r.sourceReference);
  const s=r.source,keys=s?.kind==='submission'?['kind','submissionId','variantId','assessmentInstanceId','instanceQuestionId','userId','fileIndex','filename','answerField']:s?.kind==='native-file'?['kind','fileId','assessmentInstanceId','instanceQuestionId','userId','filename']:[];
  if(!keys.length||Object.keys(s).sort().join(',')!==keys.sort().join(',')||keys.filter(k=>!['kind','fileIndex','filename','answerField'].includes(k)).some(k=>typeof s[k]!=='string'||!/^[1-9][0-9]*$/.test(s[k]))||s.userId!==target.userId||typeof s.filename!=='string'||!s.filename||/[\x00-\x1f\x7f]/.test(s.filename))throw Error('Typed source file owner missing/foreign');
  if(s.kind==='submission'&&(!Number.isSafeInteger(s.fileIndex)||s.fileIndex<0||!['raw','submitted'].includes(s.answerField)||r.sourceReference!==`submission:${s.submissionId}:${s.answerField}:${s.fileIndex}`)||s.kind==='native-file'&&r.sourceReference!==`native-file:${s.fileId}`)throw Error('Exact source submission/file reference differs');
 }
}
async function bytes(api,ref){const data=await api.readSourceReference(ref);if(!Buffer.isBuffer(data)||data.length>1048576)throw Error('Native source file size/type limit');return data;}
export async function validatePrivateSourceFiles({refs,target},api){
 references(refs,target);let total=0;
 for(const ref of refs){total+=(await bytes(api,ref)).length;if(total>4194304)throw Error('Private file total size limit');}
 return{sourceReferences:refs.length};
}
export function privateDisplayName(ref){const s=ref.source;const id=s.kind==='native-file'?`file-${s.fileId}`:`submission-${s.submissionId}-${s.answerField}-${s.fileIndex}`;return'recognized-'+id+'-'+s.filename.split('/').at(-1);}
export async function attachRecognizedPrivateFiles({refs,target,actorUserId},api){
 if(typeof actorUserId!=='string'||!/^[1-9][0-9]*$/.test(actorUserId))throw Error('Exact native administrator actor required');
 references(refs,target);checkOwner(await api.context(),target,actorUserId,refs.length>0);
 await validatePrivateSourceFiles({refs,target},api);const files=[];
 for(const ref of ordered(refs)){
  const name=privateDisplayName(ref),data=await bytes(api,ref);const existing=await api.findFiles(name);if(existing.length>1)throw Error('Duplicate native private file materialization');
  let fileId;
  if(existing.length){checkFile(existing[0],target,name);fileId=existing[0].id;}
  else fileId=await api.uploadFile({display_filename:name,contents:data,type:'student_upload',assessment_id:target.assessmentId,assessment_instance_id:target.assessmentInstanceId,instance_question_id:target.instanceQuestionId,user_id:target.userId,authn_user_id:actorUserId});
  const saved=await api.getFile(fileId);checkFile(saved.file,target,name);if(!Buffer.isBuffer(saved.contents)||!saved.contents.equals(data))throw Error('Native private bytes readback differs');
  checkOwner(await api.context(),target,actorUserId,refs.length>0);files.push({...ref,destinationFileId:String(fileId),displayFilename:name});
 }
 return{files};
}
export async function verifyRecognizedPrivateFiles({refs,target,actorUserId},api){
 references(refs,target);checkOwner(await api.context(),target,actorUserId,refs.length>0);const files=[];
 for(const ref of ordered(refs)){
  const data=await bytes(api,ref),name=privateDisplayName(ref);const rows=await api.findFiles(name);if(rows.length!==1)throw Error('Missing/duplicate native private reference');checkFile(rows[0],target,name);const got=await api.getFile(rows[0].id);checkFile(got.file,target,name);if(!Buffer.isBuffer(got.contents)||!got.contents.equals(data))throw Error('Native private source bytes mismatch');files.push({...ref,destinationFileId:String(rows[0].id),displayFilename:name});
 }
 return{files};
}
