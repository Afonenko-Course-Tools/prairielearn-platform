import assert from 'node:assert/strict';
import {test} from 'node:test';
import {existsSync} from 'node:fs';
import {mkdtemp,mkdir,writeFile,rm,symlink} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createHash} from 'node:crypto';
import {canonicalJSONString} from '../../bridge/policy.mjs';
const modulePath=new URL('../../tools/native-course-payload.mjs',import.meta.url);
test('verified native payload reader exists',()=>assert.ok(existsSync(modulePath),'Bootstrap payload validation is missing'));
if(existsSync(modulePath)) {
 const {readNativeCoursePayload}=await import(modulePath.href);
 const hash=s=>createHash('sha256').update(s).digest('hex');
 async function fixture(run,candidate=false) {
  const root=await mkdtemp(join(tmpdir(),'native-bootstrap-'));
  const info='{"name":"SYN","title":"Synthetic","timezone":"Europe/Minsk"}';
  const q='demo/exr-a',slot='demo/lab/exr-a';
  const payload={schemaVersion:3,courseId:'demo',bookRoot:'tasks',sourceSnapshotHash:'a'.repeat(64),inventoryHash:'b'.repeat(64),verificationInventoryHash:'c'.repeat(64),questions:[q],gradingPayloads:{[q]:{uuid:'37d79ee7-fd7d-44db-bd45-6587711862a5',grading:{method:'manual'},submission:{mode:'upload'},sourceRoot:'projects/a'}},works:[{id:'lab',slots:[{id:slot,selection:'fixed',candidates:[q],assignment:{requirement:'required',workMode:'individual'}}],policy:{},completion:{schemaVersion:2,mode:'required-slot-completion',source:'per-slot-results-v2',slotIds:[slot],requiredSlotIds:[slot],atLeast:1,fullyCompletedScore:1}}],instances:{fixture:{works:['lab'],selfEnrollment:false}},files:{'infoCourse.json':hash(info)},...(candidate?{candidate:true}:{})};
  const digest=hash(canonicalJSONString(payload)),path=join(root,digest);
  await mkdir(path);await writeFile(join(path,'infoCourse.json'),info);
  await writeFile(join(path,'delivery.json'),JSON.stringify({...payload,deliveryHash:digest}));
  try{await run(path,root);}finally{await rm(root,{recursive:true,force:true});}
 }
 test('valid immutable manifest resolves hashed native metadata',()=>fixture(async path=>{
  const result=await readNativeCoursePayload(path);assert.equal(result.info.name,'SYN');assert.equal(result.delivery.schemaVersion,3);
 }));
 test('tampered native metadata rejects before bootstrap',()=>fixture(async path=>{
  await writeFile(join(path,'infoCourse.json'),'{}');await assert.rejects(()=>readNativeCoursePayload(path),/payload changed/);
 }));
 test('symlinked metadata and root reject before bootstrap',()=>fixture(async(path,root)=>{
  await rm(join(path,'infoCourse.json'));await writeFile(join(root,'foreign.json'),'{}');await symlink(join(root,'foreign.json'),join(path,'infoCourse.json'));
  await assert.rejects(()=>readNativeCoursePayload(path),/Symlink/);
  await symlink(path,join(root,'alias'));await assert.rejects(()=>readNativeCoursePayload(join(root,'alias')),/Symlink/);
 }));
 test('candidate payload cannot create a production native institution',()=>fixture(async path=>{
  await assert.rejects(()=>readNativeCoursePayload(path),/Candidate/);
 },true));
}
