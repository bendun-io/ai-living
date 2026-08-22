# Readme

## Setup

Start the required services first:

- From the telegram-stack folder:
  - `docker compose up -d --build`
- From the n8n folder:
  - `docker compose up -d --build`

## Ngrok forwarding

To expose your local app running on port 3000 to Telegram, start ngrok and forward port 3000:

- `ngrok http 3000`

Use the generated public HTTPS URL in your webhook configuration.

## Telegram webhook

Set the Telegram webhook with the command below (replace the URL with your current ngrok URL):

```bash
curl "https://api.telegram.org/bot8831100892:AAFR0GPBchSVl-4-vb5p4Zrm5ebdr4XnCgk/setWebhook?url=https://telegram.bendun.io/telegram/webhook&secret_token=XXX"
```

> Reminder: run the webhook setup again whenever your ngrok URL changes.

## Migration

To migrate this setup to a new machine, follow these steps:

1. Clone or copy this repository to the new machine.
2. Install Docker Desktop and make sure Docker Compose is available.
3. Make sure the required external Docker network exists if your stack depends on it:
   - `docker network create telegram-stack`
4. Start the services again:
   - `docker compose up -d --build` in the telegram-stack folder
   - `docker compose up -d --build` in the n8n folder
5. If you use ngrok, start it again on the new machine:
   - `ngrok http 3000`
6. Re-register the Telegram webhook with the new public ngrok URL.

If you rely on persisted data, copy the relevant Docker volumes before starting the containers:

- In the telegram-stack stack, the Kafka data volume is named `kafka-data` and is mounted at `/var/lib/kafka/data`.
  - On the old machine, back it up with:
    - `docker volume inspect kafka-data`
    - `docker run --rm -v kafka-data:/source -v ${PWD}:/backup alpine sh -c "cp -a /source/. /backup/"`
  - On the new machine, restore it with:
    - `docker volume create kafka-data`
    - `docker run --rm -v kafka-data:/target -v ${PWD}:/backup alpine sh -c "cp -a /backup/. /target/"`

- In the n8n stack, the main data volume is named `n8n_data` and is mounted at `/home/node/.n8n`.
  - Back it up from the old machine with:
    - `docker volume inspect n8n_data`
    - `docker run --rm -v n8n_data:/source -v ${PWD}:/backup alpine sh -c "cp -a /source/. /backup/"`
  - Restore it on the new machine with:
    - `docker volume create n8n_data`
    - `docker run --rm -v n8n_data:/target -v ${PWD}:/backup alpine sh -c "cp -a /backup/. /target/"`

If you do not need to preserve state, you can skip the volume backup and let Docker recreate the volumes from scratch.

