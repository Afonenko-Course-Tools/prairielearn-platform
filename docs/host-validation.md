# Host validation2.4.1

Это исходный выпуск host-tools, совместимый с digit-first instance именами Exporter. Runtime images/assets и Native provenance сохраняют фактическую Platform2.4.0 M3 identity; новый runtime build не требуется.

Для отдельного host-tools checkout используйте штатный `tools/stage_courses.py REGISTRY --storage STORAGE --compose-output FRESH --images M3_ASSETS/images.lock.json --assembly-root ORIGINAL_M3_ASSEMBLY`. Параметр выбирает только источник исходного Context; его закрытые assets, source/tree, provenance equality и recheck не ослаблены. Без параметра сохраняется прежний source-root default. Native IDs, route IDs и DB IDs не взаимозаменяемы.

Для явно разрешённого импорта с отложенной квалификацией передайте вместе `--admission-policy FILE --admission-policy-sha256 SHA256`. Без этой пары сохраняется строгий receipt gate. Policy — закрытая запись точного route/native Git/payload/catalog/M3 Context и human/privacy/failed-report hashes с конечным expiresAt (не более24часов). Только совпадающий route использует `package-integrity-user-deferred`; остальные courses проходят строгую проверку receipt. Результат — `DEFERRED_BY_USER / NOT_VERIFIED`, никогда verified receipt. Файл policy и статус находятся вне Native, его bytes/provenance не меняются.
