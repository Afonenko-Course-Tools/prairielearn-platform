# Ограничение доступа процесса

Dockerfile компилирует `sandbox.c` обычным системным C compiler. Готовый helper
поставляется в образе; собственный binary inventory и SHA reader удалены.
Происхождение исходного кода сохраняет `PRAIRIELEARN-LICENSE`.

Supervisor проверяет владельца, права, отсутствие symlink/capabilities и
доступность helper перед выполнением. Ядро Landlock задаёт ограничения файловой
системы; реальные UID, private paths и network namespace проверяются отдельно.
Изменение `/dev/null` сохраняет корректную работу вложенного JVM без открытия
произвольного `/dev`. Исходный helper не даёт разрешения на production deployment.
