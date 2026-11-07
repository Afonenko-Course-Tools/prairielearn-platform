/** Узкие используемые контракты Native Community; PrairieLearn/PrairieLearn@92584fe426ececb84bc2d09de9975c7056c0c5f6, apps/prairielearn/src/{models,lib,sync}. Первичный источник: https://github.com/PrairieLearn/PrairieLearn/tree/92584fe426ececb84bc2d09de9975c7056c0c5f6/apps/prairielearn/src. */
export interface InstitutionDescriptor {shortName: string; longName: string; displayTimezone: string; uidRegexp: string | null}
export interface RegistryCourse {id: string; institution: string; repository: string; commit: string; mount: string}
export interface Institution {id: string; short_name: string; long_name: string; display_timezone: string; uid_regexp: string | null}
export interface NativeUser {id: string; uid: string}
export interface NativeCourse {id: string; institution_id: string; path: string; authn_user_id?: string; repository?: string | null}
export interface CourseInsert {institution_id: string; short_name: string; title: string; display_timezone: string; path: string; repository: null; branch: string; authn_user_id: string}
export interface NativeInstitutionApi {
  selectAllInstitutions(): Promise<Institution[]>;
  insertInstitution(descriptor: InstitutionDescriptor): Promise<string>;
}
export interface NativeCourseApi {
  selectOptionalCourseByPath(path: string): Promise<NativeCourse | null>;
  selectCourseById(id: string): Promise<NativeCourse>;
  insertCourse(course: CourseInsert): Promise<NativeCourse>;
  updateCourseColumn(args: {courseId: string; columnName: 'path'; value: string; authnUserId: string}): Promise<NativeCourse>;
}
export interface NativeLockApi {withLock<T>(name: string, action: () => Promise<T>): Promise<T>}
export interface AdministratorApi {selectOptionalUserByUid(uid: string): Promise<NativeUser | null>; isAdministrator(id: string): Promise<boolean>}
export interface DeclaredInstance {uuid: string; short_name: string}
export interface NativeInstance {id: string; course_id: string; uuid: string | null; short_name: string; deleted_at: unknown}
export interface NativeConfig {devMode: boolean; hasShib: boolean; postgresqlUser: string; postgresqlDatabase: string; postgresqlHost: string; postgresqlPassword: string | null}
export interface NativeSystemAuthz {authn_user:{id:null};user:{id:null}}
export interface EnrollmentArgs {userId: string; courseInstance: BridgeCourseInstance; authzData: NativeSystemAuthz; requiredRole: 'System'[]; actionDetail?: 'implicit_joined'}
export interface BridgeCourseInstance extends NativeInstance {modern_publishing: boolean}
export interface CoursePermissionArgs {course_id: string; uid: string; course_role: 'Editor'; authn_user_id: string}
export interface InstancePermissionArgs {course_id: string; course_instance_id: string; user_id: string; course_instance_role: 'Student Data Editor'; authn_user_id: string}
export interface NativeModules {
  'lib/config': {config: NativeConfig; loadConfig(paths: string[]): Promise<void>};
  'models/institution': NativeInstitutionApi;
  'models/course': NativeCourseApi;
  'models/user': {selectOptionalUserByUid(uid: string): Promise<NativeUser | null>};
  'models/course-instances': {selectCourseInstanceById(id: string): Promise<BridgeCourseInstance>};
  'models/enrollment': {selectOptionalEnrollmentByUserId(args: EnrollmentArgs): Promise<{status: string} | null>; ensureUncheckedEnrollment(args: EnrollmentArgs & {actionDetail:'implicit_joined'}): Promise<{id: string; status: string} | null>};
  'lib/authz-data-lib': {dangerousFullSystemAuthz(): NativeSystemAuthz};
  'lib/authz-data': {constructCourseOrInstanceContext(args: {user: NativeUser; course_id: string; course_instance_id: string; ip: null; req_date: Date; is_administrator: false; overrides: {mode: 'Public'}}): Promise<{authzData: {has_course_permission_preview: boolean; has_course_instance_permission_view?: boolean; has_student_access_with_enrollment?: boolean} | null}>};
  'models/course-permissions': {
    insertCoursePermissionsByUserUid(args: CoursePermissionArgs): Promise<NativeUser>;
    insertCourseInstancePermissions(args: InstancePermissionArgs): Promise<void>;
    selectCoursePermissionForUser(args: {course_id: string; user_id: string}): Promise<string|null>;
    selectCourseInstancePermissionForUser(args: {course_instance_id: string; user_id: string}): Promise<string|null>;
  };
  'sprocs/index': {init(): Promise<void>};
  'sync/syncFromDisk': {syncDiskToSql(course: NativeCourse, logger: {info(message: unknown): void; verbose(): void; error(message: unknown): void}): Promise<{status:'sharing_error'}|{status:'complete';hadJsonErrors:boolean;hadJsonErrorsOrWarnings:boolean}>};
}
