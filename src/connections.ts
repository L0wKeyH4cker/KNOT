export type ModelConnection = {
  provider: 'openai' | 'anthropic';
  model: string;
  credential_ref: string;
  base_url?: string;
};

export const CONNECTION_PRESETS = {
  deepseek: {
    label: 'DeepSeek',
    provider: 'openai',
    model: 'deepseek-flash',
    credential_ref: 'DEEPSEEK_API_KEY',
    base_url: 'https://api.deepseek.com',
  },
  openai: {
    label: 'OpenAI',
    provider: 'openai',
    model: '',
    credential_ref: 'OPENAI_API_KEY',
    base_url: '',
  },
  anthropic: {
    label: 'Anthropic',
    provider: 'anthropic',
    model: '',
    credential_ref: 'ANTHROPIC_API_KEY',
    base_url: '',
  },
  custom: {
    label: 'Other OpenAI-compatible API',
    provider: 'openai',
    model: '',
    credential_ref: 'CUSTOM_API_KEY',
    base_url: '',
  },
} as const;
export type ConnectionPreset = keyof typeof CONNECTION_PRESETS;

export function connectionPreset(connection: ModelConnection): ConnectionPreset {
  if (connection.provider === 'anthropic') return 'anthropic';
  try {
    if (connection.base_url && new URL(connection.base_url).hostname === 'api.deepseek.com')
      return 'deepseek';
  } catch {
    /* A partially edited address stays in the custom form. */
  }
  return (!connection.base_url && connection.credential_ref === 'OPENAI_API_KEY') ||
    (!!connection.base_url && /^https:\/\/api\.openai\.com(?:\/v1)?\/?$/.test(connection.base_url))
    ? 'openai'
    : 'custom';
}

export function presetConnection(
  preset: ConnectionPreset,
  credentialRef?: string,
): ModelConnection & { base_url: string } {
  const { label: _label, ...connection } = CONNECTION_PRESETS[preset];
  return credentialRef
    ? {
        ...connection,
        credential_ref: credentialRef,
        base_url: preset === 'openai' ? 'https://api.openai.com/v1' : connection.base_url,
      }
    : connection;
}
