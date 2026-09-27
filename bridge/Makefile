PI ?= akhadiev@192.168.31.250
REMOTE_SRC ?= /tmp/treadmill-bridge-src

.PHONY: test deploy logs status

test:
	uv run pytest -q

deploy:
	rsync -a --delete --exclude .venv --exclude __pycache__ --exclude .pytest_cache ./ $(PI):$(REMOTE_SRC)/
	ssh $(PI) 'sudo install -d /opt/treadmill-bridge && sudo rsync -a --delete --exclude .venv $(REMOTE_SRC)/ /opt/treadmill-bridge/bridge/ && sudo sh /opt/treadmill-bridge/bridge/deploy/install.sh'

logs:
	ssh $(PI) 'journalctl -u treadmill-bridge -n 100 --no-pager'

status:
	ssh $(PI) 'systemctl is-active treadmill-bridge; TOKEN=$$(sudo grep api_token /etc/treadmill-bridge/config.toml | cut -d\" -f2); curl -s -H "Authorization: Bearer $$TOKEN" http://localhost:8080/api/v1/status'
