/** Узкий dev adapter к штатному HTTP loadFromDisk и native server job. */
import {constants} from 'node:fs';
import {open, readFile, rename, unlink} from 'node:fs/promises';
import {randomUUID} from 'node:crypto';
import path from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {setTimeout as sleep} from 'node:timers/promises';

const usage = 'node tools/dev-load-course.mjs --path /course/COURSE/current [--timeout 600] [--job-state /jobs/preview-load-job.json [--resume]]';
/** @typedef {{id: string, short_name: string, uuid: string | null, sync_errors: string | null}} Instance */
/** @typedef {{courseId: string, uuid: string, path: string, jobSequenceId: string, instances: Omit<Instance, 'sync_errors'>[]}} Receipt */
/** @typedef {{schemaVersion: 1, coursePath: string, uuid: string, phase: 'intent' | 'running' | 'terminal', previousCourseId: string | null, previousInstances: Instance[], jobSequenceId?: string, nativeStatus?: 'Success' | 'Error' | 'Stopped', receipt?: Receipt, validationError?: string}} JobState */

/** Открытие без перехода по ссылкам; state принадлежит одному обычному файлу.
 * @param {string} filename @returns {Promise<JobState | null>}
 */
export async function readJobState(filename) {
  let handle;
  try { handle = await open(filename, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK); }
  catch (error) { if (/** @type {NodeJS.ErrnoException} */ (error).code === 'ENOENT') return null; throw error; }
  try {
    const stat = await handle.stat();
    if (!stat.isFile() || stat.nlink !== 1 || stat.size > 1024 * 1024) throw new Error('Job state должен быть обычным отдельным файлом');
    const state = JSON.parse(await handle.readFile('utf8'));
    if (!state || state.schemaVersion !== 1 || typeof state.coursePath !== 'string' || typeof state.uuid !== 'string'
      || !['intent', 'running', 'terminal'].includes(state.phase)
      || !(state.previousCourseId === null || typeof state.previousCourseId === 'string') || !Array.isArray(state.previousInstances)
      || state.previousInstances.some((/** @type {Instance} */ item) => !item || typeof item.id !== 'string' || typeof item.short_name !== 'string'
        || !(item.uuid === null || typeof item.uuid === 'string') || !(item.sync_errors === null || typeof item.sync_errors === 'string'))
      || (state.jobSequenceId !== undefined && (typeof state.jobSequenceId !== 'string' || !/^[1-9][0-9]*$/.test(state.jobSequenceId)))
      || (state.phase !== 'intent' && !state.jobSequenceId)
      || (state.phase === 'terminal' && !['Success', 'Error', 'Stopped'].includes(state.nativeStatus))
      || (state.phase !== 'terminal' && state.nativeStatus !== undefined)) throw new Error('Некорректный durable job state; требуется диагностика оператора');
    return state;
  } finally { await handle.close(); }
}

/** @param {string} filename @param {JobState} state @param {boolean} exclusive */
async function writeJobState(filename, state, exclusive = false) {
  // Exclusive intent не позволяет двум CLI отправить два запроса на один state.
  const target = exclusive ? filename : `${filename}.${randomUUID()}.tmp`;
  const handle = await open(target, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o644);
  try {
    // Контейнер может писать от root; host controller читает публичные job ID
    // из своего закрытого каталога state (0700), без chown и root на host.
    await handle.chmod(0o644);
    await handle.writeFile(`${JSON.stringify(state)}\n`, 'utf8');
    await handle.sync();
  } finally { await handle.close(); }
  if (!exclusive) {
    try {
      if (!await readJobState(filename)) throw new Error('Durable job state исчез; требуется диагностика оператора');
      await rename(target, filename);
    } catch (error) { await unlink(target).catch(() => {}); throw error; }
  }
  const directory = await open(path.dirname(filename), constants.O_RDONLY | constants.O_DIRECTORY);
  try { await directory.sync(); } finally { await directory.close(); }
}

/** Durable узкая граница запуска: intent -> точный ID -> native terminal.
 * Таймаут и потеря ответа не превращаются в terminal и не разрешают новый запрос.
 * @param {{statePath?: string, resume: boolean, coursePath: string, uuid: string, previousCourseId: string | null, previousInstances: Instance[], timeoutMs: number, intervalMs?: number, start: () => Promise<string>, poll: (id: string) => Promise<{status: 'Running' | 'Stopping' | 'Stopped' | 'Success' | 'Error' | null}>, heartbeat?: (id: string, status: string | null) => void}} options
 * @returns {Promise<JobState>}
 */
