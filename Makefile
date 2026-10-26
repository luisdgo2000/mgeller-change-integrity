# MGeller — tareas locales. Solo biblioteca estándar (PyYAML opcional para YAML y lint).
PY ?= python3
SKILL := skills/mgeller-change-integrity

.PHONY: test lint verificar

test:   ## Escenarios de validación (Git temporal + producto de ejemplo)
	$(PY) -m unittest discover -s tests -v

lint:   ## SKILL.md contra la especificación de Agent Skills
	$(PY) herramientas/lint_skill.py $(SKILL)

verificar: lint test
