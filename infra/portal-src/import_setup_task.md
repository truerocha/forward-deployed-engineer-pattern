# Code Factory Integration Guide: `import_setup_task.md`

This document outlines the steps required to smoothly migrate the **Code Factory** frontend architecture and it's Engineering Amplification patterns into your existing enterprise solution.

## 1. Dependency Installation
Ensure the following core libraries are installed in your target project:

```bash
npm install i18next react-i18next lucide-react motion dompurify
```

## 2. Localization (i18n) Setup
The solution supports **en-US**, **pt-BR**, and **es** (Spanish Pilot).

1.  Copy `src/i18n.ts` to your project's source directory.
2.  Import it in your entry point file (`main.tsx` or `index.tsx`):
    ```typescript
    import './i18n';
    ```

## 3. Styling & Accessibility
The UI uses a high-contrast theme system optimized for WCAG accessibility.

1.  **Tailwind Configuration**: Ensure your `index.css` includes the CSS variables for `--bg-main`, `--bg-card`, `--text-main`, and `--text-secondary`.
2.  **Focus States**: Implement the global focus-visible ring for keyboard navigation:
    ```css
    *:focus-visible {
      @apply outline-2 outline-offset-2 outline-aws-orange;
    }
    ```

## 4. Component Migration Path
When moving components, prioritize them in the following order:

1.  **Services**: Migrate `src/services/factoryService.ts` first (the core logic).
2.  **Shared Components**: `MetricsCard.tsx`, `ComponentHealthCard.tsx`.
3.  **Core Views**: `Terminal.tsx` (Reasoning Engine) and `CodePreview.tsx` (Orchestration Hub).

## 5. Accessibility (POUR) Check
Every component includes specific accessibility markers that must be preserved:
*   **Skip Links**: Use the "Skip to main content" anchor in the root component.
*   **Aria Labels**: All buttons and interactive inputs must retain their `aria-label` linked to the translation keys.
*   **Role Mapping**: Use `role="navigation"` for sidebars and `role="log"` for streaming terminals.

## 6. Language Toggle Implementation
The sidebar implementation uses a cyclic language selector. When importing the `App.tsx` logic, ensure the toggle logic supports the full array of supported locals:
```typescript
const langs = ['en-US', 'pt-BR', 'es'];
// Logic to rotate via i18n.changeLanguage()
```
