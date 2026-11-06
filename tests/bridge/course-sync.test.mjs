import assert from 'node:assert/strict';
import {test} from 'node:test';
import * as policy from '../../tools/course-sync-policy.mjs';
const uuid='12345678-1234-5678-9234-123456789abc',path='/course/demo/current';
const request={path,sourceCourseId:'demo',previousSourceCourseId:'demo',courseUuid:uuid,infoUuid:uuid};
test('sync binds normalized path to exact source ID and native UUID without Gateway',()=>{
 assert.equal(policy.authorizeCourseSync(request),path);
 assert.equal(policy.authorizeCourseSync({...request,courseUuid:null}),path);
 for(const changed of [{path:'/course/other/current'},{path:'/course/demo/../current'},{previousSourceCourseId:'other'},{infoUuid:'77777777-7777-4777-8777-777777777777'}])assert.throws(()=>policy.authorizeCourseSync({...request,...changed}));
});
test('operator requires exact existing native UID and administrator membership',async()=>{
 const actor={id:'9',uid:'operator@example.test'};
 const native={selectOptionalUserByUid:async uid=>uid===actor.uid?actor:null,isAdministrator:async id=>id==='9'};
 assert.deepEqual(await policy.verifyNativeAdministrator(actor.uid,native),actor);
 for(const uid of ['', 'other@example.test',' operator@example.test'])await assert.rejects(policy.verifyNativeAdministrator(uid,native));
 await assert.rejects(policy.verifyNativeAdministrator(actor.uid,{...native,isAdministrator:async()=>false}));
 await assert.rejects(policy.verifyNativeAdministrator(actor.uid,{...native,selectOptionalUserByUid:async()=>({...actor,uid:'wrong'})}));
});
const declared=[{uuid,short_name:'Autumn'}],row={id:'73',course_id:'7',uuid,short_name:'Autumn',deleted_at:null};
test('pre-sync rejects conflicting, deleted and ambiguous native identities before writes',()=>{
 assert.doesNotThrow(()=>policy.validateNativeInstances('7',declared,[]));
 assert.doesNotThrow(()=>policy.validateNativeInstances('7',declared,[row]));
 for(const rows of [[{...row,course_id:'8'}],[{...row,uuid:'77777777-7777-4777-8777-777777777777'}],[{...row,deleted_at:'yesterday'}],[row,{...row,id:'74'}]])assert.throws(()=>policy.validateNativeInstances('7',declared,rows));
});
test('post-sync requires each declared UUID and native short name in exact course',()=>{
 assert.deepEqual(policy.validateNativeInstances('7',declared,[row],true),[row]);
 for(const rows of [[],[{...row,course_id:'8'}],[{...row,short_name:'other'}]])assert.throws(()=>policy.validateNativeInstances('7',declared,rows,true));
});
test('declared identity follows native directory key and ignores deprecated shortName',async t=>{
 const {mkdtemp,mkdir,writeFile,rm}=await import('node:fs/promises');
 const {tmpdir}=await import('node:os');
 const root=await mkdtemp(tmpdir()+'/operator-ci-');t.after(()=>rm(root,{recursive:true}));
 await mkdir(root+'/courseInstances/fall',{recursive:true});
 const file='courseInstances/fall/infoCourseInstance.json';
 await writeFile(root+'/'+file,JSON.stringify({uuid,shortName:'Deprecated display name'}));
 assert.deepEqual(await policy.readDeclaredInstances(root,{instances:{fall:{}},files:[file]}),[{uuid,short_name:'fall'}]);
 await assert.rejects(policy.readDeclaredInstances(root,{instances:{fall:{}},files:[]}));
 await writeFile(root+'/'+file,JSON.stringify({uuid:'invalid'}));
 await assert.rejects(policy.readDeclaredInstances(root,{instances:{fall:{}},files:[file]}));
});
