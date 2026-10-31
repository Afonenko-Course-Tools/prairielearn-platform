# Проверка целевой среды Platform 2.5.0

Этот исходный кандидат объединяет изменения host-tools 2.4.1, обычный библиотечный JAR без Main-Class, отчёт JUnit и SP Workspace. Он меняет runtime и требует нового закрытого контекста, настоящей сборки образа и независимой квалификации. Проверка исходников и локальные диагностические JUnit-запуски не подтверждают готовность образа либо выпуска.

Исторические комплекты M3 сохраняют свои точные images/assets и provenance; их идентичность не переносится на новый кандидат автоматически. Поддержка digit-first instance имён Exporter сохранена.

Для отдельного host-tools checkout используйте штатный `tools/stage_courses.py REGISTRY --storage STORAGE --compose-output FRESH --images M3_ASSETS/images.lock.json --assembly-root ORIGINAL_M3_ASSEMBLY`. Параметр выбирает только источник исходного Context; его закрытые assets, source/tree, provenance equality и recheck не ослаблены. Без параметра сохраняется прежний source-root default. Native IDs, route IDs и DB IDs не взаимозаменяемы.

Для явно разрешённого импорта с отложенной квалификацией передайте вместе `--admission-policy FILE --admission-policy-sha256 SHA256`. Без этой пары сохраняется строгий receipt gate. Policy — закрытая запись точного route/native Git/payload/catalog/M3 Context и human/privacy/failed-report hashes с конечным expiresAt (не более24часов). Только совпадающий route использует `package-integrity-user-deferred`; остальные courses проходят строгую проверку receipt. Результат — `DEFERRED_BY_USER / NOT_VERIFIED`, никогда verified receipt. Файл policy и статус находятся вне Native, его bytes/provenance не меняются.
