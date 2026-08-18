@echo off
setlocal

; REM see https://docs.n8n.io/deploy/host-n8n/install-options/install-with-docker

docker compose pull

docker compose down

docker compose up -d