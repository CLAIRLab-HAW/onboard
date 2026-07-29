#!/usr/bin/env node
/*
 * Minimal unit-test runner for the fork-specific logic.
 *
 * The upstream `make check` boots a Cockpit VM and drives a browser, which is
 * far too heavy for "does the panel still read the keys the publisher sends".
 * This bundles each *.test.ts with the esbuild that is already a dependency and
 * runs it in node; a test fails by throwing. No new dependencies, no framework.
 *
 *   node test/unit/run.js            # all tests
 *   node test/unit/run.js contract   # only matching names
 *   make check-unit
 *
 * Deliberately outside tsconfig.json/eslint: that config targets the browser
 * bundle (dom lib, no node types), and widening it for test tooling would only
 * add merge friction with upstream. These files are checked by running them.
 */
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import process from 'node:process';

const useWasm = os.arch() !== 'x64';
const esbuild = (await import(useWasm ? 'esbuild-wasm' : 'esbuild')).default;

const dir = path.dirname(new URL(import.meta.url).pathname);
const filter = process.argv[2];
const tests = fs.readdirSync(dir).filter(f => f.endsWith('.test.ts'))
        .filter(f => !filter || f.includes(filter))
        .sort();

if (tests.length === 0) {
    console.error(filter ? `no tests matching "${filter}"` : 'no tests found');
    process.exit(1);
}

const outdir = fs.mkdtempSync(path.join(os.tmpdir(), 'cockpit-ros2-unit-'));
let failed = 0;

for (const test of tests) {
    const out = path.join(outdir, test.replace(/\.ts$/, '.cjs'));
    try {
        await esbuild.build({
            entryPoints: [path.join(dir, test)],
            bundle: true,
            platform: 'node',
            format: 'cjs',
            jsx: 'automatic',
            loader: { '.json': 'json' },
            // `cockpit` is provided by the Cockpit bridge at runtime; in node it
            // is stubbed down to the two calls this code path uses.
            alias: { cockpit: path.join(dir, 'cockpit-stub.ts') },
            outfile: out,
            logLevel: 'error',
        });
        execFileSync(process.execPath, [out], { stdio: 'inherit' });
    } catch (error) {
        if (!error.stdout && !error.status) console.error(error.message);
        console.error(`FAILED: ${test}`);
        failed++;
    }
}

fs.rmSync(outdir, { recursive: true, force: true });
console.log(failed === 0 ? `\n${tests.length} test file(s) passed.` : `\n${failed}/${tests.length} test file(s) FAILED.`);
process.exit(failed === 0 ? 0 : 1);
