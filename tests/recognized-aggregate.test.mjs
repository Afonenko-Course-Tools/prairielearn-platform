// Genuine pinned dist aggregate: reviewer counterexample, fictional SQL I/O only.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {test} from 'node:test';
const file=/** @type {string} */(process.argv.find(v=>v.startsWith('--aggregate='))).slice('--aggregate='.length);
const text=readFileSync(file,'utf8').replace(/^import[\s\S]*?from ['"][^'"]+['"];\s*/gm,'').replace(/\bexport (?=(?:async )?function|const|class)/g,'').replaceAll('import.meta.url',JSON.stringify('file:///fictional/dist/lib/assessment-grading.js'));
/** @type {import("../types/test-contracts.d.ts").SchemaProxy} */
const schema=/** @type {import("../types/test-contracts.d.ts").SchemaProxy} */(new Proxy(function(){return schema;},{get:()=>schema,apply:()=>schema}));
/** @param {{lastCredit?:number|null,credit?:number|null,recognized?:number,points?:number,maxPoints?:number,precomputedPointsByZone?:{points:number,iq_ids:string[]}[],failHook?:boolean}} options */
async function aggregate({lastCredit=null,credit=null,recognized=1,points=100,maxPoints=100,precomputedPointsByZone,failHook=false}){
 const ai={id:'25',max_points:maxPoints,max_bonus_points:0,points:0,score_perc:0};
/** @type {{saved?:Record<string,unknown>}} */
const state={};let calls=0,lastReads=0;
 const ctx=vm.createContext({z:schema,IdSchema:schema,AssessmentInstanceSchema:schema,SubmissionSchema:schema,loadSqlEquiv:()=>new Proxy({},{get:(_,k)=>k}),
/** @template T @param {()=>Promise<T>} f */
 runInTransactionAsync:async f=>f(),queryRow:async()=>ai,queryOptionalScalar:async()=>{lastReads++;return lastCredit;},queryRows:async()=>[{zone_id:'1',points,iq_ids:['26','27'],max_points:maxPoints,max_iq_ids:['26','27']}],execute:async(/** @type {string} */q,
/** @type {Record<string,unknown>} */p)=>{assert.equal(q,'update_assessment_instance_grade');state.saved=p;},applyRecognizedCredit:async()=>{calls++;if(failHook)throw Error('trusted source I/O failed');return recognized;}});
 new vm.Script(text+'\nglobalThis.entry=updateAssessmentInstanceGrade;').runInContext(ctx);
 const result=await /** @type {(args:Record<string,unknown>)=>Promise<{score_perc:number,points:number}>} */(ctx.entry)({assessment_instance_id:'25',authn_user_id:'99',credit,onlyLogIfScoreUpdated:true,precomputedPointsByZone});
 assert.equal(calls,1);const saved=state.saved;assert.ok(saved);assert.equal(saved.score_perc,result.score_perc);assert.equal(saved.points,result.points);
 return {result,saved,lastReads};
}
for(const lastCredit of [null,0,50,100])test('recognized fresh AI: actual native aggregate100, last credit '+lastCredit,async()=>{const {result}=await aggregate({lastCredit});assert.equal(result.points,100);assert.equal(result.score_perc,100);});
test('explicit low credit from later failed/ungradable completion cannot revoke recognition',async()=>{assert.equal((await aggregate({credit:0,lastCredit:50})).result.score_perc,100);});
test('ordinary AI retains native last-submission limit and stale precomputed semantics',async()=>{for(const lastCredit of [null,0,50,100]){const {result,lastReads}=await aggregate({recognized:0,lastCredit,precomputedPointsByZone:[{points:70,iq_ids:['27']}]});assert.equal(result.points,70);assert.equal(result.score_perc,Math.min(70,lastCredit??0));assert.equal(lastReads,1);}});
test('recognition never grants unrelated IQ points or force-max: native mixed zone aggregate60/100',async()=>{const {result}=await aggregate({points:60,lastCredit:0,precomputedPointsByZone:[{points:0,iq_ids:[]}]});assert.equal(result.points,60);assert.equal(result.score_perc,60);});
test('native bonus credit and maximum points remain effective',async()=>{assert.equal((await aggregate({lastCredit:120})).result.score_perc,120);const {result}=await aggregate({points:140,lastCredit:50});assert.equal(result.points,100);assert.equal(result.score_perc,100);});
test('trusted recognition I/O failure does not persist an aggregate',async()=>{await assert.rejects(aggregate({failHook:true}),/trusted source I\/O failed/);});
