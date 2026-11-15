export class BridgeError extends Error {
  /** @param {number} status @param {string} message */
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}
/** @param {unknown} value @returns {value is string} */
export function isCanonicalEmail(value) {
  if (
    typeof value !== "string" ||
    value.length < 3 ||
    value.length > 254 ||
    value !== value.toLowerCase() ||
    !/^[\x21-\x7e]+$/.test(value)
  )
    return false;
  const parts = value.split("@");
  if (parts.length !== 2) return false;
  const [local, domain] = parts;
  if (
    local.length < 1 ||
    local.length > 64 ||
    local.startsWith(".") ||
    local.endsWith(".") ||
    local.includes("..") ||
    !/^[a-z0-9!#$%&'*+/=?^_`{|}~.\-]+$/.test(local)
  )
    return false;
  const labels = domain.split(".");
  return (
    labels.length >= 2 &&
    labels.every(
      (label) =>
        label.length >= 1 &&
        label.length <= 63 &&
        /^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/.test(label),
    )
  );
}
/** @param {string} message @returns {never} */
const fail = (message) => {
  throw new BridgeError(409, message);
};
/** @param {unknown} value @returns {string | undefined} */
export function canonicalJSONString(value) {
  /** @param {string} left @param {string} right */
  const compare = (left, right) => {
    const a = Array.from(left, (c) => /** @type {number} */ (c.codePointAt(0))),
      b = Array.from(right, (c) => /** @type {number} */ (c.codePointAt(0)));
    for (let i = 0; i < Math.min(a.length, b.length); i++)
      if (a[i] !== b[i]) return a[i] - b[i];
    return a.length - b.length;
  };
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value))
    return "[" + value.map(canonicalJSONString).join(",") + "]";
  // Building the text directly also preserves scalar order for integer-looking keys.
  return (
    "{" +
    Object.keys(value)
      .sort(compare)
      .map(
        (k) =>
          JSON.stringify(k) +
          ":" +
          canonicalJSONString(
            /** @type {Record<string, unknown>} */ (value)[k],
          ),
      )
      .join(",") +
    "}"
  );
}
/** @param {string | undefined} environment @param {{devMode?: unknown, hasShib?: unknown}} config */
export function assertProductionRuntime(environment, config) {
  if (
    environment !== "production" ||
    config.devMode !== false ||
    config.hasShib !== true
  )
    fail("Gateway bridge requires production, devMode=false and hasShib=true");
}
