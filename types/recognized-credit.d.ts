import type {z} from 'zod';
export interface SourceOwner extends Record<string, unknown> {database: string; autoJobId: string; submissionId: string; variantId: string; instanceQuestionId: string; assessmentInstanceId: string; questionUUID: string; workUUID: string; uid: string; userId: string}
export interface FileTarget {uid: string; userId: string; assessmentId: string; assessmentInstanceId: string; instanceQuestionId: string}
export interface CreditTarget extends FileTarget, Record<string,unknown> {courseId:string; courseUUID:string; courseInstanceUUID:string; courseInstanceId:string; workId:string; assessmentUUID:string; questionUUID:string; questionId:string; assessmentQuestionId:string}
export interface RecognitionInput {source:SourceOwner; target:CreditTarget; mapping:{kind:string;canonicalExerciseId:string;privateFiles?:unknown[]}; actorUserId:string; checkModifiedAt?:unknown; destinationSubmissionId?:unknown; format?:unknown; explanation?:unknown}
export interface SourceFileOwner {assessmentInstanceId:string; instanceQuestionId:string; userId:string; filename:string}
export interface SubmissionReference extends SourceFileOwner {kind:'submission';submissionId:string;variantId:string;fileIndex:number;answerField:'raw'|'submitted'}
export interface NativeFileReference extends SourceFileOwner {kind:'native-file';fileId:string}
export interface PrivateReference {sourceReference:string;source:SubmissionReference|NativeFileReference;relativeName:string;uid:string;bytes?:unknown}
export interface PrivateFile extends Record<string,unknown> {id:string;user_id:string|null;assessment_id:string|null;assessment_instance_id:string|null;instance_question_id:string|null;type:string;display_filename:string;deleted_at?:unknown;contents?:Buffer}
export interface UploadFile {contents:Buffer;user_id:string;authn_user_id:string;assessment_id:string;assessment_instance_id:string;instance_question_id:string;type:'student_upload';display_filename:string}
export interface FileStore {getFile(id:string):Promise<{file:PrivateFile;contents:Buffer}>;uploadFile(options:UploadFile):Promise<string>}
export interface PrivateContext extends FileTarget {actorUserId:string;recognizedCredit:boolean;allowPersonalNotes:boolean}
export interface PrivateFilesApi extends FileStore {context():Promise<PrivateContext>;readSourceReference(ref:PrivateReference):Promise<Buffer>;findFiles(name:string):Promise<PrivateFile[]>}
export type FileArgs = {refs:unknown;target:FileTarget;actorUserId?:unknown};
export type CreditRow = Record<string,unknown>;
export interface RecomputeArgs {assessment_instance_id:string;authn_user_id:string;credit:number}
export interface CreditDatabase {
  schema: unknown;
  loadSqlEquiv(path:string): Record<string,string>;
  runInTransactionAsync<T>(action:()=>Promise<T>):Promise<T>;
  queryRow(sql:string,params:Record<string,unknown>,schema:unknown):Promise<CreditRow>;
  queryOptionalRow(sql:string,params:Record<string,unknown>,schema:unknown):Promise<CreditRow|null>;
  queryRows(sql:string,params:Record<string,unknown>,schema:unknown):Promise<CreditRow[]>;
  execute(sql:string,params:Record<string,unknown>):Promise<unknown>;
  recompute(args:RecomputeArgs):Promise<unknown>;
}
