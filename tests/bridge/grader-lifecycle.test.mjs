import assert from 'node:assert/strict';
import {test} from 'node:test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import vm from 'node:vm';
import EventEmitter from 'node:events';
import {spawnSync} from 'node:child_process';

const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'grader-lifecycle-'));
/** @type {string} */let source;
try {
  const input = path.join(scratch, 'externalGraderLocal.js');
  fs.copyFileSync(new URL('../fixtures/native-grader-upstream/externalGraderLocal.js', import.meta.url), input);
  const patch = spawnSync('python3', ['-B', new URL('../../images/prairielearn/patch-local-grader.py', import.meta.url).pathname, input], {encoding:'utf8'});
  assert.equal(patch.status, 0, patch.stderr);
  source = fs.readFileSync(input, 'utf8').replace(/^import .*;\n/gm, '')
    .replace('export class ExternalGraderLocal', 'globalThis.ExternalGraderLocal = class ExternalGraderLocal')
    .replace('import.meta.url', JSON.stringify('file:///fixture/externalGraderLocal.js'));
} finally { fs.rmSync(scratch, {recursive:true}); }
let serial = 0;
/** @overload @param {string} failure @param {string} [cleanup] @returns {Promise<import("../../types/test-contracts.d.ts").LifecycleResult>} */
/** @overload @param {string} failure @param {string} cleanup @param {(env:import("../../types/test-contracts.d.ts").LifecycleExercise)=>Promise<void>} exercise @returns {Promise<void>} */
/** @param {string} failure @param {string} [cleanup] @param {(env:import("../../types/test-contracts.d.ts").LifecycleExercise)=>Promise<void>} [exercise] */
async function run(failure, cleanup='success', exercise) {
  const {acquireLocalGrader} = /** @type {typeof import('../../bridge/grader-pool.mjs')} */(await import(new URL(`../../bridge/grader-pool.mjs?test=${++serial}`, import.meta.url).href));
  /** @type {string[]} */const events=[];/** @type {Map<number,()=>void>} */const timers=new Map();
  let active=0, running=false, timerId=0;/** @type {(()=>void)|undefined} */let finishCleanup;
  /** @type {Array<()=>void>} */const cleanupResolvers=[];
  const problem=new Error(`Docker ${failure}`);
  const container={
    async attach() { events.push('attach'); if(failure==='attach') throw problem; return {}; },
    async start() { events.push('start'); running=true; if(failure==='start') throw problem; },
    async wait() { events.push('wait'); if(failure==='wait') throw problem; running=false; },
    async inspect() {
      events.push('inspect');
      if(cleanup==='unknown' || failure==='inspect'&&!events.includes('remove')) throw problem;
      return {State:{Running:running,ExitCode:failure==='student'?1:0}};
    },
    /** @param {{force:boolean}} options @returns {Promise<void>} */
    async remove(options) {
      events.push('remove');
      if(cleanup==='hang') return new Promise(resolve=>{finishCleanup=()=>{running=false;resolve();};});
      if(cleanup==='deferred') return new Promise(resolve=>{cleanupResolvers.push(resolve);});
      if(cleanup==='404') {running=false;throw Object.assign(new Error('absent'),{statusCode:404});}
      if(cleanup==='stopped') {running=false;throw new Error('remove denied');}
      if(cleanup==='unknown') throw new Error('remove denied');
      assert.equal(options.force,true,'known container must be force-removed'); running=false;
    },
    async kill() {running=false;},
  };
  const context={EventEmitter,os,path,process,
    setTimeout(/** @type {()=>void} */fn,/** @type {number} */ms) {
      if(ms===0) return setTimeout(fn,0);
      const id=++timerId;timers.set(id,fn);
      if(cleanup==='hang'&&ms===10_000) queueMicrotask(fn);
      return id;
    },
    clearTimeout(/** @type {number} */id) {timers.delete(id);},
    acquireLocalGrader:async()=>{
      const release=await acquireLocalGrader();active++;events.push('acquire');
      return()=>{events.push('release');active--;release();};
    },
    Docker:class {async ping(){if(failure==='ping') throw problem;} async createContainer(){events.push('create');if(failure==='create') throw problem;return container;}},
    byline:()=>({on(){}}),
    config:{externalGradingDefaultTimeout:30,externalGradingMaximumTimeout:600,externalGradingPullImagesFromDockerHub:false},
    sqldb:{loadSqlEquiv(){return{};},async execute(){}},
    buildDirectory:async()=>{},logger:{info(){},error(){}},
    readFileWithinDirectory:async()=>'{"score":1}',makeGradingResult:/** @template T @param {unknown} _id @param {T} result */(_id,result)=>result,
  };
  vm.createContext(context);vm.runInContext(source,context);
  /** @returns {Promise<import("../../types/test-contracts.d.ts").GradingResult>} */
  const submit=()=>new Promise(resolve=>{
    new (/** @type {typeof context & {ExternalGraderLocal:new()=>{handleGradingRequest(...args:unknown[]):EventEmitter}}} */(context).ExternalGraderLocal)().handleGradingRequest({id:'1'},{},{},{external_grading_image:'fictional@sha256:000',external_grading_environment:{}},{})
      .once('error',/** @param {Error} error */error=>resolve({error})).once('results',/** @param {{succeeded:boolean}} value */value=>resolve({value}));
  });
  if(exercise) return exercise({submit,events,cleanupResolvers,get active(){return active;}});
  const result=await submit();
  return {result,events,active,running,timers,finishCleanup,get currentActive(){return active;}};
}
for(const failure of ['attach','start','wait','inspect']) {
  test(`ошибка ${failure}: очистка до освобождения слота`,async()=>{
    const o=await run(failure);assert.ok(o.result.error,'Docker error stays infrastructure failure');
    assert.equal(o.result.error.message,`Docker ${failure}`,'preserve the original grading error');
    assert.equal(o.running,false);assert.ok(o.events.includes('remove'),'failure path must remove known container');
    assert.ok(o.events.indexOf('remove')<o.events.indexOf('release'));assert.equal(o.active,0);
    assert.equal(o.timers.size,0,'watchdog must be cleared');
  });
}
test('успех: очистка и отмена watchdog',async()=>{
  const o=await run('none');assert.ok(o.result.value?.succeeded);assert.equal(o.active,0);assert.equal(o.timers.size,0);
});
for(const cleanup of ['404']) {
  test(`ошибка start, cleanup ${cleanup}: безопасный слот освобождён`,async()=>{
    const o=await run('start',cleanup);assert.ok(o.result.error);assert.equal(o.running,false);assert.equal(o.active,0);assert.equal(o.timers.size,0);
  });
}
for(const cleanup of ['unknown','hang','stopped']) {
  test(`ошибка start, cleanup ${cleanup}: слот удерживается`,async()=>{
    const o=await run('start',cleanup);assert.ok(o.result.error);assert.ok(o.result.error.errors);assert.equal(o.result.error.errors[0].message,'Docker start');
    assert.equal(o.active,1,'unknown container must retain slot');
    assert.ok(!o.events.includes('release'));assert.equal(o.events.includes('inspect'),false,'no snapshot fallback after ambiguous start');assert.equal(o.timers.size,0);
  });
}

