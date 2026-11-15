import assert from "node:assert/strict";
import test from "node:test";
import * as policy from "../../bridge/policy.mjs";
test("canonical keys use Unicode scalar order across BMP private use and astral characters", () => {
  assert.equal(typeof policy.canonicalJSONString, "function");
  assert.equal(
    policy.canonicalJSONString({ "𐀀": 2, "\ue000": 1 }),
    '{"":1,"𐀀":2}',
  );
  assert.equal(
    policy.canonicalJSONString({
      nested: { "𐀀": 2, "\ue000": 1 },
      values: [2, 1],
    }),
    '{"nested":{"":1,"𐀀":2},"values":[2,1]}',
  );
});

test("canonical numeric-looking keys remain lexical rather than JS enumeration order", () => {
  assert.equal(
    policy.canonicalJSONString({ 2: "two", 10: "ten" }),
    '{"10":"ten","2":"two"}',
  );
});
test("gateway bridge fails closed for development runtime or missing Community identity", () => {
  assert.equal(typeof policy.assertProductionRuntime, "function");
  policy.assertProductionRuntime("production", {
    devMode: false,
    hasShib: true,
  });
  assert.throws(() =>
    policy.assertProductionRuntime("development", {
      devMode: false,
      hasShib: true,
    }),
  );
  assert.throws(() =>
    policy.assertProductionRuntime("production", {
      devMode: true,
      hasShib: true,
    }),
  );
  assert.throws(() =>
    policy.assertProductionRuntime("production", {
      devMode: false,
      hasShib: false,
    }),
  );
});
