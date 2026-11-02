// Настоящий Native binder и SQL loader; DB I/O заменяется существующей fixture.
import vm from 'node:vm';import {readFileSync} from 'node:fs';
import {loadSql} from '../fixtures/native-postgres-upstream/loader.js';
const source=readFileSync(new URL('../fixtures/native-postgres-upstream/pool.js',import.meta.url),'utf8');
const start=source.indexOf('function paramsToArray('),end=source.indexOf('\n/**',start);if(start<0||end<0)throw Error('Граница настоящего Native binder изменилась');
const context=vm.createContext({difference:(a,b)=>a.filter(k=>!b.includes(k))});new vm.Script(source.slice(start,end)+'\nglobalThis.bind=paramsToArray;').runInContext(context);
const sql=loadSql(new URL('../../bridge/recognized-credit-native.sql',import.meta.url).pathname);
export function strictNativeSqlFixture(db){
 const result={...db};for(const method of ['queryRow','queryOptionalRow','queryRows','execute'])result[method]=async(name,params,...rest)=>{
  if(!Object.hasOwn(sql,name))throw Error('Неизвестный настоящий SQL-блок '+name);
  context.bind(sql[name],params,true);return db[method](name,params,...rest);
 };return result;
}
