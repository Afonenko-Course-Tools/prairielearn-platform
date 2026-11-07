const limit = 2;
let active = 0;
/** @type {Array<() => void>} */
const waiting = [];

export async function acquireLocalGrader() {
  if (active < limit) active++;
  else {
    /** @type {Promise<void>} */
    const ready = new Promise(resolve => { waiting.push(resolve); });
    await ready;
  }
  let released = false;
  return () => {
    if (released) return;
    released = true;
    const next = waiting.shift();
    if (next) next();
    else active--;
  };
}
