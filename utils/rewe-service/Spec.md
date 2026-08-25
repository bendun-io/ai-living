# Specification

- The rewe service should be deployed in the same docker pattern as the others.
- It should offer endpoints for the AI agent to use.
- It should be based on a puppeteer headless browser.
- It should be capable of logging in into rewe.de
- It should be able to use the search on rewe.de
- It should be able to put a product in the shopping card on rewe.de
- The login should be done with credentials from the .env file.
- The login should not be needed to be triggered by the agent, but happen before anything is searched or put in the shopping card.
- The logged in session should be used accross different requests.
- The service should not process requests in parallel but only when one is finished, process the next one.