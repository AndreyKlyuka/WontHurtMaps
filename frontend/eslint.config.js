// @ts-check
const eslint = require('@eslint/js');
const tseslint = require('typescript-eslint');
const angular = require('@angular-eslint/eslint-plugin');
const angularTemplate = require('@angular-eslint/eslint-plugin-template');
const angularTemplateParser = require('@angular-eslint/template-parser');
const prettierConfig = require('eslint-config-prettier');
const prettierPlugin = require('eslint-plugin-prettier');

module.exports = tseslint.config(
  {
    ignores: ['dist/**', 'node_modules/**', '.angular/**'],
  },
  {
    // TypeScript source files
    files: ['**/*.ts'],
    extends: [eslint.configs.recommended, ...tseslint.configs.recommended],
    plugins: {
      '@angular-eslint': angular,
      prettier: prettierPlugin,
    },
    languageOptions: {
      parserOptions: {
        project: ['tsconfig.app.json', 'tsconfig.spec.json'],
        tsconfigRootDir: __dirname,
      },
    },
    rules: {
      ...angular.configs.recommended.rules,
      ...prettierConfig.rules,
      'prettier/prettier': 'error',
      // Allow both "app" (Angular default) and "whm" (WontHurtMaps) prefixes
      '@angular-eslint/directive-selector': [
        'error',
        { type: 'attribute', prefix: ['app', 'whm'], style: 'camelCase' },
      ],
      '@angular-eslint/component-selector': [
        'error',
        { type: 'element', prefix: ['app', 'whm'], style: 'kebab-case' },
      ],
    },
  },
  {
    // Angular HTML templates
    files: ['**/*.html'],
    plugins: {
      '@angular-eslint/template': angularTemplate,
      prettier: prettierPlugin,
    },
    languageOptions: {
      parser: angularTemplateParser,
    },
    rules: {
      ...angularTemplate.configs.recommended.rules,
      ...prettierConfig.rules,
      'prettier/prettier': ['error', { parser: 'angular' }],
    },
  },
);
