'use strict';

const browserManager = require('./browserManager');
const queue = require('./queue');

// Shared by every route that touches the site: queues the work (one request at a time)
// and guarantees a logged-in page before the task runs, without the agent ever having
// to call a login endpoint itself.
function runWithSession(task) {
  return queue.run(async () => {
    const page = await browserManager.getPage();
    const loggedIn = await browserManager.ensureLoggedIn();
    if (!loggedIn) {
      const err = new Error(`Not logged in to REWE.de: ${browserManager.status().lastLoginError}`);
      err.statusCode = 503;
      throw err;
    }
    return task(page);
  });
}

module.exports = { runWithSession };
