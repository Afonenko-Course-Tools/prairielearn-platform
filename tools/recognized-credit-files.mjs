// Служебный E-адаптер native file-store; не пользовательский endpoint.
import {createHash} from 'node:crypto';
import {constants} from 'node:fs';
import {lstat,open,realpath} from 'node:fs/promises';
import {resolve,join} from 'node:path';
import {canonicalJSONString} from '../bridge/policy.mjs';
const sha=b=>createHash('sha256').update(b).digest('hex');
function ordered(refs){return refs.map(r=>({sourceReference:r.sourceReference,source:r.source,relativeName:r.relativeName,bytes:r.bytes,sha256:r.sha256,uid:r.uid})).sort((a,b)=>Buffer.compare(Buffer.from(a.sourceReference),Buffer.from(b.sourceReference)));}
export const privateManifestDigest=refs=>sha(Buffer.from(canonicalJSONString(ordered(refs))));
const id=s=>[s.dev,s.ino,s.mode,s.uid,s.gid,s.nlink,s.size,s.mtimeNs,s.ctimeNs].map(String).join(':');
async function sourceBytes(root,ref){
 if(typeof root!=='string'||resolve(root)!==root||await realpath(root)!==root)throw Error('Canonical owned source root required');
 const names=ref.relativeName.split('/');if(!ref.relativeName||ref.relativeName.startsWith('/')||names.some(n=>!n||n==='.'||n==='..')||/[\x00-\x1f\x7f]/.test(ref.relativeName))throw Error('Unsafe private source path');
 const parents=[];
 for(let i=0;i<names.length;i++){const p=join(root,...names.slice(0,i));const s=await lstat(p,{bigint:true});if(!s.isDirectory()||s.uid!==BigInt(process.getuid())||(s.mode&0o777n)!==0o700n)throw Error('Private owned source directory required');parents.push([p,id(s)]);}
 const path=join(root,...names);const before=await lstat(path,{bigint:true});if(!before.isFile()||before.uid!==BigInt(process.getuid())||before.nlink!==1n||(before.mode&0o777n)!==0o600n||before.size!==BigInt(ref.bytes))throw Error('Private regular single-link source file required');
 const f=await open(path,constants.O_RDONLY|constants.O_NOFOLLOW);
 try{
  if(id(await f.stat({bigint:true}))!==id(before))throw Error('Private source open race');
  const bytes=Buffer.alloc(ref.bytes);let offset=0;
  while(offset<bytes.length){const r=await f.read(bytes,offset,bytes.length-offset,offset);if(!r.bytesRead)throw Error('Short private source');offset+=r.bytesRead;}
  const extra=Buffer.alloc(1);if((await f.read(extra,0,1,offset)).bytesRead||id(await f.stat({bigint:true}))!==id(before)||id(await lstat(path,{bigint:true}))!==id(before)||sha(bytes)!==ref.sha256)throw Error('Private source changed/hash mismatch');
  for(const [p,identity]of parents)if(id(await lstat(p,{bigint:true}))!==identity)throw Error('Private source ancestor changed');
  return bytes;
 }finally{await f.close();}
}
function checkOwner(context,target,actor,needsNotes=true){if(!context||['uid','userId','assessmentId','assessmentInstanceId','instanceQuestionId'].some(k=>context[k]!==target[k])||context.recognizedCredit!==true||(needsNotes&&context.allowPersonalNotes!==true)||context.actorUserId!==actor)throw Error('Native owner/recognized credit/personal-notes delivery required');}
function checkFile(row,target,name){if(!row||row.user_id!==target.userId||row.assessment_id!==target.assessmentId||row.assessment_instance_id!==target.assessmentInstanceId||row.instance_question_id!==target.instanceQuestionId||row.type!=='student_upload'||row.display_filename!==name||row.deleted_at!=null)throw Error('Existing native private file ownership conflict');}
function references(refs,target,approved){
 if(!Array.isArray(refs)||privateManifestDigest(refs)!==approved)throw Error('Approved all-reference private manifest differs');
 const seen=new Set();for(const r of refs){
  if(typeof r.sourceReference!=='string'||!r.sourceReference||seen.has(r.sourceReference)||r.uid!==target.uid||typeof r.relativeName!=='string'||!Number.isSafeInteger(r.bytes)||r.bytes<0||!/^[a-f0-9]{64}$/.test(r.sha256))throw Error('Duplicate/foreign/invalid source file reference');seen.add(r.sourceReference);
  const s=r.source,keys=s?.kind==='submission'?['kind','submissionId','variantId','assessmentInstanceId','instanceQuestionId','userId','fileIndex','filename','answerField']:s?.kind==='native-file'?['kind','fileId','assessmentInstanceId','instanceQuestionId','userId','filename']:[];
  if(!keys.length||Object.keys(s).sort().join(',')!==keys.sort().join(',')||keys.filter(k=>!['kind','fileIndex','filename','answerField'].includes(k)).some(k=>typeof s[k]!=='string'||!/^[1-9][0-9]*$/.test(s[k]))||s.userId!==target.userId||typeof s.filename!=='string'||!s.filename||s.filename.includes('\0'))throw Error('Typed source file owner missing/foreign');
  if(s.kind==='submission'&&(!Number.isSafeInteger(s.fileIndex)||s.fileIndex<0||!['raw','submitted'].includes(s.answerField)||r.sourceReference!==`submission:${s.submissionId}:${s.answerField}:${s.fileIndex}`)||s.kind==='native-file'&&r.sourceReference!==`native-file:${s.fileId}`)throw Error('Exact source submission/file reference differs');
 }
}
export async function validatePrivateSourceFiles({sourceRoot,refs,target,approvedManifestSha256},api){
 references(refs,target,approvedManifestSha256);
 for(const r of refs){await api.verifySourceReference(r);await sourceBytes(sourceRoot,r);}
 return{sourceReferencesVerified:refs.length,manifestSha256:approvedManifestSha256};
}
export async function attachRecognizedPrivateFiles({sourceRoot,refs,target,approvedManifestSha256,actorUserId},api){
 if(typeof actorUserId!=='string'||!/^[1-9][0-9]*$/.test(actorUserId))throw Error('Exact native administrator actor required');
 references(refs,target,approvedManifestSha256);
 checkOwner(await api.context(),target,actorUserId,refs.length>0);
 // Validate the complete approved set before the first native upload. Keep only
 // one file buffer at a time; native uploadFile/getFile are buffer APIs.
 await validatePrivateSourceFiles({sourceRoot,refs,target,approvedManifestSha256},api);
 const files=[];
 for(const ref of ordered(refs)){
  const name=privateDisplayName(ref);
  const existing=await api.findFiles(name);if(existing.length>1)throw Error('Duplicate native private file materialization');
  let fileId;
  if(existing.length){checkFile(existing[0],target,name);fileId=existing[0].id;}
  else{const bytes=await sourceBytes(sourceRoot,ref);fileId=await api.uploadFile({display_filename:name,contents:bytes,type:'student_upload',assessment_id:target.assessmentId,assessment_instance_id:target.assessmentInstanceId,instance_question_id:target.instanceQuestionId,user_id:target.userId,authn_user_id:actorUserId});}
  const saved=await api.getFile(fileId);checkFile(saved.file,target,name);if(!Buffer.isBuffer(saved.contents)||saved.contents.length!==ref.bytes||sha(saved.contents)!==ref.sha256)throw Error('Native private bytes readback differs');
  checkOwner(await api.context(),target,actorUserId,refs.length>0);files.push({...ref,destinationFileId:String(fileId),displayFilename:name});
 }
 return{status:'ALL_PRIVATE_REFERENCES_NATIVE_BYTES_VERIFIED',manifestSha256:approvedManifestSha256,files,studentDownloadRoute:'NOT_QUALIFIED_BY_ADMIN_FILESTORE_READBACK'};
}

