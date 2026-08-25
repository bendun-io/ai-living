'use strict';

// Mirrors the AGENT_TOOL_DEFINITIONS / GET /agent/tool-definitions convention used by
// utils-lists, so this service is discoverable by the same generic REST-tool adapter.
const TOOL_DEFINITIONS = [
  {
    name: 'rewe_search',
    description: 'Search REWE.de for products by keyword and return matching results with price and id.',
    endpoint: '/search',
    method: 'POST',
    input_schema: {
      type: 'object',
      properties: {
        query: { type: 'string', description: 'Search keyword, e.g. "milk" or "Vollmilch".' },
        limit: { type: 'integer', minimum: 1, maximum: 50, default: 20 },
      },
      required: ['query'],
    },
  },
  {
    name: 'rewe_add_to_cart',
    description: 'Add a product to the REWE.de shopping cart, using the id or url returned by rewe_search.',
    endpoint: '/cart/add',
    method: 'POST',
    input_schema: {
      type: 'object',
      properties: {
        productId: { type: 'string', description: 'Product id or url returned by rewe_search.' },
        quantity: { type: 'integer', minimum: 1, default: 1 },
      },
      required: ['productId'],
    },
  },
];

module.exports = { TOOL_DEFINITIONS };
