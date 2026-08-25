'use strict';

const express = require('express');
const config = require('./config');
const browserManager = require('./browserManager');
const healthRoutes = require('./routes/health');
const agentRoutes = require('./routes/agent');
const searchRoutes = require('./routes/search');
const cartRoutes = require('./routes/cart');
const adminRoutes = require('./routes/admin');

const app = express();
app.use(express.json());

app.use(healthRoutes);
app.use(agentRoutes);
app.use(searchRoutes);
app.use(cartRoutes);
app.use(adminRoutes);

app.use((err, req, res, next) => {
  // eslint-disable-next-line no-unused-vars
  void next;
  console.error(err);
  res.status(err.statusCode || 500).json({ error: err.message });
});

let server;

async function main() {
  await browserManager.start();
  server = app.listen(config.port, () => {
    console.log(`rewe-service listening on :${config.port}`);
  });

  // Best-effort so the first real request doesn't pay the login cost; failures just
  // leave loginState as "blocked" until a request or /admin/login/retry tries again.
  browserManager.ensureLoggedIn().catch((err) => {
    console.error('Initial login attempt failed:', err.message);
  });
}

async function shutdown() {
  if (server) server.close();
  await browserManager.stop();
  process.exit(0);
}

process.on('SIGTERM', shutdown);
process.on('SIGINT', shutdown);

main().catch((err) => {
  console.error('Failed to start rewe-service:', err);
  process.exit(1);
});
