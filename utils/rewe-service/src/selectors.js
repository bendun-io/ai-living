'use strict';

// Best-effort selectors for shop.rewe.de. shop.rewe.de returns HTTP 403 to non-browser
// clients and gates its shop behind a cookie-consent banner and a real Chromium session,
// so these could not be verified against the live DOM from this environment. Treat every
// selector list below as a starting point: open the real site in a browser, inspect the
// current markup, and update the arrays here (each is tried in order, first match wins).
module.exports = {
  baseUrl: 'https://shop.rewe.de',

  cookieConsent: {
    acceptButtonSelectors: [
      '#uc-btn-accept-banner',
      'button[data-testid="uc-accept-all-button"]',
      'button[aria-label="Alles akzeptieren"]',
    ],
    acceptButtonTextCandidates: ['Alle akzeptieren', 'Alles akzeptieren', 'Akzeptieren'],
  },

  login: {
    loginLinkSelectors: ['a[href*="login"]', 'a[data-testid="header-login-link"]'],
    loginLinkTextCandidates: ['Anmelden', 'Login'],
    emailInputSelectors: ['input[name="email"]', 'input[type="email"]', '#email'],
    passwordInputSelectors: ['input[name="password"]', 'input[type="password"]', '#password'],
    submitButtonSelectors: ['button[type="submit"]'],
    submitButtonTextCandidates: ['Anmelden', 'Einloggen', 'Login'],
    loggedInIndicatorSelectors: [
      'a[href*="logout"]',
      '[data-testid="header-account-menu"]',
      '[data-testid="my-account-link"]',
    ],
  },

  search: {
    searchInputSelectors: [
      'input[type="search"]',
      'input[name="search"]',
      '[data-testid="search-input"]',
      'input[placeholder*="such" i]',
    ],
    resultTileSelectors: [
      '[data-testid*="ArticleTile"]',
      '[data-testid*="product-tile"]',
      'li[data-testid*="product"]',
      'article[data-testid]',
    ],
    tileNameSelectors: ['h2', 'h3', '[data-testid*="title"]', '[data-testid*="name"]'],
    tilePriceSelectors: ['[data-testid*="price"]', '.price'],
    tileLinkSelector: 'a[href]',
    addToCartButtonSelectors: [
      'button[data-testid*="add-to-cart"]',
      'button[aria-label*="Warenkorb"]',
    ],
    addToCartButtonTextCandidates: ['In den Warenkorb', 'Hinzufügen'],
  },
};
