import assert from 'node:assert/strict';
import {mkdtemp, mkdir, writeFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import test from 'node:test';

test('dev loader rejects production configuration before any DB package import or mutation', async () => {
  const root = await mkdtemp(path.join(tmpdir(), 'pl-dev-guard-'));
  try {
    const directory = path.join(root, 'apps/prairielearn/dist/lib');
    await mkdir(directory, {recursive: true});
    await writeFile(path.join(root, 'package.json'), '{"type":"module"}');
    await writeFile(path.join(directory, 'config.js'), 'export const config={devMode:false,hasShib:true}; export async function loadConfig() {}');
    const result = spawnSync(process.execPath, [fileURLToPath(new URL('../tools/dev-load-course.mjs', import.meta.url)), '--path', '/course/fixture/current'],
      {env: {...process.env, PL_ROOT: root}, encoding: 'utf8'});
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /devMode:true/);
    assert.doesNotMatch(result.stderr, /ERR_MODULE_NOT_FOUND|ENOENT/);
    assert.equal(result.stdout, '');
  } finally {
    await rm(root, {recursive: true, force: true});
  }
});

test('dev loader rejects a versioned release path instead of silently changing native identity', () => {
  const result = spawnSync(process.execPath, [fileURLToPath(new URL('../tools/dev-load-course.mjs', import.meta.url)), '--path', '/course/java/releases/fresh-native'], {encoding: 'utf8'});
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /\/course\/COURSE\/current/);
});
