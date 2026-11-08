import { useState } from 'react';
import { Check, Copy, Terminal } from 'lucide-react';

export default function ExportRunGuide() {
  const [platform, setPlatform] = useState<'windows' | 'unix'>(() =>
    /Win/i.test(navigator.platform) ? 'windows' : 'unix',
  );
  const [copied, setCopied] = useState('');
  const [feedback, setFeedback] = useState('');
  const windows = platform === 'windows';
  const prefix = windows ? '.\\knot.cmd' : 'sh knot.sh';
  const start = `${prefix} run --interactive`;
  const monitor = `${prefix} monitor`;

  async function copyCommand(command: string, name: string) {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(command);
      setFeedback(`${name} copied. Paste it into your terminal.`);
    } catch {
      setCopied('');
      setFeedback('Clipboard unavailable. Select the command and copy it manually.');
    }
  }

  function commandRow(command: string, name: string) {
    return (
      <div className="export-command">
        <code>{command}</code>
        <button
          type="button"
          className="export-copy"
          aria-label={`Copy ${name.toLowerCase()}`}
          onClick={() => void copyCommand(command, name)}
        >
          {copied === command ? <Check size={17} /> : <Copy size={17} />}
          {copied === command ? 'Copied' : 'Copy'}
        </button>
      </div>
    );
  }

  return (
    <section className="export-run-guide" aria-labelledby="export-run-title">
      <h4 id="export-run-title">
        <Terminal size={22} /> Run on your computer
      </h4>
      <div className="export-platforms" role="group" aria-label="Terminal platform">
        {(['windows', 'unix'] as const).map((value) => (
          <button
            key={value}
            type="button"
            aria-pressed={platform === value}
            onClick={() => {
              setPlatform(value);
              setCopied('');
              setFeedback('');
            }}
          >
            {value === 'windows' ? 'Windows · PowerShell' : 'macOS / Linux'}
          </button>
        ))}
      </div>
      <ol className="export-steps">
        <li>
          <span>1</span>
          <div>
            <strong>Extract the ZIP and open a terminal</strong>
            <p>
              {windows
                ? 'Extract all files. Open the extracted folder in File Explorer, right-click its background and choose Open in Terminal. Use a PowerShell tab.'
                : 'Extract all files. Open Terminal, type cd followed by a space, drag the extracted folder into the window, then press Enter.'}
            </p>
            <p>Use the folder containing knot.py. Add any starting project code to workspace/.</p>
          </div>
        </li>
        <li>
          <span>2</span>
          <div>
            <strong>Start and assign the canvas tasks</strong>
            {commandRow(start, 'Start command')}
            <p>
              KNOT launches your selected assistant for each role. Independent tasks run together;
              connected tasks wait for their inputs. The live dashboard opens automatically.
            </p>
            <p>Keep this terminal open. Approve or reject here when a Human Review task pauses.</p>
          </div>
        </li>
        <li>
          <span>3</span>
          <div>
            <strong>Watch all projects in another terminal</strong>
            <p>Open a second terminal in the same folder, then run:</p>
            {commandRow(monitor, 'Monitor command')}
            <p>
              This only watches progress. It does not start another run. Use ↑/↓ to select tasks,
              Tab to switch projects, and q to close the dashboard while work continues.
            </p>
          </div>
        </li>
      </ol>
      <p className="export-guide-result">
        After required reviews, find the delivered code in <code>results/project/</code>. Ctrl+C in
        the running terminal stops its agents.
      </p>
      <p className="export-guide-help">
        To review costs, open Costs &amp; split and import <code>logs/usage-report.json</code>
        from the extracted workspace after running. Confirm billed amounts before sharing a
        settlement.
      </p>
      <p className="export-guide-help">
        Needs Python 3.10+ and your selected assistant installed and signed in. If you use Conda,
        activate your Python environment before running these commands. Full instructions are in
        README.md and START-HERE.md inside the ZIP.
      </p>
      <p className="export-copy-feedback" role="status" aria-live="polite">
        {feedback}
      </p>
    </section>
  );
}