export async function runNativeLoadJob(options) {
  const {statePath, resume, coursePath, uuid, previousCourseId, previousInstances, start, poll} = options;
  if (resume && !statePath) throw new Error('--resume требует --job-state');
  let state = statePath ? await readJobState(statePath) : null;
  if (state && (state.coursePath !== coursePath || state.uuid !== uuid)) throw new Error('Durable job state не соответствует стабильному пути и UUID курса');
  if (resume) {
    if (!state) throw new Error('Durable job state отсутствует; повторный запуск запрещён, требуется диагностика оператора');
    if (!state.jobSequenceId) throw new Error('Job intent сохранён, но ID неизвестен; повторный запуск запрещён, требуется диагностика оператора');
  } else {
    if (state) throw new Error('Durable job state уже существует; используйте --resume, новый запуск запрещён');
    state = {schemaVersion: 1, coursePath, uuid, phase: 'intent', previousCourseId, previousInstances};
    if (statePath) await writeJobState(statePath, state, true);
    const id = await start();
    if (!/^[1-9][0-9]*$/.test(id)) throw new Error('Некорректный native job ID; повторный запуск запрещён');
    state = {...state, phase: 'running', jobSequenceId: id};
    if (statePath) await writeJobState(statePath, state);
  }
  if (!state?.jobSequenceId) throw new Error('Native job ID неизвестен');
  const id = state.jobSequenceId;
  const deadline = Date.now() + options.timeoutMs;
  let nextHeartbeat = 0;
  while (state.phase !== 'terminal') {
    const {status} = await poll(id);
    if (Date.now() >= nextHeartbeat) {
      options.heartbeat?.(id, status);
      nextHeartbeat = Date.now() + 10000;
    }
    if (status === 'Success' || status === 'Error' || status === 'Stopped') {
      state = {...state, phase: 'terminal', nativeStatus: status};
      if (statePath) await writeJobState(statePath, state);
      break;
    }
    if (Date.now() >= deadline) throw new Error(`Превышено время ожидания native load job ${id}; job не запускается повторно, используйте --resume`);
    await sleep(options.intervalMs ?? 1000);
  }
  if (state.nativeStatus !== 'Success') throw new Error(`Native load job ${id}: ${state.nativeStatus}`);
  return state;
}

