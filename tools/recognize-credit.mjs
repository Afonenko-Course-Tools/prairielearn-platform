// Вызывается E только с закрытой принятой картой и native admin authority.
// Функция не читает реальные данные/конфигурацию при импорте модуля.
import {recognizeCredit,recognizedPrivateFilesApi} from '../bridge/recognized-credit-native.mjs';
import {attachRecognizedPrivateFiles,validatePrivateSourceFiles} from './recognized-credit-files.mjs';
/** @param {unknown} input @param {unknown} approval @param {{db?:import("../types/recognized-credit.d.ts").CreditDatabase,fileStore?:Partial<import("../types/recognized-credit.d.ts").FileStore>}} [dependencies] */
export async function recognizeMappedCreditAndFiles(input,approval,{db,fileStore}={}){
 const raw=/** @type {{mapping?:{privateFiles?:unknown}}} */(input);
 const refs=raw.mapping?.privateFiles;
 const api=await recognizedPrivateFilesApi(input,approval,db,fileStore);
 // Фабрика уже проверила закрытую карту через shape.
 const mapping=/** @type {import("../types/recognized-credit.d.ts").RecognitionInput} */(input);
 await validatePrivateSourceFiles({refs,target:mapping.target},api);
 const nativeAdmin=db?{recognizePreviousCredit:/** @param {unknown} i @param {unknown} a */(i,a)=>recognizeCredit(i,a,db)}:/** @type {{recognizePreviousCredit(input:unknown,approval:unknown):Promise<{status:string}>}} */(await import(new URL('../dist/lib/manualGrading.js',import.meta.url).href));
 const grade=await nativeAdmin.recognizePreviousCredit(input,approval);
 if(grade.status==='NEEDS_NATIVE_ADMIN_EVENT')return{...grade,files:'NOT_WRITTEN'};
 const files=await attachRecognizedPrivateFiles({refs,target:mapping.target,actorUserId:mapping.actorUserId},api);
 return{grade,files};
}
