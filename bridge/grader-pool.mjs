const limit = 2;
let active = 0;
const waiting = [];

export async function acquireLocalGrader() {
  if (active < limit) active++;
  else await new Promise((resolve) => waiting.push(resolve));
  let released = false;
  return () => {
    if (released) return;
    released = true;
    const next = waiting.shift();
    if (next) next();
    else active--;
  };
}
