const express = require("express");
const { Kafka } = require("kafkajs");

const app = express();

app.use(express.json());


const kafka = new Kafka({
    clientId: "telegram-webhook",
    brokers: ["kafka:9092"]
});


const producer = kafka.producer();


async function start() {
    await producer.connect();
}


app.post("/telegram/webhook", async (req, res) => {

    const token =
        req.headers["x-telegram-bot-api-secret-token"];


    if (token !== process.env.TELEGRAM_SECRET) {
        return res.sendStatus(401);
    }


    await producer.send({
        topic: "telegram-updates",
        messages: [
            {
                value: JSON.stringify(req.body)
            }
        ]
    });


    res.sendStatus(200);
});


start();


app.listen(3000, () => {
    console.log("Webhook listening");
});