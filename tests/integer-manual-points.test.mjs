import assert from "node:assert/strict";
import test from "node:test";
import {
  assertIntegerManualPoints,
  displayIntegerPoints,
} from "../tools/integer-manual-points.mjs";

test("native derived manual points preserve endpoints and integer partial credit", () => {
  for (const manual of [0, 1, 2, null])
    assertIntegerManualPoints(10, 2, manual);
  // Percentage conversions may be fractional as percentages; earned manual points may not.
  assertIntegerManualPoints(3, 3, ((100 / 3) * 3) / 100);
});

test("integer display rounds nearest and preserves raw ratio", () => {
  const raw = 8 / 3;
  assert.equal(displayIntegerPoints(raw), "3");
  assert.equal(raw, 8 / 3);
  assert.equal(displayIntegerPoints(2.49), "2");
  assert.equal(displayIntegerPoints(2.5), "3");
  assert.equal(displayIntegerPoints(0), "0");
  assert.equal(displayIntegerPoints(null), "—");
});

test("fractional, negative, bonus, nonfinite and fractional maxima reject", () => {
  for (const manual of [0.5, -1, 3, NaN, Infinity, -Infinity]) {
    assert.throws(
      () => assertIntegerManualPoints(10, 2, manual),
      /manual_points.*0\.\.2/,
    );
  }
  for (const [max, manualMax] of [
    [10.5, 2],
    [10, 2.5],
    [null, 2],
    [10, null],
    [-1, 2],
    [10, Infinity],
  ]) {
    assert.throws(
      () => assertIntegerManualPoints(max, manualMax, null),
      /max_.*safe integer/,
    );
  }
});
