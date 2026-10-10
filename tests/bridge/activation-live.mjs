// Run inside the pinned native app; temporary table only, no managed journal writes.
import assert from 'node:assert/strict';
import * as db from '@prairielearn/postgres';
import { z } from 'zod';
import { config, loadConfig } from './dist/lib/config.js';
await loadConfig(['/PrairieLearn/config.json']);
await db.initAsync({user:config.postgresqlUser,database:config.postgresqlDatabase,host:config.postgresqlHost,password:config.postgresqlPassword??undefined,max:4},console.error);
const sql=db.loadSqlEquiv('/PrairieLearn/apps/prairielearn/bridge/native.mjs');
let releaseStarted, locked;
const started=new Promise(r=>releaseStarted=r), acquired=new Promise(r=>locked=r);
const holder=db.runInTransactionAsync(async()=>{
 await db.execute(sql.lock,{lock_key:'gateway-activation-regression'});locked();await started;
 await db.execute('SELECT pg_sleep(1)',{});
});
await acquired;
const waiter=db.runInTransactionAsync(async()=>{
 await db.execute('CREATE TEMP TABLE pl_gateway_assignments (id text PRIMARY KEY,course_instance_id bigint,user_uid text,request jsonb,updated_at timestamptz DEFAULT now()) ON COMMIT DROP',{});
 const row=await db.queryRow('SELECT extract(epoch FROM now())::float8 AS t',{},z.object({t:z.number()}));
 releaseStarted();await db.execute(sql.lock,{lock_key:'gateway-activation-regression'});
 const params={id:'clock-test',course_instance_id:'1',user_uid:'clock-test',request:'{}'};
 await db.execute(sql.store_assignment,params);
 const first=await db.queryRow('SELECT extract(epoch FROM updated_at)::float8 AS t FROM pl_gateway_assignments',{},z.object({t:z.number()}));
 assert.ok(first.t-row.t>=0.9,'first activation predates completed lock wait');
 await db.execute('SELECT pg_sleep(0.1)',{});await db.execute(sql.store_assignment,params);
 const second=await db.queryRow('SELECT extract(epoch FROM updated_at)::float8 AS t FROM pl_gateway_assignments',{},z.object({t:z.number()}));
 assert.ok(second.t>first.t,'same-work regrant activation must advance');
 console.log(JSON.stringify({lockWaitSeconds:first.t-row.t,regrantAdvanceSeconds:second.t-first.t,activationAfterLock:true,sameWorkNewVersionExcludesEarlierAttempts:true}));
});
try{await Promise.all([holder,waiter]);}finally{await db.closeAsync();}
