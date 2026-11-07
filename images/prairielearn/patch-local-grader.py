"""Ограничить pinned локальный grader и освободить слот после очистки контейнера."""
from pathlib import Path
import re
import sys


def patch(source: str) -> str:
    markers = [
        '(async () => {', '})()',
        'Memory: (1 << 30) * 2', 'MemorySwap: (1 << 30) * 2',
        'const container = await docker.createContainer({',
        'const timeoutId = setTimeout(() => {',
    ]
    removal = r'(?m)^\s*await container\.remove\(\{\s*// Remove any volumes associated with this container\s*v: true,\s*\}\);'
    if any(source.count(value) != 1 for value in markers) or len(re.findall(removal, source)) != 1:
        raise ValueError('Pinned local grader differs; review upstream')
    source = source.replace(markers[0], markers[0] + '''
const releaseLocalGrader = await acquireLocalGrader();
let container;
let timeoutId;
let gradingFailure;
let gradingFailed = false;
try {''', 1)
    source = source.replace(markers[4], 'container = await docker.createContainer({', 1)
    source = source.replace(markers[5], 'timeoutId = setTimeout(() => {', 1)
    source = re.sub(removal, '', source, count=1)
    source = source.replace(markers[1], '''} catch (error) {
  gradingFailed = true;
  gradingFailure = error;
  throw error;
} finally {
  clearTimeout(timeoutId);
  let removed = !container;
  let cleanupTimer;
  let cleanupFailure;
  let cleanupFailed = false;
  const cleanupContainer = container;
  if (cleanupContainer) {
    try {
      // Ограничено ожидание, не отменён запрос Docker. Поздний ответ не освобождает слот.
      await Promise.race([
        (async () => {
          try {
            await cleanupContainer.remove({force: true, v: true});
            removed = true;
          } catch (error) {
            if (typeof error === 'object' && error !== null && 'statusCode' in error && error.statusCode === 404) {
              removed = true;
              return;
            }
            throw error;
          }
        })(),
        new Promise((_, reject) => {
          cleanupTimer = setTimeout(() => reject(new Error('Local grader container cleanup timed out')), 10000);
        }),
      ]);
    } catch (error) {
      cleanupFailed = true;
      cleanupFailure = error;
      logger.error('Local grader cleanup failed; unconfirmed container retains its slot', error);
    } finally {
      clearTimeout(cleanupTimer);
    }
  }
  if (removed) releaseLocalGrader();
  if (cleanupFailed) {
    throw new AggregateError(gradingFailed ? [gradingFailure, cleanupFailure] : [cleanupFailure],
      'Local grader container cleanup failed');
  }
}
})()''', 1)
    for value in markers[2:4]:
        source = source.replace(value, value.split(':')[0] + ': 512 * 1024 * 1024')
    return "import { acquireLocalGrader } from '../../bridge/grader-pool.mjs';\n" + source


if __name__ == '__main__':
    for name in sys.argv[1:]:
        path = Path(name)
        path.write_text(patch(path.read_text()))
