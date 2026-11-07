import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// Read Git objects, not working-tree replacements. Never print matching values.
const git = (...args) =>
  execFileSync('git', args, { maxBuffer: 32 * 1024 * 1024, windowsHide: true });
const root = git('rev-parse', '--show-toplevel').toString().trim();
const tracked = process.argv.includes('--tracked');
const files = (
  tracked
    ? git('ls-tree', '-r', '--name-only', '-z', 'HEAD')
    : git('diff', '--cached', '--name-only', '--diff-filter=ACMR', '-z')
)
  .toString()
  .split('\0')
  .filter(Boolean);
const knownSecrets = new Set();
for (const name of ['.env', '.env.local', '.env.example.private-backup']) {
  try {
    for (const line of readFileSync(resolve(root, name), 'utf8').split(/\r?\n/)) {
      const match = line.match(/^\s*(?:export\s+)?([A-Z_][A-Z0-9_]*)\s*=\s*(.*?)\s*$/);
      if (!match || !/(?:KEY|TOKEN|SECRET|PASSWORD)/.test(match[1])) continue;
      const value = match[2].replace(/^(['"])(.*)\1$/, '$2');
      if (value.length >= 12) knownSecrets.add(value);
    }
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }
}
const patterns = [
  ['API key', /\bsk-(?:proj-|ant-api\d+-)?[A-Za-z0-9_-]{20,}\b/g],
  ['GitHub token', /\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b/g],
  ['AWS access key', /\b(?:AKIA|ASIA)[A-Z0-9]{16}\b/g],
  ['private key', /-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----/g],
  ['credential in URL', /[a-z][a-z0-9+.-]*:\/\/[^\s/:@]+:[^\s/@]+@/gi],
  ['hardcoded authorization', /\b(?:Bearer|Basic)\s+[A-Za-z0-9+/_=-]{24,}/g],
];
const failures = [];
for (const path of files) {
  const example = /(?:^|\/)\.env(?:\.[^/]+)?\.example$/.test(path);
  if (
    (!example && /(?:^|\/)\.env(?:\.|$)/.test(path)) ||
    /(?:^|\/)(?:\.aws|\.ssh|\.codex|\.agents|artifacts|uploads|logs|results)(?:\/|$)/.test(path) ||
    /(?:\.(?:pem|key|p12|pfx)$|(?:^|\/)(?:credentials|secrets)\.json$|(?:^|\/)\.(?:netrc|npmrc)$)/i.test(
      path,
    )
  ) {
    failures.push(`${path}: private configuration or generated local data must not be committed`);
    continue;
  }
  const content = git('show', tracked ? `HEAD:${path}` : `:${path}`).toString('utf8');
  const lines = content.split(/\r?\n/);
  for (let index = 0; index < lines.length; index++) {
    const line = lines[index];
    if (example && /^\s*(?:export\s+)?[A-Z_][A-Z0-9_]*\s*=\s*\S/.test(line))
      failures.push(`${path}:${index + 1}: environment examples must contain empty values`);
    if ([...knownSecrets].some((secret) => line.includes(secret)))
      failures.push(`${path}:${index + 1}: matches a local credential value`);
    for (const [label, pattern] of patterns) {
      pattern.lastIndex = 0;
      for (const match of line.matchAll(pattern)) {
        // This exact zero-filled dummy is used to test the app's own rejection.
        if (path.startsWith('tests/') && /^sk-proj-TESTONLY0+$/.test(match[0])) continue;
        failures.push(`${path}:${index + 1}: possible ${label}`);
      }
    }
  }
}
if (failures.length) {
  console.error('Commit/push blocked. Remove private data from the Git snapshot:');
  for (const failure of [...new Set(failures)]) console.error(`- ${failure}`);
  process.exit(1);
}
console.log(
  `Secret check passed: ${files.length} ${tracked ? 'committed' : 'staged'} files. No matching values are displayed.`,
);
