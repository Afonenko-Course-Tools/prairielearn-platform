import { pathToFileURL } from 'node:url';
import { assertProductionRuntime } from './policy.mjs';

const root = process.env.PL_ROOT ?? '/PrairieLearn';
const { config, loadConfig } = await import(
  pathToFileURL(`${root}/apps/prairielearn/dist/lib/config.js`).href
);
await loadConfig([`${root}/config.json`]);
assertProductionRuntime(process.env.NODE_ENV, config);
console.log('Community gateway native configuration preflight passed');
