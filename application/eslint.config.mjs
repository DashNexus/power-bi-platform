/**
 * ESLint flat config for the application layer.
 *
 * `npm run lint` previously had no config file at all, so it dropped into
 * next lint's interactive setup prompt and `make lint` hung on this layer.
 *
 * eslint-config-next still ships in eslintrc format, so it is bridged through
 * FlatCompat rather than imported directly.
 */
import { dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { FlatCompat } from '@eslint/eslintrc'

const compat = new FlatCompat({ baseDirectory: dirname(fileURLToPath(import.meta.url)) })

export default [
  {
    ignores: [
      '.next/**',
      '.next-verify/**',
      'node_modules/**',
      'next-env.d.ts',
      'public/timelinejs/**',
    ],
  },

  ...compat.extends('next/core-web-vitals', 'next/typescript'),

  {
    rules: {
      // STYLE.md: React/Next → third-party → internal aliases (@/…) → relative.
      'import/order': [
        'warn',
        {
          groups: ['builtin', 'external', 'internal', 'parent', 'sibling', 'index'],
          pathGroups: [
            { pattern: 'react', group: 'builtin', position: 'before' },
            { pattern: 'next/**', group: 'builtin', position: 'before' },
            { pattern: '@/**', group: 'internal' },
          ],
          pathGroupsExcludedImportTypes: ['react', 'next/**'],
          'newlines-between': 'ignore',
        },
      ],
      // STYLE.md: named exports only for components; `Any` needs justification.
      '@typescript-eslint/no-explicit-any': 'warn',
      '@typescript-eslint/consistent-type-imports': ['warn', { prefer: 'type-imports' }],
      '@typescript-eslint/no-unused-vars': [
        'warn',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
    },
  },

  {
    // Tests deliberately cast partial mocks to library types.
    files: ['**/*.test.ts', '**/*.test.tsx', '**/__tests__/**'],
    rules: {
      '@typescript-eslint/no-explicit-any': 'off',
    },
  },
]
