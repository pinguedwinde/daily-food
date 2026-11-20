PORT ?= 8421
VENV := venv
PY   := $(VENV)/bin/python

.DEFAULT_GOAL := help
.PHONY: help install run dev prod stop clean

help: ## Liste des commandes
	@grep -E '^[a-z]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-9s %s\n", $$1, $$2}'

$(VENV)/.installed: requirements.txt
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -q -r requirements.txt
	@touch $@

install: $(VENV)/.installed ## Crée le venv et installe les dépendances

run: install ## Lance l'app (http://localhost:$(PORT))
	PORT=$(PORT) $(PY) app.py

dev: install ## Lance avec rechargement automatique
	RELOAD=1 PORT=$(PORT) $(PY) app.py

prod: install ## Lance en production (écoute sur 0.0.0.0)
	HOST=0.0.0.0 PORT=$(PORT) $(PY) app.py

stop: ## Arrête l'app qui écoute sur $(PORT)
	@lsof -ti :$(PORT) | xargs kill 2>/dev/null && echo "arrêté" || echo "rien à arrêter"

clean: ## Supprime le venv
	rm -rf $(VENV)
