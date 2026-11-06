// Настоящий PostgreSQL parser и native binder; соединение с БД не открывается.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import vm from 'node:vm';
import {parse} from 'pgsql-parser';
import {loadSql} from '../fixtures/native-postgres-upstream/loader.js';

const sourceFlag = process.argv.find(value => value.startsWith('--sql-source='));
const path = sourceFlag ? sourceFlag.slice('--sql-source='.length) : new URL('../../bridge/native.sql', import.meta.url).pathname;
const sql = loadSql(path);
const pool = readFileSync(new URL('../fixtures/native-postgres-upstream/pool.js', import.meta.url), 'utf8');
const context = vm.createContext({difference: (a, b) => a.filter(key => !b.includes(key))});
new vm.Script(pool.slice(pool.indexOf('function paramsToArray('), pool.indexOf('\n/**', pool.indexOf('function paramsToArray('))) + '\nglobalThis.bind=paramsToArray;').runInContext(context);
const query = sql.grant_administrator;
const {processedSql: boundSql, paramsArray: params} = context.bind(query, {uid: 'student@fixture.invalid', user_id: '21'}, true);
const ast = (await parse(boundSql)).stmts[0].stmt.SelectStmt;
const ctes = Object.fromEntries(ast.withClause.ctes.map(({CommonTableExpr: row}) => [row.ctename, row.ctequery.InsertStmt]));
const columns = node => node.ColumnRef.fields.map(field => field.String.sval).join('.');
function predicates(node) {
  if (node.BoolExpr) return node.BoolExpr.args.flatMap(predicates);
  const expression = node.A_Expr;
  assert.equal(expression.name[0].String.sval, '=');
  return [[columns(expression.lexpr), expression.rexpr.ParamRef ? params[expression.rexpr.ParamRef.number - 1] : columns(expression.rexpr)]];
}

test('Administrator insert и повторный readback связывают native UID с тем же user ID', () => {
  assert.deepEqual(predicates(ctes.inserted.selectStmt.SelectStmt.whereClause).sort(), [['id', '21'], ['uid', 'student@fixture.invalid']]);
  const repeat = ast.targetList[0].ResTarget.val.BoolExpr.args[1].SubLink.subselect.SelectStmt;
  const actual = predicates(repeat.whereClause).map(([key, value]) => [key.split('.').at(-1), value]).sort();
  assert.deepEqual(actual, [['id', '21'], ['uid', 'student@fixture.invalid']]);
  assert.deepEqual(predicates(repeat.fromClause[0].JoinExpr.quals), [['u.id', 'a.user_id']]);
});

test('Administrator audit пишет только новую native запись, повтор не создаёт audit', () => {
  assert.equal(ctes.inserted.relation.relname, 'administrators');
  assert.equal(ctes.inserted.onConflictClause.action, 'ONCONFLICT_NOTHING');
  assert.deepEqual(ctes.inserted.onConflictClause.infer.indexElems.map(row => row.IndexElem.name), ['user_id']);
  assert.equal(ctes.audit.relation.relname, 'audit_logs');
  assert.deepEqual(ctes.audit.cols.map(row => row.ResTarget.name), ['authn_user_id', 'user_id', 'table_name', 'row_id', 'action', 'new_state']);
  const audit = ctes.audit.selectStmt.SelectStmt;
  assert.equal(audit.fromClause[0].RangeVar.relname, 'inserted');
  const values = audit.targetList.map(row => row.ResTarget.val);
  assert.equal(params[values[0].ParamRef.number - 1], '21');
  assert.equal(columns(values[1]), 'inserted.user_id');
  assert.equal(values[2].A_Const.sval.sval, 'administrators');
  assert.equal(columns(values[3]), 'inserted.id');
  assert.equal(values[4].A_Const.sval.sval, 'insert');
  assert.equal(values[5].FuncCall.funcname[0].String.sval, 'to_jsonb');
  assert.equal(columns(values[5].FuncCall.args[0]), 'inserted');
});

test('Native binder отклоняет лишние и отсутствующие параметры grant/lock', () => {
  for (const bad of [{uid: 'student@fixture.invalid'}, {user_id: '21'}, {uid: 'student@fixture.invalid', user_id: '21', email: 'owner@fixture.invalid'}])
    assert.throws(() => context.bind(query, bad, true));
  assert.doesNotThrow(() => context.bind(sql.lock, {lock_key: 'gateway:73:student@fixture.invalid'}, true));
});
