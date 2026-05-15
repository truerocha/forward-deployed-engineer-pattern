import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.tsx';
import './index.css';
import './i18n';

// Apply dark mode class before render (prevents FOUC)
const storedTheme = localStorage.getItem('fde-theme');
if (storedTheme === 'dark' || (!storedTheme && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
  document.body.classList.add('awsui-dark-mode');
}

// Error boundary for production debugging
const root = document.getElementById('root')!;
try {
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
} catch (e: any) {
  root.innerHTML = `<pre style="color:red;padding:20px;font-size:14px;">RENDER ERROR:\n${e?.message}\n${e?.stack}</pre>`;
}
