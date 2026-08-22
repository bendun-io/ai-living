const express = require("express");
const { Kafka } = require("kafkajs");

const app = express();

app.use(express.json());


const brokerList = (process.env.KAFKA_BROKERS || "kafka:9092")
    .split(",")
    .map((entry) => entry.trim())
    .filter(Boolean);

const kafka = new Kafka({
    clientId: "telegram-webhook",
    brokers: brokerList
});


const producer = kafka.producer();
let producerReady = false;


async function start() {
    const maxAttempts = Number(process.env.KAFKA_CONNECT_MAX_ATTEMPTS || 20);
    const retryDelayMs = Number(process.env.KAFKA_CONNECT_RETRY_DELAY_MS || 1500);

    for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
        try {
            await producer.connect();
            producerReady = true;
            console.log(`Kafka producer connected to ${brokerList.join(", ")}`);
            return;
        } catch (error) {
            console.error(`Kafka connect failed (attempt ${attempt}/${maxAttempts})`, error);
            await new Promise((resolve) => setTimeout(resolve, retryDelayMs));
        }
    }

    throw new Error(`Kafka producer could not connect after ${maxAttempts} attempts`);
}


app.post("/telegram/webhook", async (req, res) => {

    const token =
        req.headers["x-telegram-bot-api-secret-token"];


    if (token !== process.env.TELEGRAM_SECRET) {
        return res.sendStatus(401);
    }

    if (!producerReady) {
        return res.status(503).json({ error: "Kafka producer not ready" });
    }

    try {
        await producer.send({
            topic: "telegram-updates",
            messages: [
                {
                    value: JSON.stringify(req.body)
                }
            ]
        });

        res.sendStatus(200);
    } catch (error) {
        console.error("Kafka publish failed", error);
        res.status(503).json({ error: "Kafka publish failed" });
    }
});


start().catch((error) => {
    console.error("Fatal startup error", error);
    process.exit(1);
});


app.listen(3000, () => {
    console.log("Webhook listening");
});