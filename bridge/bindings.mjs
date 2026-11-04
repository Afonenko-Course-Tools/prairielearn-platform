import {readNativeCoursePayload} from '../tools/native-course-payload.mjs';
import {validateBindings} from './policy.mjs';
// Одна проверка функциональных Native bindings для Bridge и администратора.
export async function loadVerifiedBindings(settings){
 const bindings=[];
 for(const binding of settings){
  const {delivery}=await readNativeCoursePayload(binding.deliveryPath);
  bindings.push({...binding,delivery});
 }
 validateBindings(bindings);return bindings;
}
