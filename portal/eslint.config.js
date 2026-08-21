// C-01: ESLint flat config (ESLint 10) para el portal.
// Reglas recomendadas de typescript-eslint (sin type-aware, rápido),
// hooks de React como errores y refresh como aviso. Estilo intencionalmente
// mínimo: el formateo lo gobierna Prettier (`npm run format:check`).
import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  { ignores: ['dist', 'coverage', 'node_modules'] },
  {
    files: ['**/*.{ts,tsx}'],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: {
      ecmaVersion: 2022,
      globals: { ...globals.browser, ...globals.es2022 },
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // El portal carga datos al montar (fetch → setState) por diseño
      // (sin router ni librería de estado; ver C-04). La regla nueva de
      // React 19 contra setState en effects choca con ese patrón hasta
      // la refactorización de carga de datos; se deja como aviso.
      'react-hooks/set-state-in-effect': 'warn',
      'react-refresh/only-export-components': 'warn',
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
    },
  },
  {
    // Los ficheros de test usan APIs de vitest/jsdom: sin reglas extra.
    files: ['**/*.test.{ts,tsx}', 'src/test/**'],
    languageOptions: {
      globals: { ...globals.browser, ...globals.node },
    },
  },
)
