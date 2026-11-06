export class BridgeError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}
export function isCanonicalEmail(value) {
  if (typeof value !== 'string' || value.length < 3 || value.length > 254 ||
      value !== value.toLowerCase() || !/^[\x21-\x7e]+$/.test(value)) return false;
  const parts = value.split('@');
  if (parts.length !== 2) return false;
  const [local, domain] = parts;
  if (local.length < 1 || local.length > 64 || local.startsWith('.') || local.endsWith('.') ||
      local.includes('..') || !/^[a-z0-9!#$%&'*+/=?^_`{|}~.\-]+$/.test(local)) return false;
  const labels = domain.split('.');
  return labels.length >= 2 && labels.every(label => label.length >= 1 && label.length <= 63 &&
    /^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/.test(label));
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
      const key = binding.delivery.courseId + '/' + instance;
      if (seen.has(key)) fail('Ambiguous delivery/instance binding');
      seen.add(key);
    }
}

export function assertProductionRuntime(environment, config) {
  if (environment !== 'production' || config.devMode !== false || config.hasShib !== true)
    fail('Gateway bridge requires production, devMode=false and hasShib=true');
}
