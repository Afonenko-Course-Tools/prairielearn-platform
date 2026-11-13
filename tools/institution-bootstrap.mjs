/** Общий deployment descriptor; numeric ID разрешается только native model. */
const keyPattern = /^[a-z][a-z0-9-]*$/;
/** @param {unknown} value @param {string[]} fields @returns {value is Record<string, unknown>} */
const closed = (value, fields) =>
  value !== null &&
  typeof value === "object" &&
  !Array.isArray(value) &&
  Object.keys(value).sort().join(",") === [...fields].sort().join(",");
/** @param {unknown} catalog @returns {Record<string, import("../types/native-contracts.d.ts").InstitutionDescriptor>} */
export function validateInstitutionCatalog(catalog) {
  if (
    !closed(catalog, ["schema", "institutions"]) ||
    catalog.schema !== "pl-institutions-v1" ||
    !catalog.institutions ||
    Array.isArray(catalog.institutions) ||
    typeof catalog.institutions !== "object" ||
    !Object.keys(catalog.institutions).length
  )
    throw new Error("Expected pl-institutions-v1 catalog");
  const names = new Set();
  for (const [key, d] of Object.entries(catalog.institutions)) {
    if (
      !keyPattern.test(key) ||
      !closed(d, ["shortName", "longName", "displayTimezone", "uidRegexp"])
    )
      throw new Error("Closed institution descriptor required");
    for (const field of ["shortName", "longName", "displayTimezone"]) {
      const value = d[field];
      if (typeof value !== "string" || !value || value.trim() !== value)
        throw new Error("Explicit institution name/timezone required");
    }
    new Intl.DateTimeFormat("en", {
      timeZone: /** @type {string} */ (d.displayTimezone),
    });
    if (names.has(d.shortName))
      throw new Error("Duplicate native institution shortName");
    names.add(d.shortName);
    if (d.uidRegexp !== null) {
      if (
        typeof d.uidRegexp !== "string" ||
        !d.uidRegexp.startsWith("@") ||
        !d.uidRegexp.endsWith("$") ||
        /(^|[^\\])(?:\\\\)*\./u.test(d.uidRegexp)
      )
        throw new Error("Invalid native UID regexp");
      new RegExp(d.uidRegexp, "u");
    }
  }
  return /** @type {Record<string, import("../types/native-contracts.d.ts").InstitutionDescriptor>} */ (
    catalog.institutions
  );
}
/** @param {unknown} registry @param {unknown} courseKey @param {unknown} catalog */
export function selectRegistryCourse(registry, courseKey, catalog) {
  const descriptors = validateInstitutionCatalog(catalog);
  if (
    !closed(registry, ["schema", "courses"]) ||
    registry.schema !== "pl-courses-v2" ||
    !Array.isArray(registry.courses) ||
    !registry.courses.length
  )
    throw new Error("Bootstrap requires pl-courses-v2 registry");
  const ids = new Set(),
    mounts = new Set();
  /** @type {import("../types/native-contracts.d.ts").RegistryCourse[]} */
  const courses = [];
  for (const value of /** @type {unknown[]} */ (registry.courses)) {
    if (
      !closed(value, ["id", "institution", "repository", "commit", "mount"]) ||
      typeof value.id !== "string" ||
      typeof value.institution !== "string" ||
      typeof value.repository !== "string" ||
      typeof value.commit !== "string" ||
      typeof value.mount !== "string"
    )
      throw new Error("Invalid exact native course pin");
    const course = {
      id: value.id,
      institution: value.institution,
      repository: value.repository,
      commit: value.commit,
      mount: value.mount,
    };
    if (
      !closed(course, ["id", "institution", "repository", "commit", "mount"]) ||
      !Object.values(course).every((v) => typeof v === "string") ||
      !keyPattern.test(course.id) ||
      ids.has(course.id) ||
      !/^\/course(?:[2-9]|[1-9][0-9]+)?$/.test(course.mount) ||
      mounts.has(course.mount) ||
      !/^[a-f0-9]{40}$/.test(course.commit)
    )
      throw new Error("Invalid exact native course pin");
    const url = new URL(course.repository);
    if (
      url.protocol !== "https:" ||
      url.username ||
      url.password ||
      url.search ||
      url.hash ||
      !url.pathname.slice(1) ||
      /[\s\\%]/.test(course.repository) ||
      course.repository.split("/").includes("..")
    )
      throw new Error("Credential-free HTTPS repository required");
    if (!Object.hasOwn(descriptors, course.institution))
      throw new Error("Unknown institution key");
    ids.add(course.id);
    mounts.add(course.mount);
    courses.push(course);
  }
  const course = courses.find((c) => c.id === courseKey);
  if (!course) throw new Error("Unknown registry course");
  return course;
}
/** @param {unknown} catalog @param {string} key @param {import("../types/native-contracts.d.ts").NativeInstitutionApi & import("../types/native-contracts.d.ts").NativeLockApi} native */
export async function resolveInstitution(catalog, key, native) {
  const descriptors = validateInstitutionCatalog(catalog);
  if (!Object.hasOwn(descriptors, key))
    throw new Error("Unknown institution key");
  const d = descriptors[key];
  return native.withLock("deployment-institution:" + d.shortName, async () => {
    const rows = (await native.selectAllInstitutions()).filter(
      (i) => i.short_name === d.shortName,
    );
    if (rows.length > 1) throw new Error("Ambiguous native institution");
    if (rows.length) {
      const row = rows[0];
      if (
        row.long_name !== d.longName ||
        row.display_timezone !== d.displayTimezone ||
        row.uid_regexp !== d.uidRegexp
      )
        throw new Error(
          "Native institution descriptor differs; explicit operator action required",
        );
      return row.id;
    }
    return await native.insertInstitution({ ...d });
  });
}
/** @param {{registry: unknown, catalog: unknown, courseKey: unknown, path: unknown, info: unknown, actorId: unknown}} request @param {import("../types/native-contracts.d.ts").NativeInstitutionApi & Pick<import("../types/native-contracts.d.ts").NativeCourseApi, "selectOptionalCourseByPath" | "insertCourse"> & import("../types/native-contracts.d.ts").NativeLockApi} native */
export async function bootstrapNativeCourse(
  { registry, catalog, courseKey, path, info, actorId },
  native,
) {
  const record = selectRegistryCourse(registry, courseKey, catalog);
  if (typeof actorId !== "string" || !/^[1-9][0-9]*$/.test(actorId))
    throw new Error("Verified native administrator required");
  if (
    typeof path !== "string" ||
    !path.startsWith("/course/" + record.id + "/") ||
    path.split("/").some((p) => p === ".." || p === ".")
  )
    throw new Error("Unknown immutable native path");
  const metadata = /** @type {Record<string, unknown> | null} */ (info);
  if (
    !metadata ||
    ["name", "title", "timezone"].some(
      (k) => typeof metadata[k] !== "string" || !metadata[k].trim(),
    ) ||
    /** @type {string} */ (metadata.title).length > 75
  )
    throw new Error("Native course metadata required");
  const courseInfo = /** @type {{name:string,title:string,timezone:string}} */ (
    metadata
  );
  new Intl.DateTimeFormat("en", { timeZone: courseInfo.timezone });
  const institutionId = await resolveInstitution(
    catalog,
    record.institution,
    native,
  );
  return native.withLock("deployment-course:" + path, async () => {
    const existing = await native.selectOptionalCourseByPath(path);
    if (existing) {
      if (existing.institution_id !== institutionId)
        throw new Error(
          "Native course institution mismatch; migration is not supported",
        );
      return existing;
    }
    // Readonly immutable snapshots have no native repository-sync operation.
    // Native insertCourse records the authenticated actor in its audit trail.
    return await native.insertCourse({
      institution_id: institutionId,
      short_name: courseInfo.name,
      title: courseInfo.title,
      display_timezone: courseInfo.timezone,
      path,
      repository: null,
      branch: "master",
      authn_user_id: actorId,
    });
  });
}
