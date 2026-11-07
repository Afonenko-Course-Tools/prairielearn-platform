// PostgreSQL18 WASM parser: syntax/AST + pinned native schema projection only.
// Ни сервер PostgreSQL, ни миграция/запросы здесь не исполняются.
import assert from 'node:assert/strict';import {readFile} from 'node:fs/promises';import {test} from 'node:test';import {parse} from 'pgsql-parser';
import {pg,present} from './helpers/pg-nodes.mjs';
const files=['bridge/recognized-credit-native.sql','bridge/native.sql'];
const types=await readFile(new URL('./fixtures/native-credit-upstream/dist/lib/db-types.js',import.meta.url),'utf8');
/** @type {Record<string,Set<string>>} */
const schemas={};for(const [table,name]of Object.entries({assessment_instances:'AssessmentInstance',assessments:'Assessment',assessment_questions:'AssessmentQuestion',instance_questions:'InstanceQuestion',questions:'Question',course_instances:'CourseInstance',courses:'Course',users:'User',grading_jobs:'GradingJob',submissions:'Submission',variants:'Variant',audit_logs:'AuditLog',files:'File',administrators:'Administrator'})){const m=types.match(new RegExp('export const '+name+'Schema = z.object\\(\\{([\\s\\S]*?)\\n\\}\\);'));assert.ok(m,'Pinned native schema '+name);schemas[table]=new Set([...m[1].matchAll(/^    ([a-z_0-9]+):/gm)].map(v=>v[1]));}
schemas.question_score_logs=new Set(['instance_question_id','auth_user_id','max_points','max_manual_points','max_auto_points','points','score_perc','auto_points','manual_points']);
/** @param {string} text */
function blocks(text){return Object.fromEntries([...text.matchAll(/^-- BLOCK ([a-z_0-9]+)\n([\s\S]*?)(?=^-- BLOCK |$(?![\s\S]))/gm)].map(m=>[m[1],m[2]]));}
// Named placeholders are values, not identifiers. Existing source has no dollar
// quotes; leave comments/quoted strings untouched while numbering its values.
/** @param {string} text */
function bound(text){let i=0;return text.replace(/'(?:''|[^'])*'|--[^\n]*|\$[a-zA-Z][a-zA-Z_0-9]*/g,t=>t.startsWith('$')?'$'+(++i):t);}
/** @param {unknown} v @param {(node:Record<string,unknown>)=>void} fn */
function walk(v,fn){if(!v||typeof v!=='object')return;fn(/** @type {Record<string,unknown>} */(v));for(const x of Object.values(v))if(Array.isArray(x))x.forEach(x=>walk(x,fn));else walk(x,fn);}
/** @type {Record<string,Awaited<ReturnType<typeof parse>>>} */
const parsed={};for(const file of files){const sql=await readFile(new URL('../'+file,import.meta.url),'utf8');for(const [name,value]of Object.entries(blocks(sql)))parsed[file+':'+name]=await parse(bound(value));}
/** @param {unknown} ast */
function footprint(ast){
 /** @type {Array<{kind:string,table:string,columns:string[]}>} */
const writes=[];
 walk(ast,v=>{for(const type of /** @type {const} */(['InsertStmt','UpdateStmt','DeleteStmt']))if(v[type]){
  const relation=type==='InsertStmt'?pg(v,'InsertStmt').relation:type==='UpdateStmt'?pg(v,'UpdateStmt').relation:pg(v,'DeleteStmt').relation,cols=type==='InsertStmt'?pg(v,'InsertStmt').cols:type==='UpdateStmt'?pg(v,'UpdateStmt').targetList:[];
  writes.push({kind:type,table:present(present(relation).relname),columns:present(cols).map(c=>present(pg(c,'ResTarget').name)).sort()});
 }});return writes.sort((a,b)=>a.table.localeCompare(b.table)||a.kind.localeCompare(b.kind));
}

test('all authored SQL blocks parse with real PostgreSQL parser and columns match pinned native schemas',()=>{for(const [name,ast]of Object.entries(parsed)){
/** @type {Record<string,string>} */
const aliases={};walk(ast,v=>{if(v.RangeVar){const r=pg(v,'RangeVar');aliases[present(r.alias?.aliasname??r.relname)]=present(r.relname);}});walk(ast,v=>{if(v.ColumnRef){const f=present(pg(v,'ColumnRef').fields).map(s=>s&&typeof s==='object'&&'String' in s?pg(s,'String').sval:undefined);if(f.length===2&&f[0]&&f[1]&&schemas[aliases[f[0]]])assert.ok(schemas[aliases[f[0]]].has(f[1]),name+' unknown '+f.join('.'));}for(const w of footprint(v)){if(schemas[w.table])for(const c of w.columns)assert.ok(schemas[w.table].has(c),name+' unknown write '+w.table+'.'+c);}});}});
test('recognition writes only exact IQ score/admin audit/log plus optional Manual job, never raw submission',()=>{const rows=Object.entries(parsed).filter(([n])=>n.startsWith('bridge/recognized-credit-native.sql:')).flatMap(([name,ast])=>footprint(ast).map(w=>({block:name.split(':')[1],...w})));assert.deepEqual(rows.map(r=>[r.block,r.kind,r.table]),[['insert_event','InsertStmt','audit_logs'],['repair','UpdateStmt','instance_questions'],['repair','InsertStmt','question_score_logs'],['insert_manual_job','InsertStmt','grading_jobs']]);const repair=rows.find(r=>r.table==='instance_questions');assert.ok(repair);assert.deepEqual(repair.columns,['auto_points','is_ai_graded','last_grader','manual_points','modified_at','points','requires_manual_grading','score_perc','status']);assert.ok(!repair.columns.includes('open'));});
