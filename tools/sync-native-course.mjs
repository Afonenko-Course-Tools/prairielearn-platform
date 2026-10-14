import {bridgeDeliverySchema} from '../bridge/delivery.mjs';
/** Локальная операция администратора: sync ровно одной immutable поставки. */
import { readFile,lstat } from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {pathToFileURL} from 'node:url';
import * as db from '@prairielearn/postgres';
import * as namedLocks from '@prairielearn/named-locks';
import {z} from 'zod';
import {authorizeCourseSync} from './course-sync-policy.mjs';
import {authorizeAdministrator,canonicalJSONString} from '../bridge/policy.mjs';
import {selectRegistryCourse,resolveInstitution} from './institution-bootstrap.mjs';
const root=process.env.PL_ROOT??'/PrairieLearn';
const native=(path)=>import(pathToFileURL(`${root}/apps/prairielearn/dist/${path}.js`).href);
const args=process.argv.slice(2);
if(args.length<4||args[0]!=='--course-id'||!/^[1-9][0-9]*$/.test(args[1])||args[2]!=='--path')throw new Error('Use --course-id ID --path /course/ID/DELIVERY_HASH [--registry PATH --course-key KEY --institutions PATH]');
const id=args[1],path=args[3];
const options={};
for(let i=4;i<args.length;i+=2) {
 if(!['--registry','--course-key','--institutions'].includes(args[i])||!args[i+1]||Object.hasOwn(options,args[i]))throw new Error('Invalid registry sync options');
 options[args[i]]=args[i+1];
}
if(Boolean(options['--registry'])!==Boolean(options['--course-key'])||options['--institutions']&&!options['--registry'])throw new Error('Registry and course key must be supplied together');
const catalog=options['--registry']?JSON.parse(await readFile(options['--institutions']??new URL('../config/institutions.json',import.meta.url),'utf8')):null;
const record=options['--registry']?selectRegistryCourse(JSON.parse(await readFile(options['--registry'],'utf8')),options['--course-key'],catalog):null;
if(record&&!new RegExp('^/course/'+record.id+'/[a-f0-9]{64}$').test(path))throw new Error('Registry course path mismatch');
const settings=JSON.parse(await readFile(process.env.PL_GATEWAY_CONFIG,'utf8'));
const delivery=bridgeDeliverySchema.parse(JSON.parse(await readFile(path+'/delivery.json','utf8')));
const info=JSON.parse(await readFile(path+'/infoCourse.json','utf8'));
const {deliveryHash,...payload}=delivery;
if(createHash('sha256').update(canonicalJSONString(payload)).digest('hex')!==deliveryHash)throw new Error('Delivery hash mismatch');
for(const [name,hash] of Object.entries(delivery.files)) {
 if(name.startsWith('/')||name.includes('\\')||name.split('/').some(s=>['','.','..'].includes(s)))throw new Error('Unsafe inventory path');
 let current=path;
 for(const part of name.split('/')) {current+='/'+part;if((await lstat(current)).isSymbolicLink())throw new Error('Symlink inventory');}
 if(createHash('sha256').update(await readFile(current)).digest('hex')!==hash)throw new Error('Native payload changed');
}
const {config,loadConfig}=await native('lib/config');await loadConfig([root+'/config.json']);
const pg={user:config.postgresqlUser,database:config.postgresqlDatabase,host:config.postgresqlHost,password:config.postgresqlPassword??undefined,max:4};
await db.initAsync(pg,()=>{process.exitCode=1;});
await namedLocks.init(pg,()=>{process.exitCode=1;});
try {
 await db.setRandomSearchSchemaAsync('local-course-sync');await(await native('sprocs/index')).init();
 const courses=await native('models/course');let course=await courses.selectCourseById(id);
 const previousDelivery=JSON.parse(await readFile(course.path+'/delivery.json','utf8'));
 const previousInfo=JSON.parse(await readFile(course.path+'/infoCourse.json','utf8'));
 if(previousDelivery.courseId!==delivery.courseId)throw new Error('Cannot replace another source course ID');
 authorizeCourseSync({path,deliveryHash,courseUuid:previousInfo.uuid,infoUuid:info.uuid},settings.bindings);
 const uid=Array.isArray(settings.administratorUid)?settings.administratorUid[0]:settings.administratorUid;
 authorizeAdministrator(uid,settings.administratorUid);
 const actor=await(await native('models/user')).selectOptionalUserByUid(uid);
 if(!actor||!await db.queryScalar('SELECT EXISTS(SELECT 1 FROM administrators WHERE user_id=$id)',{id:actor.id},z.boolean()))throw new Error('Verified native administrator must exist');
 if(record) {
  const institutions=await native('models/institution');
  const institutionId=await resolveInstitution(catalog,record.institution,{...institutions,withLock:(name,fn)=>namedLocks.doWithLock(name,{timeout:30000},fn)});
  if(course.institution_id!==institutionId)throw new Error('Native course institution mismatch; migration is not supported');
 }
 if(course.path!==path)course=await courses.updateCourseColumn({courseId:id,columnName:'path',value:path,authnUserId:actor.id});
 const logger={info:message=>process.stderr.write(String(message)+'\n'),verbose:()=>{},error:message=>process.stderr.write(String(message)+'\n')};
 const result=await(await native('sync/syncFromDisk')).syncDiskToSql(course,logger);
 if(result.status!=='complete'||result.hadJsonErrors||result.hadJsonErrorsOrWarnings)throw new Error('Native sync reported errors/warnings');
 const instances=await db.queryRows('SELECT id::text,uuid,short_name FROM course_instances WHERE course_id=$id AND deleted_at IS NULL',{id},z.object({id:z.string(),uuid:z.string(),short_name:z.string()}));
 process.stdout.write(JSON.stringify({courseId:id,deliveryHash,path,instances})+'\n');
} finally {await namedLocks.close();await db.closeAsync();}
