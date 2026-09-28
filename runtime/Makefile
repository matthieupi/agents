.DEFAULT_GOAL := help
PYTHON ?= python3
HARNESS ?=
IMAGE ?=
SCOPE ?= workstation
RESOURCES ?=
export HARNESS IMAGE SCOPE RESOURCES
.PHONY: help build update activate resources test
help:
	@$(PYTHON) -B install.py --help
build update:
	$(PYTHON) -B install.py $@ "$$HARNESS"
activate:
	$(PYTHON) -B install.py activate "$$HARNESS" "$$IMAGE" --scope "$$SCOPE"
resources:
	$(PYTHON) -I ../opencode/scripts/public-resources.py ../opencode/.opencode/config/opencode.json "$$RESOURCES"
test:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s tests -v
