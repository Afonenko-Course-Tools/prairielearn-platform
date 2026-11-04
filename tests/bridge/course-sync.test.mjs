import assert from 'node:assert/strict';
import {authorizeCourseSync} from '../../tools/course-sync-policy.mjs';
const uuid='12345678-1234-5678-9234-123456789abc',path='/course/system-practice/current';
const request={path,courseUuid:uuid,infoUuid:uuid};
assert.equal(authorizeCourseSync(request,[{deliveryPath:path}]),path);
assert.equal(authorizeCourseSync({...request,courseUuid:null},[{deliveryPath:path}]),path);
for(const changed of [{path:'/course/other/current'},{path:'/course/system-practice/../current'},{infoUuid:'77777777-7777-4777-8777-777777777777'}])assert.throws(()=>authorizeCourseSync({...request,...changed},[{deliveryPath:path}]));
