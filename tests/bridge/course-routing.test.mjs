import {test} from 'node:test';
import assert from 'node:assert/strict';
import {resolveAssignment,assignmentTransition,validateBindings} from '../../bridge/policy.mjs';
const delivery={courseId:'demo',instances:{fixture:{works:['lab']}},questions:['demo/exr-a'],works:[{id:'lab',policy:{assignment:{'student-label':'demo-lab'}},completion:{},slots:[{candidates:['demo/exr-a']}]}]};
const request={version:1,userUid:'student@example.invalid',instance:'fixture',courseKey:'demo',oldWork:null,newWork:'lab'};
test('existing course key routes a native instance without content binding',()=>{assert.deepEqual(resolveAssignment(request,delivery),{oldLabel:null,newLabel:'demo-lab'});assert.throws(()=>resolveAssignment({...request,courseKey:'foreign'},delivery));});
test('assignment transition keeps action version and user identity',()=>{assert.equal(assignmentTransition(request,null),'apply');assert.equal(assignmentTransition(request,request),'duplicate');assert.throws(()=>assignmentTransition({...request,userUid:'foreign@example.invalid'},request));assert.throws(()=>assignmentTransition({...request,version:3},request));});
test('configured course+instance collision fails independently of file bytes',()=>{assert.doesNotThrow(()=>validateBindings([{delivery},{delivery:{...delivery,courseId:'other'}}]));assert.throws(()=>validateBindings([{delivery},{delivery}]));});
