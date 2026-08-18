/**
 * Entry point: mount the router and the app shell.
 *
 * Routing is `BrowserRouter` because the backend serves an SPA fallback for
 * deep links (`app/static.py`), so `/chat/abc` is a real URL rather than a
 * hash. Written once by ticket 00.
 */
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';

import { App } from './App';

const container = document.getElementById('root');
if (!container) {
  throw new Error('index.html is missing its #root element');
}

createRoot(container).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
