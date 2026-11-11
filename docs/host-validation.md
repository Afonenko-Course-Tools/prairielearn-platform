# Проверка локального кандидата и граница Native

Публичное поведение grader проверяется командами из [публикации](releasing.md).
Результат host JDK25, реальный Docker image smoke и работа Native/Moodle — разные
наблюдения. Нет собственного toolchain-lock, source-tree inventory или
дополнительного разрешения запуска по совпадению hashes файлов.

`tools/stage_courses.py REGISTRY --storage STORAGE --compose-output FRESH
--images IMAGES` сохраняет ручной read-only снимок exact Git commit. Это отдельный
inspection/staging CLI, а не текущий маршрут обновления Local preview. Параметры
`--assembly-root`, `--admission-policy` и `--admission-policy-sha256` удалены.
Отдельная release assembly не требуется и не принимается как authority.

Текущая поставка содержит delivery v5 и отдельные private checks v3.
`package_integrity` проверяет выбранные native-файлы; действующие проверки
прав и UUID остаются у Bridge/PL. Дополнительные source/provenance receipts
для сборки не требуются. Полный declared/delivery контроль выполняет
`check-course.py verify`, а пользовательский сценарий проверяет реальный grader.

[Local prepare/up](development.md) использует стабильный writable course path
и native dev loader; [пример production CD](../examples/course-cd/README.md)
использует штатный Git-sync через REST. Они сохраняют course/instance UUID и
настоящие Native numeric parents. Старые БД, оценки и VM не пересоздаются.
