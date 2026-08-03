// eslint.config.js — flat config for JoyAI webui static assets.
//
// Phase 0 scope: lint ONLY the 7 externalized IIFE-to-window modules under
// src/joy_interaction_webui/static/. The ~5600 lines of inline JS inside
// index.html are intentionally out of scope (see lint-review-and-expansion
// report, Phase 3). Vendored virtualenv files (.venv) are excluded.
import js from '@eslint/js';

export default [
  {
    files: ['src/joy_interaction_webui/static/**/*.js'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'script',
      globals: {
        window: 'writable',
        document: 'readonly',
        console: 'readonly',
        performance: 'readonly',
        navigator: 'readonly',
        WebSocket: 'readonly',
        RTCPeerConnection: 'readonly',
        RTCSessionDescription: 'readonly',
        MediaStream: 'readonly',
        MediaRecorder: 'readonly',
        ImageCapture: 'readonly',
        Node: 'readonly',
        DOMParser: 'readonly',
        HTMLElement: 'readonly',
        HTMLVideoElement: 'readonly',
        HTMLCanvasElement: 'readonly',
        AudioContext: 'readonly',
        URL: 'readonly',
        Blob: 'readonly',
        marked: 'readonly',
        DOMPurify: 'readonly',
        katex: 'readonly',
        fetch: 'readonly',
        location: 'readonly',
        alert: 'readonly',
        confirm: 'readonly',
        setTimeout: 'readonly',
        setInterval: 'readonly',
        clearInterval: 'readonly',
        clearTimeout: 'readonly',
        requestAnimationFrame: 'readonly',
        cancelAnimationFrame: 'readonly',
      },
    },
    rules: {
      // Baseline "real bug" rules.
      'no-undef': 'error',
      'no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_', caughtErrorsIgnorePattern: '^_' }],
      // Style rules that the 7 files already mostly follow.
      'strict': ['error', 'global'], // require 'use strict'
      'quotes': ['error', 'single', { avoidEscape: true }],
      'semi': ['error', 'always'],
      // UI files legitimately log to the console.
      'no-console': 'off',
      'no-empty': ['error', { allowEmptyCatch: true }],
    },
  },
  {
    ignores: [
      '**/.venv/**',
      'node_modules/**',
      'dist/**',
      '**/__pycache__/**',
      'eslint.config.js',
    ],
  },
];
