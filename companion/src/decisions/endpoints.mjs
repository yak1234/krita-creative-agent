// Decision endpoints: where decisions are sent, how they authenticate, and how to
// list their current models. Built-ins cover OpenRouter (every decision model it
// serves), OpenAI's Decisions API and TypeSafe; artists can add any System One
// endpoint (e.g. Unsloth Studio serving a model they trained).

export const BUILT_IN_ENDPOINTS = Object.freeze({
  openrouter: {
    id: 'openrouter', name: 'OpenRouter', protocol: 'systemone', url: 'https://openrouter.ai/api/alpha/decisions',
    keyHint: 'Uses the OpenRouter key the painter is connected with.', defaultModel: 'openai/gpt-6-luna-decisions',
    async listModels({ fetch, key }) {
      const response = await fetch('https://openrouter.ai/api/v1/models?output_modalities=decisions', { headers: key ? { Authorization: 'Bearer ' + key } : {} });
      if (!response.ok) throw new Error('OpenRouter returned ' + response.status + ' listing decision models.');
      const { data } = await response.json();
      return data.filter(model => (model.architecture?.output_modalities ?? []).includes('decisions')).map(model => ({
        id: model.id, name: model.name ?? model.id,
        images: (model.architecture?.input_modalities ?? []).includes('image'),
        price_per_million_input: Number(model.pricing?.prompt ?? 0) * 1e6,
      })).sort((a, b) => Number(b.images) - Number(a.images) || a.price_per_million_input - b.price_per_million_input);
    },
  },
  openai: {
    id: 'openai', name: 'OpenAI', protocol: 'openai', url: 'https://api.openai.com/v1/decisions', envKey: 'OPENAI_API_KEY',
    keyHint: 'An OpenAI API key (OPENAI_API_KEY in .env, or saved in settings).', defaultModel: 'gpt-6-luna',
    async listModels() { return [{ id: 'gpt-6-luna', name: 'GPT-6 Luna', images: true }]; },
  },
  typesafe: {
    id: 'typesafe', name: 'TypeSafe', protocol: 'systemone', url: 'https://api.typesafe.ai/v1/systemone', envKey: 'TYPESAFE_API_KEY',
    keyHint: 'A TypeSafe API key (TYPESAFE_API_KEY in .env, or saved in settings).', defaultModel: 'jev-latest',
    async listModels() { return [{ id: 'jev-latest', name: 'Jev (latest)', images: false }]; },
  },
});

// A custom endpoint: System One protocol at `url` (the full decisions route, e.g.
// http://localhost:8888/v1/systemone). Models come from its OpenAI-style /models list
// when it has one; image support is unknown until the two-image check runs.
export function customEndpoint({ id, name, url, defaultModel = 'default' }) {
  const endpoint = new URL(url);
  if (endpoint.username || endpoint.password) throw new Error('Put credentials in the key field, not the URL.');
  if (endpoint.protocol !== 'https:' && !(endpoint.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(endpoint.hostname)))
    throw new Error('Use an HTTPS endpoint, or a local server.');
  return {
    id, name: name ?? id, protocol: 'systemone', url: endpoint.toString(), custom: true, defaultModel,
    keyHint: 'The key for this endpoint, if it needs one.',
    async listModels({ fetch, key }) {
      try {
        const base = endpoint.toString().replace(/\/[^/]+\/?$/, '');
        const response = await fetch(base + '/models', { headers: key ? { Authorization: 'Bearer ' + key } : {} });
        if (response.ok) {
          const { data } = await response.json();
          if (Array.isArray(data) && data.length) return data.map(model => ({ id: model.id, name: model.id, images: null }));
        }
      } catch { /* No model list: offer the default name. */ }
      return [{ id: defaultModel, name: defaultModel, images: null }];
    },
  };
}

export function resolveEndpoint(id, custom = {}) {
  if (BUILT_IN_ENDPOINTS[id]) return BUILT_IN_ENDPOINTS[id];
  if (custom[id]) return customEndpoint({ id, ...custom[id] });
  throw new Error('Unknown decision endpoint: ' + id);
}
