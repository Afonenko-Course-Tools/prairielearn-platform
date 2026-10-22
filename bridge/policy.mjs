export class BridgeError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}
export function authorizeAdministrator(requested, configured) {
  const identities = Array.isArray(configured) ? configured : [configured];
  if (!identities.length || identities.some(uid => typeof uid !== 'string' || !/^gw-[a-f0-9]{64}@example\.invalid$/.test(uid)) || !identities.includes(requested))
    throw new BridgeError(403, 'Explicit administrator identity required');
  return requested;
}
const fail = (message) => {
  throw new BridgeError(409, message);
};
export function resolveAssignment(request, delivery) {
  const keys = ['version', 'userUid', 'instance', 'deliveryHash', 'oldWork', 'newWork'];
  if (
    !request ||
    Object.keys(request).length !== keys.length ||
    keys.some((k) => !Object.hasOwn(request, k))
  )
    fail('Invalid assignment fields');
  if (
    !Number.isSafeInteger(request.version) ||
    request.version < 1 ||
    typeof request.userUid !== 'string' ||
    !request.userUid.length ||
    request.userUid.length > 512 ||
    typeof request.instance !== 'string'
  )
    fail('Invalid identity or version');
  if (
    request.deliveryHash !== delivery.deliveryHash ||
    !/^[a-f0-9]{64}$/.test(request.deliveryHash)
  )
    fail('Delivery mismatch');
  const instance = delivery.instances[request.instance];
  if (!instance) fail('Instance not in delivery');
  const resolve = (id) => {
    if (id === null) return null;
    if (typeof id !== 'string' || !instance.works.includes(id)) fail('Work not in instance');
    const work = delivery.works.find((w) => w.id === id);
    const label = work?.policy?.assignment?.['student-label'];
    if (
      !label ||
      !work.completion ||
      work.slots.flatMap(slot=>slot.candidates).some((q) => !delivery.questions.includes(q))
    )
      fail('Work is not bridge ready');
    return label;
  };
  return { oldLabel: resolve(request.oldWork), newLabel: resolve(request.newWork) };
}
export function assignmentTransition(request, prior) {
  if (!prior) {
    if (request.version !== 1 || request.oldWork !== null)
      fail('First assignment must start at version one');
    return 'apply';
  }
  for (const key of ['userUid', 'instance'])
    if (request[key] !== prior[key]) fail('Assignment identity is immutable');
  if (request.version === prior.version) {
    if (['deliveryHash', 'oldWork', 'newWork'].some((k) => request[k] !== prior[k]))
      fail('Version conflict');
    return 'duplicate';
  }
  if (request.version !== prior.version + 1 || request.oldWork !== prior.newWork)
    fail('Stale assignment transition');
  // Cross-delivery replacement needs an explicit migration of its old ACL binding.
  if (request.deliveryHash !== prior.deliveryHash) fail('Delivery migration required');
  return 'apply';
}
export function validateNativeGroups(work, groups) {
  const expected=work.slots.reduce((n,slot)=>n+(slot.selection==='choice'?slot.candidates.length:1),0);
  if(!Array.isArray(groups)||groups.length!==expected||new Set(groups.map(g=>g.group_id)).size!==groups.length)fail('Native group inventory differs from delivery');
  const mapping=new Map(),used=new Set();
  for(const slot of work.slots){
    if(slot.selection==='choice'){
      const matches=groups.filter(g=>g.question_ids.length===1&&slot.candidates.includes(g.question_ids[0]));
      if(matches.length!==slot.candidates.length||new Set(matches.map(g=>g.question_ids[0])).size!==slot.candidates.length||new Set(matches.map(g=>g.zone_id)).size!==1)fail('Choice requires all candidates in one native zone');
      const zone=matches[0].zone_id;
      if(typeof zone!=='string'||groups.filter(g=>g.zone_id===zone).length!==matches.length||matches.some(g=>g.zone_best_questions!==1||g.zone_number_choose!==null||![null,1].includes(g.number_choose)||used.has(g.group_id)))fail('Choice requires a dedicated bestQuestions one zone without random selection');
      matches.forEach(g=>used.add(g.group_id));mapping.set(slot.id,{choice:true,zoneId:zone,groups:matches});
    }else{
      if(!['fixed','random'].includes(slot.selection))fail('Unsupported slot selection');
      const matches=groups.filter(g=>canonicalJSONString([...g.question_ids].sort())===canonicalJSONString([...slot.candidates].sort()));
      if(matches.length!==1||matches[0].number_choose!==1&&!(slot.selection==='fixed'&&matches[0].number_choose===null)||used.has(matches[0].group_id))fail('Native group candidate set or selection differs from delivery');
      if(matches[0].zone_number_choose!==null||matches[0].zone_best_questions!==null)fail('Regular slots cannot hide zone subset/best selection');
      used.add(matches[0].group_id);mapping.set(slot.id,matches[0].group_id);
    }
  }
  if(used.size!==groups.length)fail('Unbound native group');
  return mapping;
}
function nativeCandidate(row,attempt){
  if(![null,'complete','unanswered','saved','correct','incorrect','grading','invalid'].includes(row.native_status))fail('Invalid native candidate status');
  if(row.attempt_id!==attempt.id||row.attempt_number!==attempt.number||typeof row.requires_manual_grading!=='boolean')fail('Native candidate attempt/manual status missing or different');
  const status=row.requires_manual_grading?'grading':['complete','correct','incorrect'].includes(row.native_status)?'complete':row.native_status==='grading'?'grading':'unanswered';
  if(row.score!==null&&(!Number.isFinite(row.score)||row.score<0||row.score>1))fail('Invalid candidate score');
  for(const field of ['points','max_points'])if(row[field]!==null&&(!Number.isFinite(row[field])||row[field]<0))fail('Invalid candidate points');
  if(row.points!==null&&row.max_points!==null&&row.points>row.max_points)fail('Candidate points exceed ceiling');
  if(status==='complete'&&row.score===1&&(row.max_points===null||row.max_points<=0||row.points!==row.max_points))fail('Incomplete full candidate result');
  return {qualifiedId:row.qualified_id,score:row.score,points:row.points,maxPoints:row.max_points,status};
}
export function assignedSlots(work, rows, attempt, groups) {
  const mapping=validateNativeGroups(work,groups);
  if(!attempt){if(rows.length)fail('Selection without native attempt');return []}
  const expected=work.slots.reduce((n,s)=>n+(s.selection==='choice'?s.candidates.length:1),0);
  if(rows.length!==expected)fail('Exact assigned candidate inventory required');
  const result=[],seen=new Set();
  for(const slot of work.slots){
    const binding=mapping.get(slot.id);
    if(slot.selection==='choice'){
      const candidateRows=binding.groups.map(group=>{
        const matching=rows.filter(row=>row.group_id===group.group_id);
        if(matching.length!==1||matching[0].qualified_id!==group.question_ids[0]||seen.has(matching[0].qualified_id))fail('Missing, duplicate or foreign choice candidate');
        seen.add(matching[0].qualified_id);return nativeCandidate(matching[0],attempt);
      });
      if(new Set(candidateRows.map(r=>r.maxPoints)).size!==1||candidateRows[0].maxPoints===null||candidateRows[0].maxPoints<=0)fail('Choice candidate weights differ');
      const full=r=>r.status==='complete'&&r.score===1;
      const ranked=[...candidateRows].sort((a,b)=>Number(full(b))-Number(full(a))||(b.score??-1)-(a.score??-1)||(a.qualifiedId<b.qualifiedId?-1:a.qualifiedId>b.qualifiedId?1:0));
      const best={...ranked[0]};
      result.push({slotId:slot.id,...best});
    }else{
      const selected=rows.filter(row=>row.group_id===binding);
      if(selected.length!==1||!slot.candidates.includes(selected[0].qualified_id)||seen.has(selected[0].qualified_id))fail('Missing or multiple native selections');
      seen.add(selected[0].qualified_id);result.push({slotId:slot.id,...nativeCandidate(selected[0],attempt)});
    }
  }
  return result;
}
export function completion(work, rows) {
  const c=work.completion,seen=new Set();let count=0;
  if(rows.length && rows.length!==c.slotIds.length)fail('Incomplete assigned slot inventory');
  for(const row of rows){
    const slot=work.slots.find(slot=>slot.id===row.slotId);
    if(!slot||seen.has(row.slotId)||!slot.candidates.includes(row.qualifiedId)||!['complete','grading','unanswered'].includes(row.status))fail('Unscoped or duplicate slot result');
    seen.add(row.slotId);
    if(row.score!==null&&(!Number.isFinite(row.score)||row.score<0||row.score>1))fail('Invalid result score');
    for(const field of ['points','maxPoints'])if(row[field]!==null&&(!Number.isFinite(row[field])||row[field]<0))fail('Invalid native points');
    if(row.points!==null&&row.maxPoints!==null&&row.points>row.maxPoints)fail('Native points exceed ceiling');
    if(row.status==='complete'&&row.score===1&&(row.points===null||row.maxPoints===null||row.maxPoints<=0||row.points!==row.maxPoints))fail('Incomplete full native result');
    if(c.requiredSlotIds.includes(row.slotId)&&row.score===c.fullyCompletedScore&&row.status==='complete')count++;
  }
  return {completedRequired:count,requiredCount:c.requiredSlotIds.length,atLeast:c.atLeast,passed:count>=c.atLeast};
}

export function canonicalJSONString(value) {
  const compare = (left, right) => {
    const a = Array.from(left, (c) => c.codePointAt(0)),
      b = Array.from(right, (c) => c.codePointAt(0));
    for (let i = 0; i < Math.min(a.length, b.length); i++) if (a[i] !== b[i]) return a[i] - b[i];
    return a.length - b.length;
  };
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return '[' + value.map(canonicalJSONString).join(',') + ']';
  // Building the text directly also preserves scalar order for integer-looking keys.
  return (
    '{' +
    Object.keys(value)
      .sort(compare)
      .map((k) => JSON.stringify(k) + ':' + canonicalJSONString(value[k]))
      .join(',') +
    '}'
  );
}
export function validateBindings(bindings) {
  const seen = new Set();
  for (const binding of bindings)
    for (const instance of Object.keys(binding.delivery.instances)) {
      const key = binding.delivery.deliveryHash + '/' + instance;
      if (seen.has(key)) fail('Ambiguous delivery/instance binding');
      seen.add(key);
    }
}

export function assertProductionRuntime(environment, config) {
  if (environment !== 'production' || config.devMode !== false || config.hasShib !== true)
    fail('Gateway bridge requires production, devMode=false and hasShib=true');
}
