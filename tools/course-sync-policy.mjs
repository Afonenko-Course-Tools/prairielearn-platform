import { resolve } from 'node:path';
export function authorizeCourseSync(request,bindings) {
 const {path,courseUuid,infoUuid}=request;
 if(typeof path!=='string'||!path.startsWith('/course/')||resolve(path)!==path||!bindings.some(b=>b.deliveryPath===path))throw new Error('Unknown immutable native path');
 if(!/^[a-f0-9-]{36}$/.test(infoUuid)||courseUuid!==null&&courseUuid!==infoUuid)throw new Error('Cannot replace another native course UUID');
 return path;
}
