// Настоящие C packages, data-only schemas; no DB/network/native lifecycle.
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {bridgeDeliverySchema} from '../bridge/delivery.mjs';
const root=process.env.PL_DELIVERY4_FIXTURES;if(!root)throw Error('Actual C fixtures required');
let positives=0,refusals=0;
for(const name of fs.readdirSync(root)) {
 const d=JSON.parse(fs.readFileSync(root+'/'+name+'/delivery.json'));
 bridgeDeliverySchema.parse(d);positives++;
 const q=d.questions[0];
 for(const change of [v=>delete v.gradingPayloads[q].kind,v=>v.gradingPayloads[q].kind='unknown',v=>v.schemaVersion=3,v=>v.schemaVersion=4,v=>v.gradingPayloads[q].secretKey=734129,v=>v.gradingPayloads[q].grading.method='unknown']) {
  const v=structuredClone(d);change(v);assert.equal(bridgeDeliverySchema.safeParse(v).success,false);refusals++;
 }
}
console.log(JSON.stringify({ordinaryBuilderPackages:positives,closedMutants:refusals,assignmentQualified:false}));
