# Исходники локального External grader

`externalGraderLocal.ts` и собранный `externalGraderLocal.js` — сохранённые
исходники PrairieLearn `92584fe426ececb84bc2d09de9975c7056c0c5f6`, на котором
основан образ Community в Dockerfile. Используются для проверки существующего
патча и поведения жизненного цикла. В тесте исполняется полный JS, Docker и
внешний ввод-вывод заменены; это не проверка настоящего Docker или VM.
