// Вызывается E только с закрытой принятой картой и native admin authority.
// Функция не читает реальные данные/конфигурацию при импорте модуля.
import {recognizeCredit,recognizedPrivateFilesApi} from '../bridge/recognized-credit-native.mjs';
import {attachRecognizedPrivateFiles,validatePrivateSourceFiles} from './recognized-credit-files.mjs';
export async function recognizeMappedCreditAndFiles(input,approval,{sourceRoot,db,fileStore}={}){
 const refs=input.mapping?.privateFiles;
 const api=await recognizedPrivateFilesApi(input,approval,db,fileStore);
 await validatePrivateSourceFiles({sourceRoot,refs,target:input.target},api);
 const nativeAdmin=db?{recognizePreviousCredit:(i,a)=>recognizeCredit(i,a,db)}:await import(new URL('../dist/lib/manualGrading.js',import.meta.url));
 const grade=await nativeAdmin.recognizePreviousCredit(input,approval);
 if(grade.status==='NEEDS_NATIVE_ADMIN_EVENT')return{...grade,files:'NOT_WRITTEN'};
 const files=await attachRecognizedPrivateFiles({sourceRoot,refs,target:input.target,actorUserId:input.actorUserId},api);
 return{status:'NATIVE_CREDIT_AND_PRIVATE_FILE_ADMIN_READBACK_VERIFIED',grade,files,studentDownloadRoute:'NOT_QUALIFIED',nativeRuntimeQualification:'REQUIRED_SEPARATE_ISOLATED_TEST'};
}