test('ожидающая задача не начинает работу до подтверждённой очистки',async()=>{
  await run('start','deferred',async env=>{
    const jobs=[env.submit(),env.submit(),env.submit()];
    await new Promise(setImmediate);
    assert.equal(env.events.filter(v=>v==='create').length,2);
    assert.equal(env.active,2);assert.equal(env.events.includes('release'),false);
    const complete=env.cleanupResolvers.shift();assert.ok(complete);complete();
    await jobs[0];await new Promise(setImmediate);
    assert.equal(env.events.filter(v=>v==='create').length,3);
    assert.ok(env.events.indexOf('release')<env.events.lastIndexOf('create'));
    for(const complete of env.cleanupResolvers) complete();
    await Promise.all(jobs);assert.equal(env.active,0);
  });
});
test('поздняя очистка после timeout не освобождает удержанный слот',async()=>{
  const o=await run('start','hang');assert.equal(o.currentActive,1);
  assert.ok(o.finishCleanup);o.finishCleanup();await new Promise(setImmediate);
  assert.equal(o.currentActive,1);assert.equal(o.events.includes('release'),false);
});

for(const failure of ['ping','create']) {
  test(`ошибка ${failure} до получения контейнера освобождает слот`,async()=>{
    const o=await run(failure);assert.ok(o.result.error);assert.equal(o.result.error.message,`Docker ${failure}`);
    assert.equal(o.active,0);assert.equal(o.events.includes('remove'),false);assert.equal(o.timers.size,0);
  });
}
test('неуспех студенческого процесса сохраняется обычным результатом',async()=>{
  const o=await run('student');assert.equal(o.result.error,undefined);
  assert.ok(o.result.value);assert.equal(o.result.value.succeeded,false);assert.equal(o.active,0);assert.ok(o.events.includes('remove'));
});
