import assert from 'node:assert/strict';
/** @template T @param {T} value @returns {NonNullable<T>} */
export function present(value) {
  assert.ok(value !== undefined && value !== null, 'Обязательное поле PostgreSQL AST отсутствует');
  return value;
}
/** @template {import('../../types/test-contracts.d.ts').PgNodeKind} K @param {unknown} node @param {K} kind @returns {import('../../types/test-contracts.d.ts').PgNodeData<K>} */
export function pg(node, kind) {
  assert.ok(node && typeof node === 'object' && Object.hasOwn(node, kind), 'Ожидался узел PostgreSQL AST: ' + kind);
  /** @type {unknown} */
  const value = Reflect.get(node, kind);
  // Дискриминатор проверен; тип ветви берётся из настоящего @pgsql/types.
  return /** @type {import('../../types/test-contracts.d.ts').PgNodeData<K>} */(value);
}
