import type {CreditTarget,SourceOwner,RecognitionInput,UploadFile,PrivateFile,CreditDatabase} from './recognized-credit.d.ts';
import type {Readable,Writable} from 'node:stream';
import type {CoursePermissionArgs,InstancePermissionArgs,EnrollmentArgs,BridgeCourseInstance} from './native-contracts.d.ts';
export interface MutableBinding extends Record<string, unknown> {kind?:string;uuid:string;grading?:{method:string};submission?:Record<string,unknown>;sourceRoot?:string}
export interface MutableDelivery {schemaVersion:number;courseId:string;bookRoot:string;questions:string[];gradingPayloads:Record<string,MutableBinding>;works:{id:string;slots:{id:string;selection:string;candidates:string[];assignment:{requirement:string;workMode:string}}[];policy:object;completion:{schemaVersion:number;mode:string;source:string;slotIds:string[];requiredSlotIds:string[];atLeast:number;fullyCompletedScore:number}}[];instances:Record<string,{works:string[];selfEnrollment:boolean}>;files:string[];candidate?:boolean}
export interface EnrollmentSettings extends Record<string,unknown> {listenHost?:unknown;listenPort?:unknown;tokenFile?:string;bindings?:unknown;administratorEmail?:unknown}
export interface EnrollmentOptions {settings?:EnrollmentSettings;ci?:Record<string,unknown>;courseRole?:string|null;instanceRole?:string|null;environment?:string;config?:Record<string,unknown>;adminGrantFailure?:boolean;nativeError?:boolean;missingUser?:boolean;changedUser?:boolean;permissionFailure?:boolean;prior?:{status:string};unavailable?:boolean;nullContext?:boolean;denied?:boolean}
export interface RequestStream extends Readable {method:string;url:string;headers:{authorization:string}}
export interface TestResponse {writeHead(code:number,headers:Record<string,string>):TestResponse;end(value:string):void}
export type BridgeHandler=(req:RequestStream,res:TestResponse)=>Promise<void>;
export interface BridgeState {migrations:number;enrollmentWrites:EnrollmentArgs[];locks:Record<string,unknown>[];nativeReads:number;bodyReads:number;queries:number;courseGrants:CoursePermissionArgs[];instanceGrants:InstancePermissionArgs[];administrators:Set<string>;courseRole:string|null;instanceRole:string|null;accessChecks:{userId:string;courseRole:string|null;instanceRole:string|null}[];reservationLookups:number;contextModes:string[]}
export interface SendOptions {body?:unknown;method?:string;url?:string;authorization?:string}
export interface BridgeResponse {status:number;headers:Record<string,string>;body:Record<string,unknown>}
export interface CallbackRequest {rawHeaders:string[];get(name:string):string|undefined}
export type CallbackHandler=(req:CallbackRequest,res:object,next:()=>void)=>Promise<unknown>;
export interface GradingResult {error?:Error & {errors?:Error[]};value?:{succeeded:boolean}}
export interface LifecycleExercise {submit():Promise<GradingResult>;events:string[];cleanupResolvers:Array<()=>void>;active:number}
export interface LifecycleResult {result:GradingResult;events:string[];active:number;running:boolean;timers:Map<number,()=>void>;finishCleanup?:()=>void;currentActive:number}
export interface SchemaProxy {():SchemaProxy;[key:string]:SchemaProxy}
export interface HookState {points:number;manual:number;status:unknown;pending:unknown;recognized:boolean;answer:unknown;job:Record<string,unknown>;ai:{id:string;max_points:number;max_bonus_points:number;points:number;score_perc:number};guardCalls:number}
export interface CreditIQ extends CreditTarget {coursePath:string;open:boolean;status:string;points:number;auto_points:number;manual_points:number;score_perc:number;requires_manual_grading:boolean;max_points:number;max_auto_points:number;max_manual_points:number;modified_at:string;allow_personal_notes:boolean}

export interface CreditTestEvent {id:string;record:RecognitionInput;authn_user_id:string}
export interface CreditTestState extends Record<string,unknown> {
 ai:CreditTarget & {coursePath:string;open:boolean;points:number;score_perc:number};
 iq:CreditIQ|null;
 source:SourceOwner & {grading_method:string;graded_at:string;grading_request_canceled_at:null;deleted_at:null;gradable:boolean;submission_broken:boolean;correct:boolean;score:number};
 sourcePrivateSubmissions:Array<SourceOwner & {raw_answer:{_files?:{name:string;contents:string}[]};submitted_answer?:{_files?:{name:string;contents:string}[]}}>;
 sourcePrivateFiles?:Array<SourceOwner & {fileId:string}>;
 events:CreditTestEvent[];logs:{points:number;actor:unknown}[];jobs:Record<string,unknown>[];submissions:unknown[];files:Array<UploadFile & PrivateFile>;calls:string[];administrator:boolean;
}
export interface CreditFixture<M extends boolean=false> {input:RecognitionInput & Record<string,unknown>;approval:RecognitionInput;state:CreditTestState & {iq:M extends true?null:CreditIQ};db:CreditDatabase}
export interface RouteRequest {method:string;params:Record<string,string>;query:object;cookies:object}
export interface RouteResponse extends Writable {locals:Record<string,unknown>;filename?:string;attachment(name:string):void;status(n:number):RouteResponse;send():void}
export type Middleware=(req:RouteRequest,res:RouteResponse)=>unknown;
export type PgNodeKind = import('@pgsql/types').Node extends infer N ? N extends object ? keyof N : never : never;
export type PgNodeData<K extends PgNodeKind> = Extract<import('@pgsql/types').Node,Record<K,unknown>> extends Record<K,infer V> ? V : never;
export interface NativeBinder {bind(sql:string,params:Record<string,unknown>,requireExactly:boolean):{processedSql:string;paramsArray:unknown[]}}
