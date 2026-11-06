# Проверка локального кандидата и граница Native

Публичное поведение grader проверяется командами из [публикации](releasing.md).
Результат host JDK25, реальный Docker image smoke и работа Native/Moodle — разные
наблюдения. Нет собственного toolchain-lock, source-tree inventory или
дополнительного разрешения запуска по совпадению hashes файлов.

`tools/stage_courses.py REGISTRY --storage STORAGE --compose-output FRESH
--images IMAGES` сохраняет существующий Native staging contract. Параметры
`--assembly-root`, `--admission-policy` и `--admission-policy-sha256` удалены.
Отдельная release assembly не требуется и не принимается как authority.

В этом старом course route остаются provenance/verification и course SHA;
их удаление требует согласованного изменения PL, Platform и Gateway readers.
Этот маршрут не объявлен новой hashless Native поставкой. Он не запускался
на production или студенческих данных. Новый вход/аутентификация и переключение
Native composition выбираются на итоговом просмотре. Course/CI UUID и реальные
Native numeric parents сохраняются как данные; старую VM не пересоздают.
