'use strict';

const express = require('express');
const { runWithSession } = require('../session');
const { addToCart } = require('../reweClient');

const router = express.Router();

router.post('/cart/add', async (req, res, next) => {
  const { productId, quantity } = req.body || {};
  if (!productId || typeof productId !== 'string') {
    return res.status(400).json({ error: 'productId is required' });
  }
  const cappedQuantity = Math.min(Math.max(parseInt(quantity, 10) || 1, 1), 50);

  try {
    const result = await runWithSession((page) => addToCart(page, productId, cappedQuantity));
    res.json(result);
  } catch (err) {
    next(err);
  }
});

module.exports = router;
