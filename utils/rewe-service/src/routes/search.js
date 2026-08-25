'use strict';

const express = require('express');
const { runWithSession } = require('../session');
const { searchProducts } = require('../reweClient');

const router = express.Router();

router.post('/search', async (req, res, next) => {
  const { query, limit } = req.body || {};
  if (!query || typeof query !== 'string') {
    return res.status(400).json({ error: 'query is required' });
  }
  const cappedLimit = Math.min(Math.max(parseInt(limit, 10) || 20, 1), 50);

  try {
    const products = await runWithSession((page) => searchProducts(page, query, cappedLimit));
    res.json({ products, count: products.length });
  } catch (err) {
    next(err);
  }
});

module.exports = router;
