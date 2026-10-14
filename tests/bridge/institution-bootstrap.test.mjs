import assert from 'node:assert/strict';
import {existsSync} from 'node:fs';
import {test} from 'node:test';
const modulePath=new URL('../../tools/institution-bootstrap.mjs',import.meta.url);
test('institution bootstrap exists before native imports',()=>assert.ok(existsSync(modulePath),'Generic institution bootstrap is missing'));
if(existsSync(modulePath)) {
 const {resolveInstitution,bootstrapNativeCourse,validateInstitutionCatalog}=await import(modulePath.href);
 const descriptor={shortName:'SYN',longName:'Synthetic University',displayTimezone:'Europe/Minsk',uidRegexp:null};
 const catalog={schema:'pl-institutions-v1',institutions:{synthetic:descriptor}};
 const registry={schema:'pl-courses-v2',courses:[{id:'course-a',institution:'synthetic',repository:'https://example.test/native.git',commit:'a'.repeat(40),mount:'/course'}]};
 function nativeStore() {
  const institutions=[],courses=[];let lockTail=Promise.resolve();
  return {institutions,courses,
   withLock(name,fn){const previous=lockTail;let release;lockTail=new Promise(r=>release=r);return previous.then(fn).finally(()=>release());},
   async selectAllInstitutions(){return institutions;},
   async insertInstitution(d){const id=String(institutions.length+1);institutions.push({id,short_name:d.shortName,long_name:d.longName,display_timezone:d.displayTimezone,uid_regexp:d.uidRegexp});return id;},
   async selectOptionalCourseByPath(path){return courses.find(c=>c.path===path)??null;},
   async insertCourse(course){const row={...course,id:String(courses.length+1)};courses.push(row);return row;},
  };
 }
 test('creates and resolves the same native institution without duplicating it',async()=>{
  const native=nativeStore();assert.equal(await resolveInstitution(catalog,'synthetic',native),'1');
  assert.equal(await resolveInstitution(catalog,'synthetic',native),'1');assert.equal(native.institutions.length,1);
  assert.equal(native.institutions[0].long_name,'Synthetic University');
 });
 test('another descriptor follows the same bootstrap without code changes',async()=>{
  const native=nativeStore();const other={...catalog,institutions:{...catalog.institutions,other:{...descriptor,shortName:'ALT',longName:'Another University'}}};
  assert.equal(await resolveInstitution(other,'synthetic',native),'1');assert.equal(await resolveInstitution(other,'other',native),'2');
  assert.equal(native.institutions[1].short_name,'ALT');
 });
 test('unknown key never falls back to Default or mutates native state',async()=>{
  const native=nativeStore();await assert.rejects(()=>resolveInstitution(catalog,'unknown',native),/Unknown institution/);
  assert.equal(native.institutions.length,0);
 });
 test('existing conflicting descriptor is rejected without rewriting native institution',async()=>{
  const native=nativeStore();await resolveInstitution(catalog,'synthetic',native);
  const changed={...catalog,institutions:{synthetic:{...descriptor,longName:'Changed name'}}};
  await assert.rejects(()=>resolveInstitution(changed,'synthetic',native),/descriptor differs/);
  assert.equal(native.institutions[0].long_name,'Synthetic University');
 });
 test('serialized concurrent bootstrap creates one institution',async()=>{
  const native=nativeStore();assert.deepEqual(await Promise.all([resolveInstitution(catalog,'synthetic',native),resolveInstitution(catalog,'synthetic',native)]),['1','1']);
  assert.equal(native.institutions.length,1);
 });
 test('native IDs and malformed descriptors fail before adapter use',()=>{
  for(const d of [{...descriptor,id:'4'},{...descriptor,displayTimezone:'Not/AZone'},{...descriptor,shortName:''}]) {
   assert.throws(()=>validateInstitutionCatalog({...catalog,institutions:{synthetic:d}}));
  }
 });
 const info={name:'Synthetic',title:'Synthetic course',timezone:'Europe/Minsk'};
 const request={registry,catalog,courseKey:'course-a',path:'/course/course-a/'+'f'.repeat(64),info,actorId:'7'};
 test('native course uses resolved institution ID and stable repeat ID',async()=>{
  const native=nativeStore();const first=await bootstrapNativeCourse(request,native);const repeated=await bootstrapNativeCourse(request,native);
  assert.equal(first.id,'1');assert.equal(repeated.id,'1');assert.equal(native.courses.length,1);
  assert.equal(first.institution_id,'1');assert.equal(first.authn_user_id,'7');assert.equal(first.repository,null);
 });
 test('existing course in a different institution is never migrated',async()=>{
  const native=nativeStore();native.courses.push({id:'42',path:request.path,institution_id:'9'});
  await assert.rejects(()=>bootstrapNativeCourse(request,native),/institution mismatch/);
  assert.equal(native.courses[0].institution_id,'9');assert.equal(native.courses.length,1);
 });
 test('unknown course or institution and malformed registry reject before creation',async()=>{
  for(const r of [{...request,courseKey:'unknown'},{...request,registry:{...registry,courses:[{...registry.courses[0],institution:'unknown'}]}},{...request,registry:{...registry,courses:[{...registry.courses[0],institution_id:'4'}]}}]) {
   const native=nativeStore();await assert.rejects(()=>bootstrapNativeCourse(r,native));assert.equal(native.courses.length,0);assert.equal(native.institutions.length,0);
  }
 });
 test('bootstrap rejects unscoped path and absent verified actor',async()=>{
  for(const r of [{...request,path:'/course/another/'+'f'.repeat(64)},{...request,actorId:null}]) {
   const native=nativeStore();await assert.rejects(()=>bootstrapNativeCourse(r,native));assert.equal(native.courses.length,0);assert.equal(native.institutions.length,0);
  }
 });
}
