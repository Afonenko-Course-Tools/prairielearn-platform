// Настоящий pinned callback с изолированными Router/loadUser dependencies.
// Это handler unit test, а не native DB, numeric user_id или Moodle UI proof.
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import vm from "node:vm";
import { stripTypeScriptTypes } from "node:module";
const path = process.argv[2];
if (!path) throw Error("Callback input required");
let code = await fs.readFile(path, "utf8");
if (path.endsWith(".ts")) code = stripTypeScriptTypes(code);
/** @type {import("../../types/test-contracts.d.ts").CallbackHandler | undefined} */
let handler;
/** @type {Array<{params:{name:string,uid:string,uin:null,provider:string},options:{redirect:boolean}}>} */
let calls = [];
let hasShib = true;
const config = {
  get hasShib() {
    return hasShib;
  },
};
class HttpStatusError extends Error {
  /** @param {number} status @param {string} message */
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}
const context = vm.createContext({ Buffer, TextDecoder });
/** @type {Record<string,Record<string,unknown>>} */
const dependencies = {
  express: {
    Router: () => ({
      get(
        /** @type {string} */ route,
        /** @type {import("../../types/test-contracts.d.ts").CallbackHandler} */ fn,
      ) {
        assert.equal(route, "/");
        handler = fn;
      },
    }),
  },
  "express-async-handler": {
    default: /** @template T @param {T} fn */ (fn) => fn,
  },
  "@prairielearn/error": { HttpStatusError },
  "../../lib/authn.js": {
    loadUser: async (
      /** @type {unknown} */ req,
      /** @type {unknown} */ res,
      /** @type {{name:string,uid:string,uin:null,provider:string}} */ params,
      /** @type {{redirect:boolean}} */ options,
    ) => {
      calls.push({ params, options });
    },
  },
  "../../lib/config.js": { config },
};
const module = new vm.SourceTextModule(code, { context, identifier: path });
await module.link(async (id) => {
  const values = dependencies[id];
  assert.ok(values, "Unexpected dependency " + id);
  return new vm.SyntheticModule(
    Object.keys(values),
    function () {
      for (const [k, v] of Object.entries(values)) this.setExport(k, v);
    },
    { context },
  );
});
await module.evaluate();
assert.equal(typeof handler, "function");
assert.ok(handler);
const boundHandler = handler;
/** @param {string} name */
const wire = (name) => "v1." + Buffer.from(name, "utf8").toString("base64url");
/** @param {string[][]} headers @param {string|null} [uid] */
function request(headers, uid = "gw-student@example.invalid") {
  const rawHeaders = [
    ...(uid === null ? [] : ["X-Trust-Auth-Uid", uid]),
    ...headers.flat(),
  ];
  return {
    rawHeaders,
    get(/** @type {string} */ name) {
      const result = [];
      for (let i = 0; i < rawHeaders.length; i += 2)
        if (rawHeaders[i].toLowerCase() === name.toLowerCase())
          result.push(rawHeaders[i + 1]);
      return result.length ? result.join(", ") : undefined;
    },
  };
}
let checks = 0;
for (const name of [
  "Тестовый участник",
  "ASCII Name",
  "e\u0301 / é",
  "O'Example <text> %2F + &",
  "Name 🧪",
  "🧪".repeat(256),
  "",
  "\ufeffName",
  wire("second-level"),
]) {
  calls = [];
  await boundHandler(
    request([
      ["x-trust-auth-name-utf8-b64", wire(name)],
      ["X-Trust-Auth-Name", "forged"],
    ]),
    {},
    () => {},
  );
  assert.equal(calls.length, 1);
  assert.equal(calls[0].params.name, name);
  assert.equal(calls[0].params.uid, "gw-student@example.invalid");
  assert.equal(calls[0].params.uin, null);
  assert.equal(calls[0].params.provider, "Shibboleth");
  assert.equal(calls[0].options.redirect, true);
  checks++;
}
const bad = [
  undefined,
  "",
  "v2.eA",
  "v1.A",
  "v1.eA=",
  "v1.eA==",
  "v1.eB",
  "v1.eA ",
  "v1.eA\n",
  "v1.eA,eA",
  "v1.+A",
  "v1./A",
  wire("\n"),
  wire("x".repeat(257)),
  wire("🧪".repeat(257)),
  "v1." + Buffer.from([255]).toString("base64url"),
  "v1." + Buffer.from([0xc0, 0xaf]).toString("base64url"),
  "v1." + Buffer.from([0xed, 0xa0, 0x80]).toString("base64url"),
];
for (const value of bad) {
  calls = [];
  await assert.rejects(() =>
    boundHandler(
      request(
        value === undefined
          ? [["X-Trust-Auth-Name", "forged"]]
          : [["X-Trust-Auth-Name-UTF8-B64", value]],
      ),
      {},
      () => {},
    ),
  );
  assert.equal(calls.length, 0);
  checks++;
}
for (const headers of [
  [
    ["X-Trust-Auth-Name-UTF8-B64", wire("one")],
    ["x-trust-auth-name-utf8-b64", wire("two")],
  ],
  [
    ["x-trust-auth-name-utf8-b64", wire("same")],
    ["X-TRUST-AUTH-NAME-UTF8-B64", wire("same")],
  ],
]) {
  calls = [];
  await assert.rejects(() => boundHandler(request(headers), {}, () => {}));
  assert.equal(calls.length, 0);
  checks++;
}
for (const uid of [null, "(null)"]) {
  calls = [];
  await assert.rejects(() =>
    boundHandler(
      request([["X-Trust-Auth-Name-UTF8-B64", wire("valid")]], uid),
      {},
      () => {},
    ),
  );
  assert.equal(calls.length, 0);
  checks++;
}
hasShib = false;
calls = [];
await assert.rejects(
  () =>
    boundHandler(
      request([["X-Trust-Auth-Name-UTF8-B64", wire("valid")]]),
      {},
      () => {},
    ),
  (e) => e instanceof HttpStatusError && e.status === 404,
);
assert.equal(calls.length, 0);
checks++;
console.log(
  JSON.stringify({
    scope:
      "pinned callback handler with mocked Router/loadUser; no native DB/UI claim",
    checks,
  }),
);
