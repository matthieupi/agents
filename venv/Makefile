# SSH working directory: <agents-source>/venv. Never run this Makefile as root.
.DEFAULT_GOAL := help
.PHONY: help pi omp opencode t3
help:
	@printf '%s\n' 'make pi|omp|opencode|t3: build selected harness with cache, then activate'

pi omp opencode t3:
	/usr/bin/python3 build.py $@
