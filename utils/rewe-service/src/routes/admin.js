'use strict';

const express = require('express');
const config = require('../config');
const browserManager = require('../browserManager');
const queue = require('../queue');

const router = express.Router();

// Operational endpoints for a human operator, not advertised via /agent/tool-definitions.
router.get('/admin/debug-info', (req, res) => {
  res.json({
    ...browserManager.status(),
    hint: `If loginState is "blocked" (likely a CAPTCHA), point a desktop Chrome at http://<host running this container>:${config.cdpPort} to see and control the live REWE session, solve it manually, then POST /admin/login/retry. Requires the debug port to be published in docker-compose.`,
  });
});

router.post('/admin/login/retry', async (req, res, next) => {
  try {
    const loggedIn = await queue.run(() => browserManager.ensureLoggedIn());
    res.json({ loggedIn, ...browserManager.status() });
  } catch (err) {
    next(err);
  }
});

module.exports = router;
