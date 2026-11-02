# Публичная поставка v23.1.2 experimental

Включены неизменённый код v22, реализация v23, frozen v4, геометрический incumbent r2 для воспроизводимого сравнения, тесты, отчёты, профиль референсов и итоговые BPMN/SVG. Для запуска не требуется история чата. ZIP v22, офисные формы и сырые журналы наблюдения остаются локальными входами и не публикуются.

Источник бизнес-логики — inputs/benchmark/process_08_v4_frozen.bpmn. examples/process_08_r2.bpmn — только проверяемая исходная геометрия для сравнительного эксперимента, не замена frozen v4.

Запуск, ограничения и показатели приведены в README.md и docs/DEVELOPMENT_R3.md. Результат экспериментальный; полная читаемая печать на A4 и глобальная оптимальность не заявляются.

## Дополнение r6

Новые необязательные npm-зависимости зафиксированы в `package.json`/`package-lock.json`. Добавлены `tools/calibrate_references.py`, `tools/reference_sensitivity.py`, `tools/probe_auto_layout.cjs`, адаптеры размещения и статический профиль `src/v23/bpmn_v23/assets/reference_conformity_profile.json`. Внешние библиотеки и node_modules не публикуются. Результаты: `output/reference_conformity.json`, `tests/reports/reference_metrics_r6/`, `tests/reports/r6_experiments.json`, `tests/reports/r6_all_tests.xml`; описание — `docs/DEVELOPMENT_R6.md`. Исходный r4 сохранён в `examples/process_08_r4.bpmn` с его отчётом размещения.

## Дополнение r7

Добавлены `src/v23/bpmn_v23/continuity.py`, режим `local-continuity`, `tools/measure_continuity.py`, `tests/test_continuity.py`, `tests/reports/r7_all_tests.xml`, `tests/reports/r7_reference_continuity.json`, `docs/DEVELOPMENT_R7.md`. Исходный проверенный r6 сохранён в `examples/process_08_r6.bpmn` и его отчёте. Обновлены выходные BPMN/SVG и независимые отчёты. Входные файлы и исходный v22 сохранены.

## Дополнение r8

Добавлены `axis_layout.py`, `axis_corridors.py`, `axis_labels.py`, `adaptive_layout.py`; adaptive стал обычным режимом CLI/API. Legacy-флаги размещения без явного движка сохраняют human. Добавлены инструменты `benchmark_references.py`, `perturb_reference_di.py`, `package_benchmark.py`, регрессии осей, упаковки и заголовков ролей. Основные данные — `tests/reports/r8/`, полный прогон — `tests/reports/r8_all_tests.xml`, описание — `docs/DEVELOPMENT_R8.md`.

`examples/benchmarks/r8/` содержит отдельные BPMN/SVG до/после, два ZIP с автономными галереями и контрольные SHA256SUMS. Основной пакет содержит 49 редактируемых BPMN (контроль/новые/расширенный прогон); тест со смещениями — ещё 12 файлов до/после. Это версии результатов, а не число разных процессов. Исходные архивы и офисные документы в пакет не включены. Геометрия №08 остаётся r7; новые предложения отражены в `output/r8_candidate_audit.json`. У `output/run_report.json` нормализован аудит кандидатов, а в SVG исправлено вписывание полных названий ролей.
