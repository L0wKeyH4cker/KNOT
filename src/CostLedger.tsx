import { useEffect, useMemo, useRef, useState } from 'react';
import { Download, FileUp, Plus, ReceiptText, Trash2, X } from 'lucide-react';
import { Field } from './Inspector';
import type { Workflow } from './model';
import { isProjectDeleted, projectBillingKey } from './project-storage';
import {
  addSharedExpense,
  clearConfirmation,
  confirmEntry,
  emptyBillingLedger,
  exportBillingLedger,
  ledgerEntriesCsv,
  mergeUsageReport,
  parseBillingLedger,
  parseUsageReport,
  removeSharedExpense,
  settlementCsv,
  summarizeBilling,
} from './billing';
import type { BillingLedger, Currency, UsageEntry } from './billing';
import './billing.css';

const currencies: Currency[] = ['USD', 'CNY', 'EUR', 'GBP'];
const storageKey = projectBillingKey;
const message = (failure: unknown) =>
  failure instanceof Error ? failure.message : 'Could not update this ledger.';
const tokens = (value: number | null) => (value === null ? 'Unknown' : value.toLocaleString());
const money = (amount: string, currency: string) => `${currency} ${amount}`;

function download(text: string, filename: string, type: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function load(id: string) {
  let raw: string | null = null;
  try {
    if (isProjectDeleted(localStorage, id))
      return {
        ledger: emptyBillingLedger(id),
        raw,
        error: 'This project was deleted. Its ledger cannot be saved.',
        corrupt: false,
        deleted: true,
      };
    raw = localStorage.getItem(storageKey(id));
    return {
      ledger: raw ? parseBillingLedger(JSON.parse(raw), id) : emptyBillingLedger(id),
      raw,
      error: '',
      corrupt: false,
      deleted: false,
    };
  } catch {
    return {
      ledger: emptyBillingLedger(id),
      raw,
      error:
        raw === null
          ? 'Could not read saved costs. Changes can be exported, but may not persist on this device.'
          : 'The saved ledger could not be read. Its original data has been kept. Import a valid ledger or report to recover it.',
      corrupt: raw !== null,
      deleted: false,
    };
  }
}

function CurrencySelect({
  value,
  onChange,
}: {
  value: Currency;
  onChange: (value: Currency) => void;
}) {
  return (
    <select value={value} onChange={(event) => onChange(event.target.value as Currency)}>
      {currencies.map((currency) => (
        <option key={currency}>{currency}</option>
      ))}
    </select>
  );
}

function CostWorkspace({ wf }: { wf: Workflow }) {
  const id = wf.project.id;
  const [initial] = useState(() => load(id));
  const [ledger, setLedger] = useState(initial.ledger);
  const ledgerRef = useRef(ledger);
  const baseline = useRef(initial.raw);
  const dirty = useRef(false);
  const corruptRef = useRef(initial.corrupt);
  const [corrupt, setCorrupt] = useState(initial.corrupt);
  const [deleted, setDeleted] = useState(initial.deleted);
  const [storageError, setStorageError] = useState(initial.error);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [pendingImport, setPendingImport] = useState<BillingLedger | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [editorOpenCount, setEditorOpenCount] = useState(0);
  const costEditor = useRef<HTMLFormElement>(null);
  const costAmountInput = useRef<HTMLInputElement>(null);
  const sharedEditor = useRef<HTMLFormElement>(null);
  const sharedDescriptionInput = useRef<HTMLInputElement>(null);
  const [amount, setAmount] = useState('');
  const [currency, setCurrency] = useState<Currency>('USD');
  const [source, setSource] = useState('');
  const [allocation, setAllocation] = useState<'owner' | 'shared'>('owner');
  const [costParticipants, setCostParticipants] = useState<string[]>([]);
  const [pendingRemoval, setPendingRemoval] = useState<{
    kind: 'confirmation' | 'shared';
    id: string;
    label: string;
  } | null>(null);
  const [sharedOpen, setSharedOpen] = useState(false);
  const [sharedDescription, setSharedDescription] = useState('');
  const [sharedAmount, setSharedAmount] = useState('');
  const [sharedCurrency, setSharedCurrency] = useState<Currency>('USD');
  const [sharedSource, setSharedSource] = useState('');
  const [participants, setParticipants] = useState<string[]>([]);
  const reportInput = useRef<HTMLInputElement>(null);
  const ledgerInput = useRef<HTMLInputElement>(null);
  const summary = useMemo(() => summarizeBilling(ledger), [ledger]);
  const people = useMemo(() => {
    const names = new Map<string, string>();
    for (const member of wf.project.members) names.set(member.id, member.name);
    for (const entry of ledger.entries)
      if (!names.has(entry.owner_id)) names.set(entry.owner_id, entry.owner_name);
    for (const confirmation of ledger.confirmed)
      for (const member of confirmation.participants)
        if (!names.has(member.id)) names.set(member.id, member.name);
    for (const expense of ledger.shared)
      for (const member of expense.participants)
        if (!names.has(member.id)) names.set(member.id, member.name);
    return [...names].map(([memberId, name]) => ({ id: memberId, name }));
  }, [wf.project.members, ledger]);
  const confirmed = useMemo(
    () => new Map(ledger.confirmed.map((entry) => [entry.entry_id, entry])),
    [ledger],
  );
  const active = ledger.entries.find((entry) => entry.id === editing);
  const totals = (values: Partial<Record<Currency, string>>) => {
    const rows = Object.entries(values);
    return rows.length ? rows.map(([unit, value]) => money(value!, unit)).join(' · ') : '—';
  };

  useEffect(() => {
    if (!editing) return;
    costEditor.current?.scrollIntoView({ block: 'center' });
    costAmountInput.current?.focus({ preventScroll: true });
  }, [editing, editorOpenCount]);

  useEffect(() => {
    if (!sharedOpen) return;
    sharedEditor.current?.scrollIntoView({ block: 'center' });
    sharedDescriptionInput.current?.focus({ preventScroll: true });
  }, [sharedOpen]);

  function persist(next: BillingLedger, recovery = false) {
    ledgerRef.current = next;
    setLedger(next);
    dirty.current = true;
    try {
      if (isProjectDeleted(localStorage, id)) {
        setDeleted(true);
        throw Error('This project was deleted. Export your ledger to keep this copy.');
      }
      if (corruptRef.current && !recovery)
        throw Error(
          'Saved data needs recovery before it can be replaced. Export your current ledger to keep your changes.',
        );
      if (localStorage.getItem(storageKey(id)) !== baseline.current)
        throw Error(
          'The saved ledger changed in another tab. Your edits are kept here. Export them before reloading saved data.',
        );
      const raw = exportBillingLedger(next);
      localStorage.setItem(storageKey(id), raw);
      baseline.current = raw;
      dirty.current = false;
      corruptRef.current = false;
      setCorrupt(false);
      setStorageError('');
    } catch (failure) {
      setStorageError(`${message(failure)} Changes remain available in this page for export.`);
    }
  }

  function mutate(update: (current: BillingLedger) => BillingLedger, success: string) {
    setError('');
    setNotice('');
    if (deleted) {
      setError('This project was deleted. Export this ledger to keep a copy.');
      return false;
    }
    try {
      persist(update(ledgerRef.current));
      setNotice(success);
      return true;
    } catch (failure) {
      setError(message(failure));
      return false;
    }
  }

  useEffect(() => {
    const sync = (event: StorageEvent) => {
      if (event.storageArea !== localStorage) return;
      if (
        event.key !== storageKey(id) &&
        event.key !== `knot.deleted-project.v1.${encodeURIComponent(id)}` &&
        event.key !== null
      )
        return;
      try {
        if (isProjectDeleted(localStorage, id)) {
          setDeleted(true);
          setStorageError(
            'This project was deleted in another tab. This ledger will not be saved again; export a copy if needed.',
          );
          return;
        }
        const raw = localStorage.getItem(storageKey(id));
        if (raw === baseline.current) return;
        if (dirty.current) {
          setStorageError(
            'The saved ledger changed in another tab. Export your unsaved edits before reloading saved data.',
          );
          return;
        }
        const next = raw ? parseBillingLedger(JSON.parse(raw), id) : emptyBillingLedger(id);
        baseline.current = raw;
        ledgerRef.current = next;
        setLedger(next);
        setEditing(null);
        corruptRef.current = false;
        setCorrupt(false);
        setStorageError('');
        setNotice('Costs updated from another tab.');
      } catch {
        setStorageError(
          'Changed data in another tab could not be read. This page has kept its current ledger.',
        );
      }
    };
    window.addEventListener('storage', sync);
    return () => window.removeEventListener('storage', sync);
  }, [id]);

  async function importFile(file: File | undefined, kind: 'report' | 'ledger') {
    if (!file) return;
    setError('');
    setNotice('');
    setPendingImport(null);
    try {
      const limitMiB = kind === 'report' ? 1 : 8;
      if (file.size > limitMiB * 1024 * 1024)
        throw Error(`Choose a JSON file smaller than ${limitMiB} MiB.`);
      const value: unknown = JSON.parse(await file.text());
      if (kind === 'ledger') {
        const next = parseBillingLedger(value, id);
        if (
          ledgerRef.current.entries.length ||
          ledgerRef.current.shared.length ||
          corruptRef.current
        )
          setPendingImport(next);
        else {
          persist(next);
          setNotice('Ledger imported.');
        }
      } else {
        const report = parseUsageReport(value, id);
        if (corruptRef.current) setPendingImport(mergeUsageReport(emptyBillingLedger(id), report));
        else
          mutate(
            (current) => mergeUsageReport(current, report),
            'Usage report imported. Existing confirmations were kept.',
          );
      }
    } catch (failure) {
      setError(message(failure));
    } finally {
      if (reportInput.current) reportInput.current.value = '';
      if (ledgerInput.current) ledgerInput.current.value = '';
    }
  }

  function editCost(entry: UsageEntry) {
    const saved = confirmed.get(entry.id);
    setAmount(saved?.amount || '');
    setCurrency(saved?.currency || entry.estimated_cost?.currency || 'USD');
    setSource(saved?.source || '');
    setAllocation(saved?.allocation || 'owner');
    setCostParticipants(
      saved?.allocation === 'shared'
        ? saved.participants.map((person) => person.id)
        : wf.project.members.map((person) => person.id),
    );
    setEditing(entry.id);
    setEditorOpenCount((count) => count + 1);
    setError('');
  }

  return (
    <section className="cost-ledger" aria-label="Costs & split">
      <div className="billing-heading">
        <div>
          <h3>
            <ReceiptText size={21} /> Project cost ledger
          </h3>
          <p className="muted">
            Each person covers their agents’ confirmed costs. Shared costs are split equally among
            the selected people.
          </p>
        </div>
        <span className={`billing-save-status ${storageError ? 'unsaved' : ''}`}>
          {storageError ? 'Not saved on this device' : 'Saved on this device'}
        </span>
      </div>
      <div className="billing-actions">
        <button className="primary" disabled={deleted} onClick={() => reportInput.current?.click()}>
          <FileUp size={17} />
          Import usage report
        </button>
        <button
          className="secondary"
          disabled={deleted}
          onClick={() => ledgerInput.current?.click()}
        >
          Import ledger JSON
        </button>
        <button
          className="secondary"
          onClick={() =>
            download(exportBillingLedger(ledger), 'knot-cost-ledger.json', 'application/json')
          }
        >
          <Download size={16} />
          Export ledger JSON
        </button>
        <button
          className="secondary"
          disabled={!ledger.entries.length && !ledger.shared.length}
          onClick={() =>
            download(ledgerEntriesCsv(ledger), 'knot-cost-details.csv', 'text/csv;charset=utf-8')
          }
        >
          Export details CSV
        </button>
        <button
          className="secondary"
          disabled={!ledger.confirmed.length && !ledger.shared.length}
          onClick={() =>
            download(settlementCsv(ledger), 'knot-member-split.csv', 'text/csv;charset=utf-8')
          }
        >
          Export split CSV
        </button>
      </div>
      <p className="billing-help">
        Import <code>logs/usage-report.json</code> from your downloaded runner. Reimport it as work
        progresses; each attempt is counted once.
      </p>
      <input
        ref={reportInput}
        className="hidden"
        type="file"
        accept=".json,application/json"
        aria-label="Usage report JSON"
        onChange={(event) => void importFile(event.target.files?.[0], 'report')}
      />
      <input
        ref={ledgerInput}
        className="hidden"
        type="file"
        accept=".json,application/json"
        aria-label="Ledger JSON"
        onChange={(event) => void importFile(event.target.files?.[0], 'ledger')}
      />
      {storageError && (
        <div className="billing-warning" role="alert">
          <p>{storageError}</p>
          <div className="billing-actions">
            {corrupt && baseline.current !== null && (
              <button
                className="secondary"
                onClick={() =>
                  download(baseline.current!, 'knot-ledger-recovery.txt', 'text/plain')
                }
              >
                Download original saved data
              </button>
            )}
            {!corrupt && !deleted && (
              <button className="secondary" onClick={() => persist(ledgerRef.current)}>
                Retry saving
              </button>
            )}
            {!deleted && (
              <button
                className="text-button"
                onClick={() => {
                  const saved = load(id);
                  baseline.current = saved.raw;
                  dirty.current = false;
                  corruptRef.current = saved.corrupt;
                  ledgerRef.current = saved.ledger;
                  setLedger(saved.ledger);
                  setCorrupt(saved.corrupt);
                  setDeleted(saved.deleted);
                  setStorageError(saved.error);
                  setEditing(null);
                  setPendingImport(null);
                }}
              >
                Discard unsaved edits and reload saved ledger
              </button>
            )}
          </div>
        </div>
      )}
      {error && (
        <div className="billing-warning" role="alert">
          {error}
        </div>
      )}
      {notice && (
        <p className="billing-notice" role="status">
          {notice}
        </p>
      )}
      {pendingImport && (
        <div className="billing-replace" role="group" aria-label="Replace ledger confirmation">
          <h4>Replace this ledger?</h4>
          <p>
            The imported ledger contains {pendingImport.entries.length} attempts and{' '}
            {pendingImport.shared.length} shared costs. Export the current ledger first if you need
            to keep it.
          </p>
          <div className="billing-actions">
            <button
              className="primary"
              disabled={deleted}
              onClick={() => {
                persist(pendingImport, true);
                setPendingImport(null);
                setEditing(null);
                setNotice('Imported ledger applied.');
              }}
            >
              Replace ledger
            </button>
            <button className="secondary" onClick={() => setPendingImport(null)}>
              Cancel
            </button>
          </div>
        </div>
      )}
      <div className="billing-summary-grid">
        {summary.currencies.map((total) => (
          <article
            className="billing-summary"
            key={total.currency}
            aria-label={`${total.currency} cost summary`}
          >
            <span className="billing-kicker">{total.currency}</span>
            <h4>{money(total.confirmed, total.currency)}</h4>
            <p>Confirmed subtotal</p>
            <div className="billing-estimate">
              Unconfirmed estimates: {money(total.estimated, total.currency)}
              <small>Estimates are separate and excluded from settlement.</small>
            </div>
          </article>
        ))}
        <article className="billing-summary" aria-label="Usage completeness">
          <span className="billing-kicker">COVERAGE</span>
          <h4>{ledger.entries.length} attempts</h4>
          <p>
            {summary.unknown_count} costs unknown · {summary.partial_count} attempts with partial
            usage
          </p>
          <small>
            {
              ledger.entries.filter(
                (entry) =>
                  entry.usage_status !== 'simulated' &&
                  (!confirmed.has(entry.id) || confirmed.get(entry.id)?.needs_review),
              ).length
            }{' '}
            costs awaiting confirmation
            {summary.simulated_count ? ` · ${summary.simulated_count} simulations excluded` : ''}
          </small>
        </article>
      </div>
      {!ledger.entries.length && (
        <div className="billing-empty">
          <ReceiptText size={26} />
          <h4>No execution costs yet</h4>
          <p>
            Import a usage report after running your workflow. Unknown amounts remain unconfirmed
            until you check them against a bill.
          </p>
        </div>
      )}

      <div className="billing-section-title">
        <h3>Member split</h3>
        <button
          className="secondary"
          disabled={deleted || corrupt}
          onClick={() => {
            setSharedOpen(!sharedOpen);
            setParticipants(wf.project.members.map((person) => person.id));
            setError('');
          }}
        >
          <Plus size={16} />
          Add shared cost
        </button>
      </div>
      <p className="billing-help">
        Only amounts you confirm are included. Planning, subscriptions, and other shared costs can
        be added here. Currencies are settled separately.
      </p>
      {summary.members.length ? (
        <div className="billing-table-wrap">
          <table className="billing-table" aria-label="Member cost split">
            <thead>
              <tr>
                <th>Member</th>
                <th>Currency</th>
                <th>Own agents</th>
                <th>Shared costs</th>
                <th>Amount to split</th>
              </tr>
            </thead>
            <tbody>
              {summary.members.map((member) => (
                <tr key={`${member.id}:${member.currency}`}>
                  <th scope="row">
                    {member.name}
                    <small>{member.id}</small>
                  </th>
                  <td>{member.currency}</td>
                  <td>{member.direct}</td>
                  <td>{member.shared}</td>
                  <td>
                    <strong>{member.total}</strong>
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              {summary.currencies.map((unit) => (
                <tr key={unit.currency}>
                  <th colSpan={4}>Total · {unit.currency}</th>
                  <td>{unit.settlement}</td>
                </tr>
              ))}
            </tfoot>
          </table>
        </div>
      ) : (
        <p className="billing-empty-line">
          Confirm an execution cost or add a shared cost to calculate each person’s share.
        </p>
      )}

      {sharedOpen && (
        <form
          ref={sharedEditor}
          className="billing-editor"
          aria-label="Add shared cost"
          onSubmit={(event) => {
            event.preventDefault();
            if (
              mutate(
                (current) =>
                  addSharedExpense(current, {
                    description: sharedDescription,
                    amount: sharedAmount,
                    currency: sharedCurrency,
                    source: sharedSource,
                    participants: people.filter((person) => participants.includes(person.id)),
                  }),
                'Shared cost added to the member split.',
              )
            ) {
              setSharedOpen(false);
              setSharedDescription('');
              setSharedAmount('');
              setSharedSource('');
            }
          }}
        >
          <h4>Add a confirmed shared cost</h4>
          <div className="billing-form-grid">
            <Field label="Shared cost description">
              <input
                ref={sharedDescriptionInput}
                required
                maxLength={300}
                value={sharedDescription}
                onChange={(event) => setSharedDescription(event.target.value)}
                placeholder="e.g. Project planning"
              />
            </Field>
            <Field label="Shared cost amount">
              <input
                required
                inputMode="decimal"
                value={sharedAmount}
                onChange={(event) => setSharedAmount(event.target.value)}
                placeholder="0.00"
              />
            </Field>
            <Field label="Shared cost currency">
              <CurrencySelect value={sharedCurrency} onChange={setSharedCurrency} />
            </Field>
          </div>
          <Field label="Shared cost bill reference">
            <input
              required
              maxLength={500}
              value={sharedSource}
              onChange={(event) => setSharedSource(event.target.value)}
              placeholder="Invoice reference or how this amount was checked"
            />
          </Field>
          <fieldset className="billing-participants">
            <legend>Split equally among</legend>
            {people.map((person) => (
              <label className="checkbox" key={person.id}>
                <input
                  type="checkbox"
                  checked={participants.includes(person.id)}
                  onChange={(event) =>
                    setParticipants(
                      event.target.checked
                        ? [...participants, person.id]
                        : participants.filter((memberId) => memberId !== person.id),
                    )
                  }
                />
                {person.name}
              </label>
            ))}
          </fieldset>
          <div className="billing-actions">
            <button className="primary" type="submit" disabled={deleted}>
              Confirm shared cost
            </button>
            <button className="secondary" type="button" onClick={() => setSharedOpen(false)}>
              Cancel
            </button>
          </div>
        </form>
      )}
      {!!ledger.shared.length && (
        <div className="billing-table-wrap">
          <table className="billing-table" aria-label="Shared costs">
            <thead>
              <tr>
                <th>Shared cost</th>
                <th>Confirmed amount</th>
                <th>Participants</th>
                <th>Bill reference</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {ledger.shared.map((expense) => (
                <tr key={expense.id}>
                  <th scope="row">
                    {expense.description}
                    <small>{new Date(expense.confirmed_at).toLocaleString()}</small>
                  </th>
                  <td>{money(expense.amount, expense.currency)}</td>
                  <td>{expense.participants.map((person) => person.name).join(', ')}</td>
                  <td>{expense.source}</td>
                  <td>
                    <button
                      className="text-button danger"
                      disabled={deleted || corrupt}
                      onClick={() =>
                        setPendingRemoval({
                          kind: 'shared',
                          id: expense.id,
                          label: expense.description,
                        })
                      }
                      aria-label={`Remove shared cost ${expense.description}`}
                    >
                      <Trash2 size={15} />
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {!!summary.agents.length && (
        <>
          <div className="billing-section-title">
            <h3>Agent totals</h3>
          </div>
          <div className="billing-table-wrap">
            <table className="billing-table" aria-label="Agent cost totals">
              <thead>
                <tr>
                  <th>Agent / responsibility</th>
                  <th>Attempts</th>
                  <th>Input / output tokens</th>
                  <th>Confirmed</th>
                  <th>Estimates</th>
                </tr>
              </thead>
              <tbody>
                {summary.agents.map((agent) => (
                  <tr key={`${agent.agent_id}:${agent.owner_id}`}>
                    <th scope="row">
                      {agent.agent_name}
                      <small>{agent.owner_name}</small>
                    </th>
                    <td>
                      {agent.entry_count}
                      <small>
                        {agent.unknown_count} unknown · {agent.partial_count} partial
                      </small>
                    </td>
                    <td>
                      {tokens(agent.input_tokens)} / {tokens(agent.output_tokens)}
                    </td>
                    <td>{totals(agent.confirmed)}</td>
                    <td>{totals(agent.estimated)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {!!ledger.entries.length && (
        <>
          <div className="billing-section-title">
            <h3>Execution details</h3>
            <span className="muted">Ownership is recorded when the work runs.</span>
          </div>
          <p className="billing-help">
            Input totals include cached tokens. Failed attempts keep their costs; reimporting the
            same attempt does not add another charge. Partial usage shows known subtotals; some
            calls may be missing.
          </p>
          <div className="billing-table-wrap">
            <table
              className="billing-table billing-detail-table"
              aria-label="Execution cost details"
            >
              <thead>
                <tr>
                  <th>Task / attempt</th>
                  <th>Agent / owner</th>
                  <th>Result</th>
                  <th>Usage</th>
                  <th>Estimate</th>
                  <th>Confirmed amount</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {ledger.entries.map((entry) => {
                  const checked = confirmed.get(entry.id);
                  return (
                    <tr key={entry.id}>
                      <th scope="row">
                        {entry.node_label}
                        <small>
                          Attempt {entry.attempt} · {entry.run_id}
                        </small>
                        <small>
                          {entry.model || 'Model not reported'} · {entry.provider}
                        </small>
                      </th>
                      <td>
                        {entry.agent_name}
                        <small>{entry.owner_name}</small>
                      </td>
                      <td>
                        <span className={`billing-state billing-state-${entry.status}`}>
                          {entry.status}
                        </span>
                        <small>
                          {entry.usage_status === 'simulated'
                            ? 'Simulation · excluded'
                            : entry.usage_status === 'legacy'
                              ? 'Older run · usage unavailable'
                              : entry.usage_status}
                        </small>
                      </td>
                      <td>
                        Input: {tokens(entry.usage.input_tokens)}
                        <small>Output: {tokens(entry.usage.output_tokens)}</small>
                        <small>Cached input: {tokens(entry.usage.cached_input_tokens)}</small>
                        {entry.usage.cache_creation_input_tokens !== null && (
                          <small>
                            Cache creation: {tokens(entry.usage.cache_creation_input_tokens)}
                          </small>
                        )}
                      </td>
                      <td>
                        {entry.estimated_cost ? (
                          <>
                            {money(entry.estimated_cost.amount, entry.estimated_cost.currency)}
                            <small>{entry.estimated_cost.source}</small>
                          </>
                        ) : (
                          'Unavailable'
                        )}
                      </td>
                      <td>
                        {checked ? (
                          <>
                            {checked.needs_review && (
                              <strong className="billing-needs-review">
                                Needs review · excluded from split
                              </strong>
                            )}
                            {money(checked.amount, checked.currency)}
                            <small>{checked.source}</small>
                            {checked.allocation === 'shared' && (
                              <small>
                                Shared:{' '}
                                {checked.participants.map((person) => person.name).join(', ')}
                              </small>
                            )}
                            <small>{new Date(checked.confirmed_at).toLocaleString()}</small>
                          </>
                        ) : entry.usage_status === 'simulated' ? (
                          'Excluded'
                        ) : (
                          'Not confirmed'
                        )}
                      </td>
                      <td>
                        <button
                          className="secondary"
                          disabled={
                            deleted ||
                            corrupt ||
                            entry.usage_status === 'simulated' ||
                            entry.status === 'running'
                          }
                          onClick={() => editCost(entry)}
                          aria-label={`${checked ? 'Edit confirmed cost' : 'Confirm cost'} for ${entry.node_label} attempt ${entry.attempt}`}
                        >
                          {checked ? 'Edit amount' : 'Confirm cost'}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
      {active && (
        <form
          ref={costEditor}
          className="billing-editor"
          aria-label="Confirm execution cost"
          onSubmit={(event) => {
            event.preventDefault();
            if (
              mutate(
                (current) =>
                  confirmEntry(current, active.id, {
                    amount,
                    currency,
                    source,
                    allocation,
                    ...(allocation === 'shared'
                      ? {
                          participants: people.filter((person) =>
                            costParticipants.includes(person.id),
                          ),
                        }
                      : {}),
                  }),
                'Execution cost confirmed and included in the member split.',
              )
            )
              setEditing(null);
          }}
        >
          <div className="row between">
            <h4>Confirm cost · {active.node_label}</h4>
            <button
              className="icon-button"
              type="button"
              aria-label="Close cost editor"
              onClick={() => setEditing(null)}
            >
              <X size={17} />
            </button>
          </div>
          <p>
            {active.agent_name} · {active.owner_name} · Attempt {active.attempt}
          </p>
          <p className="billing-help">
            Enter the amount you checked against your bill. Reported estimates are not automatically
            confirmed.
          </p>
          <div className="billing-form-grid">
            <Field label="Confirmed amount">
              <input
                ref={costAmountInput}
                required
                inputMode="decimal"
                value={amount}
                onChange={(event) => setAmount(event.target.value)}
                placeholder="0.00"
              />
            </Field>
            <Field label="Cost currency">
              <CurrencySelect value={currency} onChange={setCurrency} />
            </Field>
            <Field label="Bill reference">
              <input
                required
                maxLength={500}
                value={source}
                onChange={(event) => setSource(event.target.value)}
                placeholder="Invoice reference or verification note"
              />
            </Field>
          </div>
          <Field label="Cost allocation">
            <select
              value={allocation}
              onChange={(event) => setAllocation(event.target.value as 'owner' | 'shared')}
            >
              <option value="owner">Task owner — {active.owner_name}</option>
              <option value="shared">Shared equally</option>
            </select>
          </Field>
          {allocation === 'shared' && (
            <fieldset className="billing-participants">
              <legend>Share this execution cost among</legend>
              {people.map((person) => (
                <label className="checkbox" key={person.id}>
                  <input
                    type="checkbox"
                    checked={costParticipants.includes(person.id)}
                    onChange={(event) =>
                      setCostParticipants(
                        event.target.checked
                          ? [...costParticipants, person.id]
                          : costParticipants.filter((memberId) => memberId !== person.id),
                      )
                    }
                  />
                  {person.name}
                </label>
              ))}
            </fieldset>
          )}
          <div className="billing-actions">
            <button className="primary" type="submit" disabled={deleted}>
              Confirm amount
            </button>
            <button className="secondary" type="button" onClick={() => setEditing(null)}>
              Cancel
            </button>
            {confirmed.has(active.id) && (
              <button
                className="text-button danger"
                type="button"
                disabled={deleted}
                onClick={() =>
                  setPendingRemoval({
                    kind: 'confirmation',
                    id: active.id,
                    label: active.node_label,
                  })
                }
              >
                Remove confirmation
              </button>
            )}
          </div>
        </form>
      )}
      {pendingRemoval && (
        <div className="billing-replace" role="group" aria-label="Remove cost confirmation">
          <h4>
            {pendingRemoval.kind === 'shared' ? 'Remove shared cost?' : 'Remove this confirmation?'}
          </h4>
          <p>
            {pendingRemoval.label} will be removed from the confirmed split.
            {pendingRemoval.kind === 'confirmation'
              ? ' Its execution record and reported estimate will remain.'
              : ''}
          </p>
          <div className="billing-actions">
            <button
              className="primary"
              disabled={deleted || corrupt}
              onClick={() => {
                if (
                  mutate(
                    (current) =>
                      pendingRemoval.kind === 'shared'
                        ? removeSharedExpense(current, pendingRemoval.id)
                        : clearConfirmation(current, pendingRemoval.id),
                    'Confirmed split updated.',
                  )
                ) {
                  setPendingRemoval(null);
                  setEditing(null);
                }
              }}
            >
              Remove from split
            </button>
            <button className="secondary" onClick={() => setPendingRemoval(null)}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

export default function CostLedger({ wf }: { wf: Workflow }) {
  return <CostWorkspace key={wf.project.id} wf={wf} />;
}
