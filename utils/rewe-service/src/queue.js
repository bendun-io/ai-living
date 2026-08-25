'use strict';

// Serializes work so the shared browser session never handles two requests at once,
// as required by the spec: process one request fully before starting the next.
class SerialQueue {
  constructor() {
    this._tail = Promise.resolve();
    this._pending = 0;
  }

  run(task) {
    this._pending += 1;
    const result = this._tail.then(() => task());
    // Note: .finally() here would return its own rejected promise when result rejects,
    // and nothing else observes that promise - an unhandled rejection that crashes the
    // process under Node's default behavior. Using the two-branch .then() instead means
    // every derived promise settles, so there's nothing left unhandled.
    const settled = result.then(
      () => undefined,
      () => undefined
    );
    this._tail = settled;
    settled.then(() => {
      this._pending -= 1;
    });
    return result;
  }

  get pending() {
    return this._pending;
  }
}

module.exports = new SerialQueue();
