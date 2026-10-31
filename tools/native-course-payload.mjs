import {readFile,lstat} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {isAbsolute,resolve,basename} from 'node:path';
import {bridgeDeliverySchema} from '../bridge/delivery.mjs';
import {canonicalJSONString} from '../bridge/policy.mjs';

/** Чтение immutable payload до соединения с native БД. */
export async function readNativeCoursePayload(path) {
 if(typeof path!=='string'||!isAbsolute(path)||resolve(path)!==path)throw new Error('Absolute immutable native path required');
 async function containedFile(name) {
  if(typeof name!=='string'||name.startsWith('/')||name.includes('\\')||name.split('/').some(s=>['','.','..'].includes(s)))throw new Error('Unsafe inventory path');
  let current='';
  for(const part of (path+'/'+name).split('/').filter(Boolean)) {current+='/'+part;if((await lstat(current)).isSymbolicLink())throw new Error('Symlink inventory');}
  return readFile(path+'/'+name);
 }
 const delivery=JSON.parse(await containedFile('delivery.json'));
 const info=JSON.parse(await containedFile('infoCourse.json'));
 if(!delivery||![3,4].includes(delivery.schemaVersion)||!delivery.files||typeof delivery.files!=='object'||Array.isArray(delivery.files)||!Object.hasOwn(delivery.files,'infoCourse.json'))throw new Error('Course metadata absent from native v3 inventory');
 bridgeDeliverySchema.parse(delivery);
 const {deliveryHash,...payload}=delivery;
 if(createHash('sha256').update(canonicalJSONString(payload)).digest('hex')!==deliveryHash||basename(path)!==deliveryHash)throw new Error('Delivery hash mismatch');
 if(delivery.candidate)throw new Error('Candidate payload requires separate diagnostic verification; production bootstrap rejected');
 for(const [name,hash] of Object.entries(delivery.files)) {
  if(typeof hash!=='string'||!/^[a-f0-9]{64}$/.test(hash)||createHash('sha256').update(await containedFile(name)).digest('hex')!==hash)throw new Error('Native payload changed');
 }
 return {delivery,info};
}
