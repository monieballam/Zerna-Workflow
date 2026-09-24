#!/usr/bin/env node
/**
 * Generates the TypeScript schema types from the OpenAPI spec.
 *
 * Steps:
 *   1. Looks for openapi.json at the repo root (or OPENAPI_PATH env var).
 *   2. Runs openapi-typescript to emit src/generated/schema.ts.
 *   3. Writes src/generated/index.ts that re-exports the schema.
 *
 * Usage:
 *   node scripts/generate-client.mjs
 *   OPENAPI_PATH=./custom-spec.json node scripts/generate-client.mjs
 */

import { execSync } from 'child_process';
import { existsSync, mkdirSync, writeFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const pkgRoot = resolve(__dirname, '..');
const repoRoot = resolve(pkgRoot, '../..');

const openapiPath = process.env.OPENAPI_PATH ?? resolve(repoRoot, 'openapi.json');
const generatedDir = resolve(pkgRoot, 'src/generated');
const schemaOut = resolve(generatedDir, 'schema.ts');

if (!existsSync(openapiPath)) {
  console.error(
    `\nOpenAPI spec not found at: ${openapiPath}\n\n` +
      `Generate it first:\n` +
      `  cd ${repoRoot}\n` +
      `  uv run python -m apps.api.export_openapi --output openapi.json\n`
  );
  process.exit(1);
}

mkdirSync(generatedDir, { recursive: true });

console.log(`Generating TypeScript types from ${openapiPath} …`);
execSync(`npx openapi-typescript "${openapiPath}" -o "${schemaOut}"`, {
  stdio: 'inherit',
  cwd: pkgRoot,
});

// Write a barrel re-export so consumers can import from "@zerna/sdk/generated"
const barrel = `// Auto-generated — do not edit manually.
// Re-run \`pnpm --filter @zerna/sdk generate\` to refresh.
export type { paths, components, operations } from "./schema.js";
`;
writeFileSync(resolve(generatedDir, 'index.ts'), barrel);

console.log(`✓ Types written to ${schemaOut}`);
