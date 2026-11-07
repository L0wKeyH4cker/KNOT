import { spawn, spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const candidates = [
  ...(process.env.PYTHON ? [[process.env.PYTHON]] : []),
  ['python3'],
  ['python'],
  ['py', '-3'],
  [join(homedir(), 'miniconda3', process.platform === 'win32' ? 'python.exe' : 'bin/python')],
  [join(homedir(), 'anaconda3', process.platform === 'win32' ? 'python.exe' : 'bin/python')],
];
const probe =
  'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ required"; print(sys.executable)';
const python = candidates.find(([command, ...args]) => {
  const result = spawnSync(command, [...args, '-c', probe], {
    encoding: 'utf8',
    timeout: 5000,
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  return !result.error && result.status === 0;
});
if (!python) {
  console.error(
    'KNOT needs Python 3.10+. Install Python, or set PYTHON to your python executable path.',
  );
  process.exit(1);
}
if (process.argv.includes('--check-python')) {
  const result = spawnSync(python[0], [...python.slice(1), '-c', probe], {
    encoding: 'utf8',
    windowsHide: true,
  });
  console.log(result.stdout.trim());
  process.exit(result.status ?? 1);
}
const vite = join(root, 'node_modules', 'vite', 'bin', 'vite.js');
if (!existsSync(vite)) {
  console.error('Frontend dependencies are missing. Run npm install first.');
  process.exit(1);
}
const children = [];
let stopping = false;
function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  for (const child of children) {
    if (child.exitCode === null) child.kill('SIGTERM');
  }
  setTimeout(() => process.exit(code), 300).unref();
}
function launch(command, args) {
  const child = spawn(command, args, { cwd: root, stdio: 'inherit', windowsHide: true });
  children.push(child);
  child.on('error', (error) => {
    console.error(`Could not launch ${command}: ${error.message}`);
    stop(1);
  });
  child.on('exit', (code, signal) => {
    if (!stopping) stop(signal ? 1 : (code ?? 1));
  });
}
console.log('KNOT · editor http://127.0.0.1:5173 · API http://127.0.0.1:8000');
launch(python[0], [...python.slice(1), 'server.py', '--port', '8000']);
launch(process.execPath, [vite, '--host', '127.0.0.1', '--port', '5173', '--strictPort']);
process.on('SIGINT', () => stop(0));
process.on('SIGTERM', () => stop(0));
