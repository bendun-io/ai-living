'use strict';

const selectors = require('./selectors');
const { sleep, findHandle, clickFirstMatch, clickByText, typeInFirstMatch } = require('./domHelpers');

async function dismissCookieBanner(page) {
  try {
    const clicked =
      (await clickFirstMatch(page, selectors.cookieConsent.acceptButtonSelectors)) ||
      (await clickByText(page, selectors.cookieConsent.acceptButtonTextCandidates));
    if (clicked) {
      await sleep(300);
    }
  } catch {
    // Banner absent or already dismissed; not fatal either way.
  }
}

async function isLoggedIn(page) {
  const handle = await findHandle(page, selectors.login.loggedInIndicatorSelectors);
  return Boolean(handle);
}

async function login(page, email, password) {
  if (!email || !password) {
    throw new Error('REWE_EMAIL / REWE_PASSWORD are not configured.');
  }

  await page.goto(selectors.baseUrl, { waitUntil: 'domcontentloaded' });
  await dismissCookieBanner(page);

  const openedLogin =
    (await clickFirstMatch(page, selectors.login.loginLinkSelectors)) ||
    (await clickByText(page, selectors.login.loginLinkTextCandidates));
  if (!openedLogin) {
    throw new Error('Could not find the login link on shop.rewe.de.');
  }
  await page.waitForNavigation({ waitUntil: 'domcontentloaded' }).catch(() => {});

  const emailFilled = await typeInFirstMatch(page, selectors.login.emailInputSelectors, email);
  const passwordFilled = await typeInFirstMatch(page, selectors.login.passwordInputSelectors, password);
  if (!emailFilled || !passwordFilled) {
    throw new Error('Could not find the email/password fields on the login form.');
  }

  const submitted =
    (await clickFirstMatch(page, selectors.login.submitButtonSelectors)) ||
    (await clickByText(page, selectors.login.submitButtonTextCandidates));
  if (!submitted) {
    throw new Error('Could not find the login submit button.');
  }

  await page.waitForNavigation({ waitUntil: 'networkidle2' }).catch(() => {});
}

async function searchProducts(page, query, limit) {
  await dismissCookieBanner(page);

  const typed = await typeInFirstMatch(page, selectors.search.searchInputSelectors, query);
  if (!typed) {
    throw new Error('Could not find the search input on shop.rewe.de.');
  }
  await page.keyboard.press('Enter');
  await page
    .waitForSelector(selectors.search.resultTileSelectors.join(','), { timeout: 10000 })
    .catch(() => {});

  const products = await page.$$eval(
    selectors.search.resultTileSelectors.join(','),
    (tiles, nameSelector, priceSelector, linkSelector) =>
      tiles.map((tile) => {
        const nameEl = tile.querySelector(nameSelector);
        const priceEl = tile.querySelector(priceSelector);
        const linkEl = tile.querySelector(linkSelector);
        return {
          id: tile.getAttribute('data-testid') || (linkEl ? linkEl.getAttribute('href') : null),
          name: nameEl ? nameEl.textContent.trim() : null,
          price: priceEl ? priceEl.textContent.trim() : null,
          url: linkEl ? linkEl.href : null,
        };
      }),
    selectors.search.tileNameSelectors.join(','),
    selectors.search.tilePriceSelectors.join(','),
    selectors.search.tileLinkSelector
  );

  return products.filter((product) => product.name).slice(0, limit);
}

async function clickAddToCart(scope) {
  return (
    (await clickFirstMatch(scope, selectors.search.addToCartButtonSelectors)) ||
    (await clickByText(scope, selectors.search.addToCartButtonTextCandidates))
  );
}

async function addToCart(page, productRef, quantity) {
  const isUrl = /^https?:\/\//.test(productRef);

  if (isUrl) {
    await page.goto(productRef, { waitUntil: 'domcontentloaded' });
    await dismissCookieBanner(page);
    for (let i = 0; i < quantity; i += 1) {
      const clicked = await clickAddToCart(page);
      if (!clicked) {
        throw new Error('Could not find an "add to cart" button on the product page.');
      }
      await sleep(300);
    }
    return { added: true, quantity, productRef };
  }

  const tiles = await page.$$(selectors.search.resultTileSelectors.join(','));
  for (const tile of tiles) {
    const id = await tile.evaluate((el) => el.getAttribute('data-testid'));
    if (id !== productRef) continue;

    for (let i = 0; i < quantity; i += 1) {
      const clicked = await clickAddToCart(tile);
      if (!clicked) {
        throw new Error('Could not find an "add to cart" button on the matched product tile.');
      }
      await sleep(300);
    }
    return { added: true, quantity, productRef };
  }

  throw new Error(
    `Product "${productRef}" was not found among the current search results. Re-run rewe_search first, or pass a product URL instead.`
  );
}

module.exports = { dismissCookieBanner, isLoggedIn, login, searchProducts, addToCart };
