import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {bridgeDeliverySchema} from './delivery.mjs';
import {canonicalJSONString,validateBindings} from './policy.mjs';
// Один существующий delivery verifier для server и внутреннего E-адаптера.
export async function loadVerifiedBindings(settings){
 const bindings=[];
 for(const binding of settings){
  const delivery=bridgeDeliverySchema.parse(JSON.parse(await readFile(`${binding.deliveryPath}/delivery.json`,'utf8')));
  const {deliveryHash,...payload}=delivery;
  if(createHash('sha256').update(canonicalJSONString(payload)).digest('hex')!==deliveryHash)throw Error('Delivery hash mismatch');
  for(const [path,hash]of Object.entries(delivery.files)){
   if(path.startsWith('/')||path.split('/').includes('..'))throw Error('Unsafe delivery path');
   if(createHash('sha256').update(await readFile(`${binding.deliveryPath}/${path}`)).digest('hex')!==hash)throw Error('Delivery file mismatch');
  }
  bindings.push({...binding,delivery});
 }
 validateBindings(bindings);return bindings;
}
