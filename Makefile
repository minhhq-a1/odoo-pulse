COMPOSE = docker compose -f deploy/playground/compose.yml

.PHONY: playground playground-reset playground-smoke

playground:            ## Boot Odoo + seed the demo story
	$(COMPOSE) up -d
	$(COMPOSE) logs -f seed

playground-reset:      ## Wipe the playground (drops the database)
	$(COMPOSE) down -v

playground-smoke:      ## End-to-end: boot, seed, assert reports, tear down
	./scripts/smoke/playground.sh
