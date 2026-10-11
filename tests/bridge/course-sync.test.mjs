import assert from 'node:assert/strict';
import { authorizeCourseSync } from '../../tools/course-sync-policy.mjs';
const hash='a'.repeat(64),uuid='12345678-1234-5678-9234-123456789abc';
const path='/course/system-practice/'+hash;
const request={path,deliveryHash:hash,courseUuid:uuid,infoUuid:uuid};
assert.equal(authorizeCourseSync(request,[{deliveryPath:path}]),path);
assert.equal(authorizeCourseSync({...request,courseUuid:null},[{deliveryPath:path}]),path);
for(const changed of [{path:'/course/java/'+hash},{path:path+'/../x'},{deliveryHash:'b'.repeat(64)},{courseUuid:'87654321-1234-5678-9234-123456789abc'}]) {
 assert.throws(()=>authorizeCourseSync({...request,...changed},[{deliveryPath:path}]));
}
