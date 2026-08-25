'use strict';

const fs = require('fs');
const puppeteer = require('puppeteer');
const config = require('./config');
const { login, isLoggedIn } = require('./reweClient');

// Owns the single, long-lived Chromium instance and its login state. One browser/page
// persists across requests (userDataDir on disk too) so the logged-in session survives
// both individual requests and container restarts, per the spec.
class BrowserManager {
  constructor() {
    this.browser = null;
    this.page = null;
    this.loginState = 'unknown'; // unknown | loggingIn | loggedIn | blocked
    this.lastLoginError = null;
  }

  async start() {
    fs.mkdirSync(config.profileDir, { recursive: true });

    this.browser = await puppeteer.launch({
      headless: config.headless,
      executablePath: config.chromiumPath,
      userDataDir: config.profileDir,
      args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-dev-shm-usage',
        `--remote-debugging-port=${config.cdpPort}`,
        `--remote-debugging-address=${config.cdpHost}`,
      ],
    });

    const pages = await this.browser.pages();
    this.page = pages[0] || (await this.browser.newPage());
    this.page.setDefaultNavigationTimeout(config.navTimeoutMs);
    this.page.setDefaultTimeout(config.navTimeoutMs);
  }

  async stop() {
    if (this.browser) {
      await this.browser.close();
    }
  }

  async getPage() {
    if (!this.page || this.page.isClosed()) {
      this.page = await this.browser.newPage();
    }
    return this.page;
  }

  // Called before every search/cart request (never directly by the agent), so a logged-in
  // session is always in place by the time site interactions run.
  async ensureLoggedIn() {
    const page = await this.getPage();

    if (await isLoggedIn(page)) {
      this.loginState = 'loggedIn';
      this.lastLoginError = null;
      return true;
    }

    this.loginState = 'loggingIn';
    try {
      await login(page, config.email, config.password);
    } catch (err) {
      this.loginState = 'blocked';
      this.lastLoginError = err.message;
      return false;
    }

    if (await isLoggedIn(page)) {
      this.loginState = 'loggedIn';
      this.lastLoginError = null;
      return true;
    }

    this.loginState = 'blocked';
    this.lastLoginError =
      'Login attempt completed but the session does not look authenticated (a CAPTCHA likely needs solving manually).';
    return false;
  }

  status() {
    return {
      loginState: this.loginState,
      lastLoginError: this.lastLoginError,
      debugPort: config.cdpPort,
    };
  }
}

module.exports = new BrowserManager();
