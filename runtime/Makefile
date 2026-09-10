.DEFAULT_GOAL := help
PYTHON ?= python3
HARNESS ?=
IMAGE ?=
SCOPE ?= workstation
VM_CONFIG ?=
TARGET ?=
RESOURCES ?=
export HARNESS IMAGE SCOPE VM_CONFIG TARGET RESOURCES
.PHONY: help build update activate resources test
help:
	@$(PYTHON) -B install.py --help
build update:
	$(PYTHON) -B install.py $@ "$$HARNESS"
activate:
	$(PYTHON) -B install.py activate "$$HARNESS" "$$IMAGE" --scope "$$SCOPE" --vm-config "$$VM_CONFIG" --target "$$TARGET"
resources:
	@document="$$( $(PYTHON) -I ../venv/entry.py --public-opencode-agents ../opencode/.opencode/config/opencode.json )" && \
	printf '%s\n' "$$document" | $(PYTHON) -I ../venv/entry.py --publish-opencode-agents "$$RESOURCES" && \
	printf '%s\n' "$$document" | $(PYTHON) -I ../venv/entry.py --opencode-agents-acl-plan "$$RESOURCES" > /dev/null
test:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s tests -v
