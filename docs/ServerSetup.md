# Setup

- Install Ubuntu server.
- Setup Wifi.
- Add SSH Key to connect.
- Turn off password auth for SSH.
- Create SSH Key for the server via `ssh-keygen -t ed25519 -C "fabian.bendun+thinkcenter-01@example.com"`
- Pull github `ai-living` into `/opt`
- Install sudo `apt-get install docker.io docker-compose-v2`

## Troubleshooting

- Adding password protection to the key after the fact `ssh-keygen -p -f ~/.ssh/id_ed25519`