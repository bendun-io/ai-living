'use strict';

function parseBool(value, fallback) {
  if (value === undefined || value === null || value === '') return fallback;
  return ['1', 'true', 'yes', 'on'].includes(String(value).trim().toLowerCase());
}

function parseInteger(value, fallback) {
  const parsed = parseInt(value, 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

module.exports = {
  port: parseInteger(process.env.REWE_SERVICE_PORT, 8020),
  email: process.env.REWE_EMAIL || '',
  password: process.env.REWE_PASSWORD || '',
  headless: parseBool(process.env.HEADLESS, true),
  profileDir: process.env.REWE_PROFILE_DIR || '/app/data/profile',
  chromiumPath: process.env.PUPPETEER_EXECUTABLE_PATH || undefined,
  cdpPort: parseInteger(process.env.CDP_PORT, 9222),
  cdpHost: process.env.CDP_HOST || '0.0.0.0',
  baseUrl: process.env.REWE_BASE_URL || 'https://shop.rewe.de',
  navTimeoutMs: parseInteger(process.env.REWE_NAV_TIMEOUT_MS, 30000),
};
