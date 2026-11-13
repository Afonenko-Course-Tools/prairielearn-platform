// Настоящий PostgreSQL parser и native binder; соединение с БД не открывается.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import vm from "node:vm";
import { parse } from "pgsql-parser";
import { pg, present } from "../helpers/pg-nodes.mjs";
import { loadSql } from "../fixtures/native-postgres-upstream/loader.js";

const sourceFlag = process.argv.find((value) =>
  value.startsWith("--sql-source="),
);
const path = sourceFlag
  ? sourceFlag.slice("--sql-source=".length)
  : fileURLToPath(new URL("../../bridge/native.sql", import.meta.url));
const sql = loadSql(path);
const pool = readFileSync(
  new URL("../fixtures/native-postgres-upstream/pool.js", import.meta.url),
  "utf8",
);
const context = vm.createContext({
  difference: (/** @type {string[]} */ a, /** @type {string[]} */ b) =>
    a.filter((key) => !b.includes(key)),
});
new vm.Script(
  pool.slice(
    pool.indexOf("function paramsToArray("),
    pool.indexOf("\n/**", pool.indexOf("function paramsToArray(")),
  ) + "\nglobalThis.bind=paramsToArray;",
).runInContext(context);
const query = sql.grant_administrator;
const { processedSql: boundSql, paramsArray: params } =
  /** @type {import("../../types/test-contracts.d.ts").NativeBinder} */ (
    context
  ).bind(query, { uid: "student@fixture.invalid", user_id: "21" }, true);
const ast = pg(
  present(present((await parse(boundSql)).stmts)[0]).stmt,
  "SelectStmt",
);
const ctes = Object.fromEntries(
  present(present(ast.withClause).ctes).map((node) => {
    const row = pg(node, "CommonTableExpr");
    return [present(row.ctename), pg(row.ctequery, "InsertStmt")];
  }),
);
/** @param {unknown} node */
const columns = (node) =>
  present(pg(node, "ColumnRef").fields)
    .map((field) => pg(field, "String").sval)
    .join(".");
/** @param {import('@pgsql/types').Node | undefined} node @returns {Array<[string,unknown]>} */
function predicates(node) {
  if (node && "BoolExpr" in node)
    return present(node.BoolExpr.args).flatMap(predicates);
  const expression = pg(node, "A_Expr");
  assert.equal(pg(present(expression.name)[0], "String").sval, "=");
  const right = present(expression.rexpr);
  return [
    [
      columns(expression.lexpr),
      "ParamRef" in right
        ? params[present(right.ParamRef.number) - 1]
        : columns(right),
    ],
  ];
}

test("Administrator insert и повторный readback связывают native UID с тем же user ID", () => {
  assert.deepEqual(
    predicates(pg(ctes.inserted.selectStmt, "SelectStmt").whereClause).sort(),
    [
      ["id", "21"],
      ["uid", "student@fixture.invalid"],
    ],
  );
  const repeat = pg(
    pg(
      present(
        pg(pg(present(ast.targetList)[0], "ResTarget").val, "BoolExpr").args,
      )[1],
      "SubLink",
    ).subselect,
    "SelectStmt",
  );
  const actual = predicates(repeat.whereClause)
    .map(([key, value]) => [key.split(".").at(-1), value])
    .sort();
  assert.deepEqual(actual, [
    ["id", "21"],
    ["uid", "student@fixture.invalid"],
  ]);
  assert.deepEqual(
    predicates(pg(present(repeat.fromClause)[0], "JoinExpr").quals),
    [["u.id", "a.user_id"]],
  );
});

test("Administrator audit пишет только новую native запись, повтор не создаёт audit", () => {
  assert.equal(present(ctes.inserted.relation).relname, "administrators");
  assert.equal(
    present(ctes.inserted.onConflictClause).action,
    "ONCONFLICT_NOTHING",
  );
  assert.deepEqual(
    present(
      present(present(ctes.inserted.onConflictClause).infer).indexElems,
    ).map((row) => pg(row, "IndexElem").name),
    ["user_id"],
  );
  assert.equal(present(ctes.audit.relation).relname, "audit_logs");
  assert.deepEqual(
    present(ctes.audit.cols).map((row) => pg(row, "ResTarget").name),
    ["authn_user_id", "user_id", "table_name", "row_id", "action", "new_state"],
  );
  const audit = pg(ctes.audit.selectStmt, "SelectStmt");
  assert.equal(
    pg(present(audit.fromClause)[0], "RangeVar").relname,
    "inserted",
  );
  const values = present(audit.targetList).map(
    (row) => pg(row, "ResTarget").val,
  );
  assert.equal(params[present(pg(values[0], "ParamRef").number) - 1], "21");
  assert.equal(columns(values[1]), "inserted.user_id");
  assert.equal(present(pg(values[2], "A_Const").sval).sval, "administrators");
  assert.equal(columns(values[3]), "inserted.id");
  assert.equal(present(pg(values[4], "A_Const").sval).sval, "insert");
  assert.equal(
    pg(present(pg(values[5], "FuncCall").funcname)[0], "String").sval,
    "to_jsonb",
  );
  assert.equal(columns(present(pg(values[5], "FuncCall").args)[0]), "inserted");
});

test("Native binder отклоняет лишние и отсутствующие параметры grant/lock", () => {
  for (const bad of [
    { uid: "student@fixture.invalid" },
    { user_id: "21" },
    {
      uid: "student@fixture.invalid",
      user_id: "21",
      email: "owner@fixture.invalid",
    },
  ])
    assert.throws(() => context.bind(query, bad, true));
  assert.doesNotThrow(() =>
    context.bind(
      sql.lock,
      { lock_key: "gateway:73:student@fixture.invalid" },
      true,
    ),
  );
});
