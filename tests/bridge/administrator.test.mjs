import assert from 'node:assert/strict';
import { authorizeAdministrator } from '../../bridge/policy.mjs';
const owner='gw-'+ 'a'.repeat(64)+'@example.invalid';
assert.equal(authorizeAdministrator(owner,owner),owner);
for(const [requested,configured] of [[owner,null],[owner,''],['gw-'+ 'b'.repeat(64)+'@example.invalid',owner],['admin@example.invalid',owner],[owner+'\n',owner]]) {
  assert.throws(()=>authorizeAdministrator(requested,configured),e=>e.status===403);
}

assert.equal(authorizeAdministrator(owner,[owner,'gw-'+'b'.repeat(64)+'@example.invalid']),owner);
assert.throws(()=>authorizeAdministrator(owner,[]));
