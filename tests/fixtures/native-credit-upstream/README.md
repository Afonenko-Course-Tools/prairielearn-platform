# Pinned Native code для source-контролей

Исходный Community commit: `92584fe426ececb84bc2d09de9975c7056c0c5f6`, официальный base image `prairielearn/prairielearn@sha256:60c675a42055a430f9ad7298c7dfd2f37119aa471f806e21e2c929de28435f63`.

`lib/*.ts` и `models/grading-job.ts` взяты из принятого source-пакета архитектурного исследования. Пары `dist/lib/*.js`, `dist/models/grading-job.js`, compiled db-types/file-store и student route/middleware прочитаны как публичный исполняемый код из immutable image config `4e41b6d1ed1cbf00cb93edce45955b71146c84149aeeb70406642fce1d00609e`. Это существующий производный образ того же pinned Community base. Здесь нет production config, пользователей, ответов, course private data или архивов состояния.

`SOURCE.json` сохраняет upstream commit и список десяти входов патча. Patcher проверяет единственность изменяемых границ во всех входах до записи; функциональные тесты проверяют добавленные hooks и отказ при повреждении границ. Остальные файлы служат source-контролям Native schema/file-store/download. Новый credit image ещё не собран; эти fixtures не являются его actual readback и не доказывают Native SQL/HTTP выполнение.
