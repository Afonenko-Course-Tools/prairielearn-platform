/** Локальный production bootstrap новой immutable поставки; ключи не создаёт. */
import {readFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import {bootstrapNativeCourse,selectRegistryCourse} from './institution-bootstrap.mjs';
import {authorizeAdministrator,assertProductionRuntime} from '../bridge/policy.mjs';
import {authorizeCourseSync} from './course-sync-policy.mjs';
import {readNativeCoursePayload} from './native-course-payload.mjs';

const usage='Use --registry PATH --course-key KEY --path /course/KEY/DELIVERY_HASH [--institutions PATH]';
const args=process.argv.slice(2);
if(args.length===1&&args[0]==='--help'){console.log(usage);process.exit(0);}
const options={};
for(let i=0;i<args.length;i+=2) {
 if(!['--registry','--course-key','--path','--institutions'].includes(args[i])||!args[i+1]||Object.hasOwn(options,args[i]))throw new Error(usage);
 options[args[i]]=args[i+1];
}
if(!options['--registry']||!options['--course-key']||!options['--path'])throw new Error(usage);
const catalog=JSON.parse(await readFile(options['--institutions']??new URL('../config/institutions.json',import.meta.url),'utf8'));
const registry=JSON.parse(await readFile(options['--registry'],'utf8'));
const courseKey=options['--course-key'],path=options['--path'];
selectRegistryCourse(registry,courseKey,catalog);
if(!new RegExp('^/course/'+courseKey+'/[a-f0-9]{64}$').test(path))throw new Error('Unknown immutable native path');
// Validate the actual immutable payload before any DB connection or mutation.
const {delivery,info}=await readNativeCoursePayload(path);
const {deliveryHash}=delivery;
const settings=JSON.parse(await readFile(process.env.PL_GATEWAY_CONFIG,'utf8'));
authorizeCourseSync({path,deliveryHash,courseUuid:null,infoUuid:info.uuid},settings.bindings);
const {bridgeDeliverySchema}=await import('../bridge/delivery.mjs');bridgeDeliverySchema.parse(delivery);
const db=await import('@prairielearn/postgres');
const namedLocks=await import('@prairielearn/named-locks');
const {z}=await import('zod');
const root=process.env.PL_ROOT??'/PrairieLearn';
const native=(name)=>import(pathToFileURL(`${root}/apps/prairielearn/dist/${name}.js`).href);
const {config,loadConfig}=await native('lib/config');await loadConfig([root+'/config.json']);
assertProductionRuntime(process.env.NODE_ENV,config);
const pg={user:config.postgresqlUser,database:config.postgresqlDatabase,host:config.postgresqlHost,password:config.postgresqlPassword??undefined,max:4};
await db.initAsync(pg,()=>{process.exitCode=1;});
try {
 await namedLocks.init(pg,()=>{process.exitCode=1;});
 await db.setRandomSearchSchemaAsync('local-course-bootstrap');await(await native('sprocs/index')).init();
 const uid=Array.isArray(settings.administratorUid)?settings.administratorUid[0]:settings.administratorUid;
 authorizeAdministrator(uid,settings.administratorUid);
 const actor=await(await native('models/user')).selectOptionalUserByUid(uid);
 if(!actor||!await db.queryScalar('SELECT EXISTS(SELECT 1 FROM administrators WHERE user_id=$id)',{id:actor.id},z.boolean()))throw new Error('Verified native administrator must exist');
 const institutions=await native('models/institution'),courses=await native('models/course');
 const adapter={...institutions,...courses,withLock:(name,fn)=>namedLocks.doWithLock(name,{timeout:30000},fn)};
 const course=await bootstrapNativeCourse({registry,catalog,courseKey,path,info,actorId:actor.id},adapter);
 process.stdout.write(JSON.stringify({courseKey,courseId:course.id,institutionKey:registry.courses.find(c=>c.id===courseKey).institution,institutionId:course.institution_id,path,deliveryHash,syncRequired:true})+'\n');
} finally {await namedLocks.close();await db.closeAsync();}
