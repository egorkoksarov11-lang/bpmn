# BPMN Universal Engine — experimental r6

Автоматическая компоновка BPMN с сохранением бизнес-логики. В r6 добавлены комплексная оценка по 32 ручным референсам, выравнивание передач между ролями и экспериментальный адаптер ELK.

- **[Скачать BPMN](https://raw.githubusercontent.com/egorkoksarov11-lang/bpmn/main/output/process_08_v23.bpmn)** · **[Открыть SVG](https://raw.githubusercontent.com/egorkoksarov11-lang/bpmn/main/output/process_08_v23.svg)**
- [Исследование алгоритмов, сравнение и запуск](docs/DEVELOPMENT_R6.md)
- [Семь групп метрик](output/reference_conformity.json) · [Геометрия](output/geometry_report.json) · [Semantic diff](output/semantic_diff.json)
- [Калибровка на 32 референсах](tests/reports/reference_metrics_r6/reference_report.json) · [Эксперименты и неудачные варианты](tests/reports/r6_experiments.json)

На frozen №08: изгибы **199 → 151**, общая длина линий **51 990,8 → 49 858,3**, контакты **40 → 40**. Соответствие геометрическим признакам референсов **57,16 → 70,39 балла**; цель 80 пока не достигнута. Это диагностический индекс, а не подтверждённый человеком процент визуального сходства. Площадь выросла примерно на 4,9% ради более простых маршрутов.

Сохранены 64 узла, 95 переходов, 18 документных связей, 17 документных references и 6 дорожек. Semantic diff и DI diff = 0. Нет потерянных подписей, обрезанного текста, пересечений фигур, проходов сквозь фигуры и рёбер с более чем 8 изгибами. Шрифт Open Sans 13 px. Пересечения линий остаются; печать всей схемы на одном A4 слишком мелкая.

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python run_v23.py --input inputs/benchmark/process_08_v4_frozen.bpmn \
  --output-dir experiment-r6 --layout-engine lane-align \
  --incumbent examples/process_08_r4.bpmn --candidate-timeout 120 \
  --reference-profile src/v23/bpmn_v23/assets/reference_conformity_profile.json
PYTHONPATH=src/v23:src/v22 .venv/bin/python -m pytest tests src/v22/tests -q
```

Python ≥3.10. Для новой модели сначала запустить обычную компоновку без `--incumbent`, затем применить `lane-align` к полученному проверенному результату. Если не найден безопасный вариант, алгоритм завершится ошибкой, сохранив предыдущие выходные файлы. Время поиска ограничено, поэтому точные маршруты могут различаться между запусками.

Основной Python-backend работает без Node, Graphviz и сети. Необязательные внешние эксперименты: `npm ci` (Node ≥20), затем `--layout-engine elk`. ELK-проекция пока не прошла все проверки на других моделях и не заменяет основной алгоритм. Точные версии зафиксированы в lockfile; [ограничения и источники](docs/DEVELOPMENT_R6.md).

[Архитектура](docs/ARCHITECTURE_V23.md) · [Проверки](docs/TEST_REPORT_V23.md) · [История r3](docs/DEVELOPMENT_R3.md) · [r4](docs/DEVELOPMENT_R4.md) · [r5](docs/DEVELOPMENT_R5.md) · [Исследование ручных схем](docs/studies/HUMAN_LAYOUT_AUTOMATION_RULES_RU.md).

Исходная v22 не изменяется. Офисные документы, входные архивы и сырые журналы записи не публикуются.
