.PHONY: install dev start serve prod check build health test-tts test-stt record-stt cache-stt

install:
	./scripts/server.sh install

dev:
	./scripts/server.sh dev

start:
	./scripts/server.sh start

serve:
	./scripts/server.sh serve

prod:
	./scripts/server.sh prod

check:
	./scripts/server.sh check

build:
	./scripts/server.sh build

health:
	./scripts/server.sh health

test-tts:
	./scripts/server.sh test-tts

test-stt:
	./scripts/server.sh test-stt

record-stt:
	./scripts/server.sh record-stt 7

cache-stt:
	./scripts/server.sh cache-stt