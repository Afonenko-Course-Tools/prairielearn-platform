// Настоящий Native binder и SQL loader; DB I/O заменяется существующей fixture.
import vm from 'node:vm';import {readFileSync} from 'node:fs';
import {loadSql} from '../fixtures/native-postgres-upstream/loader.js';
const source=readFileSync(new URL('../fixtures/native-postgres-upstream/pool.js',import.meta.url),'utf8');
const start=source.indexOf('function paramsToArray('),end=source.indexOf('\n/**',start);if(start<0||end<0)throw Error('Граница настоящего Native binder изменилась');
const context=vm.createContext({difference:(/** @type {string[]} */a,/** @type {string[]} */b)=>a.filter(k=>!b.includes(k))});new vm.Script(source.slice(start,end)+'\nglobalThis.bind=paramsToArray;').runInContext(context);
const sql=loadSql(new URL('../../bridge/recognized-credit-native.sql',import.meta.url).pathname);
/** @param {import("../../types/recognized-credit.d.ts").CreditDatabase} db */
export function strictNativeSqlFixture(db){
 /** @template {unknown[]} Rest @template T @param {(name:string,params:Record<string,unknown>,...rest:Rest)=>Promise<T>} call */
 const checked=call=>/** @param {string} name @param {Record<string,unknown>} params @param {Rest} rest */async(name,params,...rest)=>{
  if(!Object.hasOwn(sql,name))throw Error('Неизвестный настоящий SQL-блок '+name);
  context.bind(sql[name],params,true);return call(name,params,...rest);
 };
 return {...db,queryRow:checked(db.queryRow.bind(db)),queryOptionalRow:checked(db.queryOptionalRow.bind(db)),queryRows:checked(db.queryRows.bind(db)),execute:checked(db.execute.bind(db))};
}
