import { readFileSync } from 'node:fs';

// Release/install staging writes the same manifest beside all components.
let manifest;
try { manifest = JSON.parse(readFileSync(new URL('../build-info.json', import.meta.url), 'utf8')); } catch { /* An unstaged checkout is visibly development-only. */ }
export const BUILD_VERSION = manifest?.version ?? '1.0.0';
export const PROTOCOL_VERSION = manifest?.protocol_version ?? 2;
export const BUILD_ID = manifest?.build_id ?? 'development-unverified';
export const BUILD_INFO = { version: BUILD_VERSION, protocol_version: PROTOCOL_VERSION, build_id: BUILD_ID,
  ...(manifest ?? {}) };
