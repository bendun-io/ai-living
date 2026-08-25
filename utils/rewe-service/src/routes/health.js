'use strict';

const express = require('express');
const browserManager = require('../browserManager');
const queue = require('../queue');
const { TOOL_DEFINITIONS } = require('../tools');

const router = express.Router();

router.get('/health', (req, res) => {
  res.json({
    status: 'ok',
    service: 'utils-rewe',
    tools: TOOL_DEFINITIONS.map((tool) => tool.name),
    pendingRequests: queue.pending,
    ...browserManager.status(),
  });
});

module.exports = router;
