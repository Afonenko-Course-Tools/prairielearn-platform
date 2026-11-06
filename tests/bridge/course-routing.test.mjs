import {test} from 'node:test';
import assert from 'node:assert/strict';
import {validateBindings} from '../../bridge/policy.mjs';
const delivery = {courseId:'demo', instances:{fixture:{works:[]}}};
test('configured course+instance collision fails independently of file bytes',()=>{assert.doesNotThrow(()=>validateBindings([{delivery},{delivery:{...delivery,courseId:'other'}}]));assert.throws(()=>validateBindings([{delivery},{delivery}]));});
