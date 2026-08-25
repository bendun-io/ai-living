'use strict';

const express = require('express');
const { TOOL_DEFINITIONS } = require('../tools');

const router = express.Router();

router.get('/agent/tool-definitions', (req, res) => {
  res.json({ tools: TOOL_DEFINITIONS });
});

module.exports = router;
