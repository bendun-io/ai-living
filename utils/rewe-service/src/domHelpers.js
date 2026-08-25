'use strict';

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function findHandle(page, selectors) {
  for (const selector of selectors) {
    const handle = await page.$(selector);
    if (handle) return handle;
  }
  return null;
}

async function clickFirstMatch(page, selectors) {
  const handle = await findHandle(page, selectors);
  if (!handle) return false;
  await handle.click();
  return true;
}

// Works on either a Page or an ElementHandle scope. Deliberately avoids
// scope.evaluateHandle(fn, ...args): Puppeteer auto-prepends the element itself as the
// first argument only when scope is an ElementHandle (not when it's a Page), so a single
// shared pageFunction signature can't handle both cases consistently.
async function clickByText(scope, texts, tags = ['button', 'a']) {
  const selector = tags.join(',');
  const handles = await scope.$$(selector);
  for (const handle of handles) {
    const text = await handle.evaluate((el) => (el.textContent || '').trim());
    if (texts.some((candidate) => text.includes(candidate))) {
      await handle.click();
      return true;
    }
  }
  return false;
}

async function typeInFirstMatch(page, selectors, text) {
  const handle = await findHandle(page, selectors);
  if (!handle) return false;
  await handle.click({ clickCount: 3 });
  await handle.type(text, { delay: 20 });
  return true;
}

module.exports = { sleep, findHandle, clickFirstMatch, clickByText, typeInFirstMatch };
