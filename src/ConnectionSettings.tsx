import { useEffect, useState } from 'react';
import { CheckCircle2, KeyRound, LoaderCircle, PlugZap } from 'lucide-react';
import { Field } from './Inspector';
import { api } from './model';
import { CONNECTION_PRESETS, connectionPreset, presetConnection } from './connections';
import type { ConnectionPreset, ModelConnection } from './connections';

export default function ConnectionSettings({
  connection,
  onChange,
  credentials,
  onCredentialsChange,
  planning = false,
  disabled = false,
}: {
  connection: ModelConnection;
  onChange: (connection: ModelConnection & { base_url: string }) => void;
  credentials: Record<string, boolean>;
  onCredentialsChange: (credentials: Record<string, boolean>) => void;
  planning?: boolean;
  disabled?: boolean;
}) {
  const [key, setKey] = useState('');
  const [pending, setPending] = useState<'save' | 'test' | ''>('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const preset = connectionPreset(connection);
  const configured = credentials[connection.credential_ref];
  const locked = disabled || !!pending;
  const change = (patch: Partial<ModelConnection>) =>
    onChange({ ...connection, base_url: connection.base_url || '', ...patch });

  useEffect(() => {
    setKey('');
  }, [connection.provider, connection.base_url, connection.credential_ref]);

  useEffect(() => {
    setMessage('');
    setError('');
  }, [connection.provider, connection.model, connection.base_url, connection.credential_ref]);

  async function saveKey() {
    setPending('save');
    setError('');
    setMessage('');
    try {
      const result = await api<{ credentials: Record<string, boolean> }>('credentials', {
        credential_ref: connection.credential_ref,
        key: key.trim(),
      });
      onCredentialsChange(result.credentials);
      setKey('');
      setMessage('API key saved on this device. You can test the connection now.');
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setPending('');
    }
  }

  async function testConnection() {
    setPending('test');
    setError('');
    setMessage('');
    try {
      const result = await api<{ message: string }>('connection/test', { connection });
      setMessage(result.message);
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setPending('');
    }
  }

  return (
    <div className="connection-settings">
      <div className="form-grid">
        <Field label={planning ? 'Planning provider' : 'Provider'}>
          <select
            value={preset}
            disabled={locked}
            onChange={(event) => onChange(presetConnection(event.target.value as ConnectionPreset))}
          >
            {Object.entries(CONNECTION_PRESETS).map(([id, item]) => (
              <option value={id} key={id}>
                {item.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label={planning ? 'Planning model' : 'Model name'}>
          <input
            value={connection.model}
            disabled={locked}
            placeholder={preset === 'deepseek' ? 'deepseek-flash' : 'Your model ID'}
            onChange={(event) => change({ model: event.target.value })}
          />
        </Field>
      </div>
      <div className="connection-key-card">
        <div className="connection-key-heading">
          <KeyRound size={16} />
          <strong>Connection</strong>
          <span className={configured === true ? 'key-state ready' : 'key-state'}>
            {configured === true
              ? 'Saved on this device'
              : configured === false
                ? 'Not configured'
                : 'Credential status not checked'}
          </span>
        </div>
        <Field
          label="API key"
          hint="Stored on this computer only; excluded from workflows and exports."
        >
          <input
            type="password"
            autoComplete="off"
            spellCheck={false}
            value={key}
            disabled={locked}
            placeholder={
              configured ? 'Enter a new key to replace the saved one' : 'Paste your API key here'
            }
            onChange={(event) => setKey(event.target.value)}
          />
        </Field>
        <div className="connection-actions">
          <button
            className="secondary"
            type="button"
            disabled={locked || !key.trim()}
            onClick={() => void saveKey()}
          >
            {pending === 'save' && <LoaderCircle size={15} className="spin" />}Save on this device
          </button>
          <button
            className="secondary"
            type="button"
            disabled={locked || configured === false || !!key.trim() || !connection.model.trim()}
            onClick={() => void testConnection()}
          >
            {pending === 'test' ? (
              <LoaderCircle size={15} className="spin" />
            ) : (
              <PlugZap size={15} />
            )}
            Test connection
          </button>
        </div>
        <p className="connection-test-hint">Tests send a short request to your selected model.</p>
      </div>
      <details className="connection-advanced" open={preset === 'custom' || undefined}>
        <summary>Advanced connection settings</summary>
        <Field
          label={planning ? 'Credential environment variable' : 'Credential reference'}
          hint="Use the environment variable name, e.g. OPENAI_API_KEY."
        >
          <input
            value={connection.credential_ref}
            disabled={locked}
            onChange={(event) => change({ credential_ref: event.target.value })}
          />
        </Field>
        <Field label="API base URL (optional)">
          <input
            value={connection.base_url || ''}
            disabled={locked}
            placeholder="Default provider endpoint"
            onChange={(event) => change({ base_url: event.target.value })}
          />
        </Field>
      </details>
      {message && (
        <div className="connection-feedback success" role="status">
          <CheckCircle2 size={17} />
          <span>{message}</span>
        </div>
      )}
      {error && (
        <div className="connection-feedback error" role="alert">
          {error}
        </div>
      )}
    </div>
  );
}
