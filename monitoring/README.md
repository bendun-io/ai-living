# Monitoring stack

This folder contains a simple monitoring setup for Ubuntu Server.

## Services

- Beszel Hub: central dashboard for system and container metrics
- Beszel Agent: reports host and Docker metrics to the hub
- Uptime Kuma: uptime and health checks for services

## Start the stack

```bash
docker compose -f monitoring/beszel-hub.yml up -d
docker compose -f monitoring/beszel-agent.yml up -d
docker compose -f monitoring/uptime-kuma.yml up -d
```

## Access

- Beszel Hub: http://<ubuntu-host>:8090
- Uptime Kuma: http://<ubuntu-host>:3001

## Environment

For the Beszel agent, set a token before starting it:

```bash
export BESZEL_TOKEN=your-secret-token
```

Then run the agent compose file again.

## Notes

- The Beszel agent uses the host Docker socket and host filesystem for metrics.
- The folders are intended for Ubuntu Server deployments and assume Docker Compose is installed.
- The Beszel agent and Kuma are separate from the main app stacks to keep their configuration independent.
