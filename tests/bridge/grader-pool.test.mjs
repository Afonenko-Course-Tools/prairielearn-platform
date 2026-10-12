import assert from 'node:assert/strict';
import { acquireLocalGrader } from '../../bridge/grader-pool.mjs';
let active=0,peak=0;
const seen=[];
await Promise.all(Array.from({length:10},(_,i)=>(async()=>{
  const release=await acquireLocalGrader();active++;peak=Math.max(peak,active);seen.push(i);
  try {await new Promise(r=>setTimeout(r,5));if(i===3)throw Error('synthetic failed job');}
  catch(error){assert.equal(error.message,'synthetic failed job');}
  finally {active--;release();release();}
})()));
assert.equal(peak,2);assert.equal(active,0);assert.deepEqual(seen,Array.from({length:10},(_,i)=>i));
const release=await acquireLocalGrader();release();
