import js from '@eslint/js'

export default [
  {
    ignores: [
      'node_modules/**',
      'dist/**',
      'src/**', // TypeScript sources are gated by `tsc --noEmit`; eslint runs on plain JS only
      'locale/**',
      'skills/**',
      'schedule/**',
      'docs/**',
      'examples/**',
      'kernel/.venv-dev/**',
      '.github/**',
    ],
  },
  js.configs.recommended,
  {
    files: ['**/*.js', '**/*.mjs', '**/*.cjs'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: {
        process: 'readonly',
        console: 'readonly',
        Buffer: 'readonly',
        __dirname: 'readonly',
        URL: 'readonly',
        setTimeout: 'readonly',
        clearTimeout: 'readonly',
      },
    },
    rules: {
      'no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      'no-undef': 'error',
    },
  },
]
