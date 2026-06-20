.PHONY: install dev start check test-tts test-stt

install:
	./scripts/server.sh install

dev:
	./scripts/server.sh dev

start:
	./scripts/server.sh start

check:
	./scripts/server.sh check

test-tts:
	./scripts/server.sh test-tts

test-stt:
	./scripts/server.sh test-stt
