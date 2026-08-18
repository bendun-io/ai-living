# Monitoring stack

This folder contains a simple monitoring setup for Ubuntu Server.

## Services

- Beszel Hub: central dashboard for system and container metrics
- Beszel Agent: reports host and Docker metrics to the hub
- Uptime Kuma: uptime and health checks for services

## Start the stack

Copy the example environment file and adjust the values:

```bash
cp monitoring/.env.example monitoring/.env
```

Then start the stack:

```bash
docker compose --env-file monitoring/.env -f monitoring/beszel-hub.yml up -d
docker compose --env-file monitoring/.env -f monitoring/beszel-agent.yml up -d
docker compose --env-file monitoring/.env -f monitoring/uptime-kuma.yml up -d
```

## Access

- Beszel Hub: http://<ubuntu-host>:${BESZEL_HUB_PORT:-8090}
- Uptime Kuma: http://<ubuntu-host>:${KUMA_PORT:-3001}

## Environment

The shared file contains:

```env
BESZEL_TOKEN=changeme
BESZEL_HUB_URL=http://127.0.0.1:8090
BESZEL_HUB_PORT=8090
KUMA_PORT=3001
```

## Notes

- The Beszel agent uses the host Docker socket and host filesystem for metrics.
- The folders are intended for Ubuntu Server deployments and assume Docker Compose is installed.
- The Beszel agent and Kuma are separate from the main app stacks to keep their configuration independent.
