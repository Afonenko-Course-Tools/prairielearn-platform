// @ts-check
import {readFile,lstat} from 'node:fs/promises';
import {isAbsolute,resolve} from 'node:path';
import {bridgeDeliverySchema} from '../bridge/delivery.mjs';

/** Чтение выбранного Native пакета до подключения к БД. @param {string} path */
export async function readNativeCoursePayload(path) {
 if(typeof path!=='string'||!isAbsolute(path)||resolve(path)!==path)throw new Error('Absolute normalized native path required');
 /** @param {string} name */
 async function containedFile(name) {
  if(typeof name!=='string'||name.startsWith('/')||/^[A-Za-z]:/.test(name)||/[\x00-\x1f\x7f]/.test(name)||name.includes('\\')||name.split('/').some(s=>['','.','..'].includes(s)))throw new Error('Unsafe native file path');
  let current='';
  for(const part of (path+'/'+name).split('/').filter(Boolean)) {current+='/'+part;if((await lstat(current)).isSymbolicLink())throw new Error('Symlink native path');}
  if(!(await lstat(current)).isFile())throw new Error('Native regular file required');
  return readFile(current);
 }
 const delivery=bridgeDeliverySchema.parse(/** @type {unknown} */(JSON.parse((await containedFile('delivery.json')).toString('utf8'))));
 /** @type {unknown} */
 const info=JSON.parse((await containedFile('infoCourse.json')).toString('utf8'));
 if(delivery.candidate)throw new Error('Candidate payload cannot be used by configured production bootstrap');
 for(const name of delivery.files)await containedFile(name);
 return {delivery,info};
}