async function main() {
  const args = process.argv.slice(2);
  if (args.length === 1 && args[0] === '--help') { console.log(usage); return; }
  /** @type {Record<string, string>} */
  const options = {};
  let resume = false;
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--resume' && !resume) { resume = true; continue; }
    if (!['--path', '--timeout', '--job-state'].includes(args[i]) || !args[i + 1] || Object.hasOwn(options, args[i])) throw new Error(usage);
    options[args[i]] = args[++i];
  }
  const coursePath = options['--path'];
  if (!/^\/course\/[a-z][a-z0-9-]*\/current$/.test(coursePath ?? '')) throw new Error(usage);
  const statePath = options['--job-state'];
  if ((statePath && !path.isAbsolute(statePath)) || (resume && !statePath)) throw new Error(usage);
  const timeout = Number(options['--timeout'] ?? '600');
  if (!Number.isFinite(timeout) || timeout < 1 || timeout > 3600) throw new Error(usage);
  const root = process.env.PL_ROOT ?? '/PrairieLearn';
  /**
   * Узкая используемая проекция PrairieLearn@92584fe426ececb84bc2d09de9975c7056c0c5f6.
   * @typedef {{
   * 'lib/config': {config: import('../types/native-contracts.d.ts').NativeConfig & {courseDirs: string[]}, loadConfig(paths: string[]): Promise<void>},
   * 'models/course': {selectOptionalCourseByPath(path: string): Promise<{id: string, sync_errors: string | null} | null>},
   * 'lib/server-jobs': {selectJobSequenceStatus(id: string): Promise<{status: 'Running' | 'Stopping' | 'Stopped' | 'Success' | 'Error' | null}>}
   * }} DevNativeModules
   */
  /** @template {keyof DevNativeModules} K @param {K} name @returns {Promise<DevNativeModules[K]>} */
  const native = (name) => import(pathToFileURL(`${root}/apps/prairielearn/dist/${name}.js`).href);
  const {config, loadConfig} = await native('lib/config');
  await loadConfig([`${root}/config.json`]);
  // Проверить реальную конфигурацию до DB init и до запуска native job.
  if (config.devMode !== true || config.hasShib !== false) throw new Error('Загрузка preview требует devMode:true и hasShib:false');
  if (!config.courseDirs.includes(coursePath)) throw new Error('Стабильный путь отсутствует в config.courseDirs');
  /** @type {unknown} */
  const info = JSON.parse(await readFile(`${coursePath}/infoCourse.json`, 'utf8'));
  if (!info || typeof info !== 'object' || !('uuid' in info) || typeof info.uuid !== 'string' || !info.uuid) throw new Error('В infoCourse.json отсутствует UUID курса');
  const uuid = info.uuid;
  const db = await import('@prairielearn/postgres');
  const {z} = await import('zod');
  await db.initAsync({user: config.postgresqlUser, database: config.postgresqlDatabase,
    host: config.postgresqlHost, password: config.postgresqlPassword ?? undefined, max: 2}, () => { process.exitCode = 1; });
  /** @type {JobState | undefined} */
  let state;
  try {
    const courses = await native('models/course');
    const previous = await courses.selectOptionalCourseByPath(coursePath);
    const instanceSchema = z.object({id: z.string(), short_name: z.string(), uuid: z.string().nullable(), sync_errors: z.string().nullable()});
    const readInstances = (/** @type {string} */ courseId) => db.queryRows('SELECT id::text, short_name, uuid, sync_errors FROM course_instances WHERE course_id=$courseId AND deleted_at IS NULL ORDER BY id', {courseId}, instanceSchema);
    const previousInstances = previous ? await readInstances(previous.id) : [];
    const jobs = await native('lib/server-jobs');
    state = await runNativeLoadJob({statePath, resume, coursePath, uuid, previousCourseId: previous?.id ?? null, previousInstances, timeoutMs: timeout * 1000,
      start: async () => {
        // Единственный запуск штатного route. Redirect содержит native job ID.
        const response = await fetch('http://127.0.0.1:3000/pl/loadFromDisk', {redirect: 'manual', signal: AbortSignal.timeout(30000)});
        const match = /^\/pl\/jobSequence\/([1-9][0-9]*)\/?$/.exec(response.headers.get('location') ?? '');
        void response.body?.cancel().catch(() => {});
        if (response.status !== 302 || !match) throw new Error('Native dev load не вернул jobSequence; проверьте штатный dev-вход и runtime');
        return match[1];
      }, poll: (id) => jobs.selectJobSequenceStatus(id),
      heartbeat: (id, status) => console.error(`Native load job ${id}: ${status ?? 'ожидание'}`),
    });
    const course = await courses.selectOptionalCourseByPath(coursePath);
    if (!course || (state.previousCourseId && state.previousCourseId !== course.id)) throw new Error('Native load не сохранил идентичность курса по стабильному пути');
    const instances = await readInstances(course.id);
    if (!instances.length) throw new Error('После native load нет действующих course instances');
    if (course.sync_errors || instances.some((instance) => instance.sync_errors)) throw new Error('Native load оставил ошибки синхронизации');
    for (const instance of instances) {
      const before = state.previousInstances.find((candidate) => candidate.uuid === instance.uuid && candidate.short_name === instance.short_name);
      if (before && before.id !== instance.id) throw new Error('Native load изменил ID существующего instance');
    }
    const receipt = {courseId: course.id, uuid, path: coursePath, jobSequenceId: /** @type {string} */ (state.jobSequenceId),
      instances: instances.map(({sync_errors, ...instance}) => instance)};
    if (statePath) {
      const {validationError, ...validatedState} = state;
      await writeJobState(statePath, {...validatedState, receipt});
    }
    console.log(JSON.stringify(receipt));
  } catch (error) {
    if (statePath && state?.nativeStatus === 'Success') await writeJobState(statePath, {...state, validationError: String(error)});
    console.error('Загрузка могла частично изменить native state. Диагностика: durable job state и /pl/jobSequence/<ID>; автоматического повторного запуска нет.');
    throw error;
  } finally { await db.closeAsync(); }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main();
