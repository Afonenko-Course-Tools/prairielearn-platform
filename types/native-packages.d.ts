/** Используемая проекция первичного API PrairieLearn/PrairieLearn@92584fe426ececb84bc2d09de9975c7056c0c5f6.
 * packages/postgres/src/{index,default-pool,pool,loader}.ts; packages/named-locks/src/index.ts.
 * Schema → z.infer сохраняется, сырые значения/параметры остаются unknown.
 */
declare module '@prairielearn/postgres' {
  import type {z} from 'zod';
  export interface PoolConfig {user?:string;database?:string;host?:string;password?:string;max?:number}
  export type QueryParams = Record<string,unknown> | unknown[];
  export function initAsync(config:PoolConfig,idleErrorHandler:(error:Error,client:unknown)=>void):Promise<void>;
  export function closeAsync():Promise<void>;
  export function setRandomSearchSchemaAsync(prefix:string):Promise<string>;
  export function loadSqlEquiv(filePathOrUrl:string):Record<string,string>;
  export function runInTransactionAsync<T>(action:(client:unknown)=>Promise<T>):Promise<T>;
  export function execute(sql:string,params?:QueryParams):Promise<number>;
  export function queryRows<Model extends z.core.$ZodType>(sql:string,model:Model):Promise<z.infer<Model>[]>;
  export function queryRows<Model extends z.core.$ZodType>(sql:string,params:QueryParams,model:Model):Promise<z.infer<Model>[]>;
  export function queryRow<Model extends z.core.$ZodType>(sql:string,model:Model):Promise<z.infer<Model>>;
  export function queryRow<Model extends z.core.$ZodType>(sql:string,params:QueryParams,model:Model):Promise<z.infer<Model>>;
  export function queryOptionalRow<Model extends z.core.$ZodType>(sql:string,model:Model):Promise<z.infer<Model>|null>;
  export function queryOptionalRow<Model extends z.core.$ZodType>(sql:string,params:QueryParams,model:Model):Promise<z.infer<Model>|null>;
  export function queryScalar<Model extends z.core.$ZodType>(sql:string,model:Model):Promise<z.infer<Model>>;
  export function queryScalar<Model extends z.core.$ZodType>(sql:string,params:QueryParams,model:Model):Promise<z.infer<Model>>;
}
declare module '@prairielearn/named-locks' {
  import type {PoolConfig} from '@prairielearn/postgres';
  export function init(config:PoolConfig,idleErrorHandler:(error:Error,client:unknown)=>void,namedLocksConfig?:{renewIntervalMs?:number}):Promise<void>;
  export function close():Promise<void>;
  export function doWithLock<T,U=never>(name:string,options:{timeout?:number;autoRenew?:boolean;onNotAcquired?:()=>Promise<U>|U},action:()=>Promise<T>):Promise<T|U>;
}