export function privateDisplayName(ref){return'recognized-'+sha(Buffer.from(ref.sourceReference))+'-'+ref.sha256+'-'+ref.source.filename.split('/').at(-1);}
// No source payload reread and no uploads: final binding verifies the complete
// approved native file multiset after an interrupted/replayed operation.
export async function verifyRecognizedPrivateFiles({refs,target,actorUserId,approvedManifestSha256},api){
 references(refs,target,approvedManifestSha256);
 checkOwner(await api.context(),target,actorUserId,refs.length>0);const files=[];
 for(const ref of ordered(refs)){
  await api.verifySourceReference(ref);const name=privateDisplayName(ref);const rows=await api.findFiles(name);if(rows.length!==1)throw Error('Missing/duplicate native private reference');checkFile(rows[0],target,name);const got=await api.getFile(rows[0].id);checkFile(got.file,target,name);if(!Buffer.isBuffer(got.contents)||got.contents.length!==ref.bytes||sha(got.contents)!==ref.sha256)throw Error('Native private source multiset bytes mismatch');files.push({...ref,destinationFileId:String(rows[0].id),displayFilename:name});
 }
 return{status:'ALL_PRIVATE_REFERENCES_NATIVE_BYTES_VERIFIED',manifestSha256:approvedManifestSha256,files,studentDownloadRoute:'NOT_QUALIFIED_BY_ADMIN_FILESTORE_READBACK'};
}
