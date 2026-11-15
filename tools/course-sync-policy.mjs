import { resolve } from "node:path";
import { readFile } from "node:fs/promises";
const uuidPattern =
  /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
/** @param {{path: string, sourceCourseId: string, previousSourceCourseId?: unknown, courseUuid: unknown, infoUuid: unknown}} request */
export function authorizeCourseSync({
  path,
  sourceCourseId,
  previousSourceCourseId = sourceCourseId,
  courseUuid,
  infoUuid,
}) {
  if (
    !/^[a-z][a-z0-9-]*$/.test(sourceCourseId) ||
    typeof path !== "string" ||
    !path.startsWith("/course/" + sourceCourseId + "/") ||
    resolve(path) !== path
  )
    throw new Error("Unknown immutable native path");
  if (previousSourceCourseId !== sourceCourseId)
    throw new Error("Cannot replace another source course ID");
  if (
    !uuidPattern.test(/** @type {string} */ (infoUuid)) ||
    (courseUuid !== null && courseUuid !== infoUuid)
  )
    throw new Error("Cannot replace another native course UUID");
  return path;
}
/** @param {unknown} uid @param {import("../types/native-contracts.d.ts").AdministratorApi} native */
export async function verifyNativeAdministrator(uid, native) {
  if (
    typeof uid !== "string" ||
    !uid ||
    uid.trim() !== uid ||
    /[\x00-\x20\x7f]/.test(uid)
  )
    throw new Error("Explicit native administrator UID required");
  const actor = await native.selectOptionalUserByUid(uid);
  if (!actor || actor.uid !== uid || !(await native.isAdministrator(actor.id)))
    throw new Error("Verified native administrator must exist");
  return actor;
}
/** @param {string} path @param {{instances: object, files: string[]}} delivery */
export async function readDeclaredInstances(path, delivery) {
  const instances = [];
  for (const key of Object.keys(delivery.instances)) {
    if (!/^[a-zA-Z0-9_-]+$/.test(key))
      throw new Error("Unsafe native course instance directory");
    const file = `courseInstances/${key}/infoCourseInstance.json`;
    if (!delivery.files.includes(file))
      throw new Error("Declared native instance must be in payload inventory");
    const info = /** @type {{uuid:unknown}} */ (
      /** @type {unknown} */ (
        JSON.parse(await readFile(path + "/" + file, "utf8"))
      )
    );
    const short_name = key;
    if (
      !uuidPattern.test(/** @type {string} */ (info.uuid)) ||
      typeof short_name !== "string" ||
      !short_name.trim()
    )
      throw new Error("Native course instance identity required");
    instances.push({ uuid: /** @type {string} */ (info.uuid), short_name });
  }
  if (
    new Set(instances.map((i) => i.uuid.toLowerCase())).size !==
      instances.length ||
    new Set(instances.map((i) => i.short_name)).size !== instances.length
  )
    throw new Error("Ambiguous declared native instances");
  return instances;
}
/** @template {import("../types/native-contracts.d.ts").NativeInstance} T @param {string} courseId @param {import("../types/native-contracts.d.ts").DeclaredInstance[]} declared @param {T[]} rows @param {boolean} [requireAll] */
export function validateNativeInstances(
  courseId,
  declared,
  rows,
  requireAll = false,
) {
  for (const instance of declared) {
    const matches = rows.filter(
      (row) =>
        row.uuid?.toLowerCase() === instance.uuid.toLowerCase() ||
        (row.course_id === courseId && row.short_name === instance.short_name),
    );
    if (matches.length > 1 || (matches.length === 0 && requireAll))
      throw new Error("Missing or ambiguous native course instance");
    if (
      matches.some(
        (row) =>
          row.course_id !== courseId ||
          row.uuid?.toLowerCase() !== instance.uuid.toLowerCase() ||
          row.short_name !== instance.short_name ||
          row.deleted_at !== null,
      )
    )
      throw new Error("Native course instance identity mismatch");
  }
  return rows;
}
