/**
 * Проверяет итог ручной оценки после native percentage/total/rubric conversions.
 * Автоматически заработанные баллы и нормализованный score могут быть дробными.
 * @param {number | null} maxPoints
 * @param {number | null} maxManualPoints
 * @param {number | null} manualPoints null означает отсутствие изменения.
 */
export function assertIntegerManualPoints(maxPoints, maxManualPoints, manualPoints) {
  for (const [name, value] of [['max_points', maxPoints], ['max_manual_points', maxManualPoints]]) {
    if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) {
      throw new Error(`integerManualPoints: ${name} must be a non-negative safe integer; actual=${value}`);
    }
  }
  if (manualPoints === null) return;
  if (!Number.isSafeInteger(manualPoints) || manualPoints < 0 || manualPoints > /** @type {number} */ (maxManualPoints)) {
    throw new Error(`integerManualPoints: manual_points must be an integer in 0..${maxManualPoints}; actual=${manualPoints}`);
  }
}

/** Только представление: исходное число и нормализованный score не меняются.
 * @param {number | null} points
 */
export function displayIntegerPoints(points) {
  return typeof points === 'number' && Number.isFinite(points) ? String(Math.round(points)) : '—';
}
