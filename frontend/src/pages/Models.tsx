import { useEffect, useState, type FormEvent } from "react";
import { AppShell } from "@/components/AppShell";
import { PageBody, PageHeader, Workspace } from "@/components/system/layout";
import { EmptyNote, Panel } from "@/components/system/panels";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { KeyRound, Loader2, Plus, Server, Trash2 } from "lucide-react";
import { createProvider, deleteProvider, fetchProviders, testProvider, type ProviderProfile as ApiProviderProfile } from "@/api/providers";

const PROVIDERS = [
  "FreeLLM API",
  "OmniRouter",
  "OpenRouter",
  "NVIDIA NIM",
  "Custom OpenAI-compatible",
] as const;

type ProviderKind = (typeof PROVIDERS)[number];
type ProviderRole = "Generation" | "Embeddings" | "Both";

interface ProviderProfile {
  id: string;
  provider: ProviderKind;
  name: string;
  baseUrl: string;
  model: string;
  apiKey?: string;
  role: ProviderRole;
}

interface ProviderPreset {
  baseUrl: string;
  model: string;
  keyHint?: string;
}

const PROVIDER_PRESETS: Record<ProviderKind, ProviderPreset> = {
  "FreeLLM API": {
    baseUrl: "http://127.0.0.1:31415/v1",
    model: "auto",
    keyHint: "freellmapi-...",
  },
  OmniRouter: {
    baseUrl: "https://api.omnirouter.ai/v1",
    model: "auto",
    keyHint: "or-...",
  },
  OpenRouter: {
    baseUrl: "https://openrouter.ai/api/v1",
    model: "openai/gpt-4o-mini",
    keyHint: "sk-or-...",
  },
  "NVIDIA NIM": {
    baseUrl: "https://integrate.api.nvidia.com/v1",
    model: "meta/llama-3.1-8b-instruct",
    keyHint: "nvapi-...",
  },
  "Custom OpenAI-compatible": {
    baseUrl: "",
    model: "",
  },
};

const INITIAL_FORM = {
  provider: "FreeLLM API" as ProviderKind,
  name: "FreeLLM API",
  baseUrl: PROVIDER_PRESETS["FreeLLM API"].baseUrl,
  model: PROVIDER_PRESETS["FreeLLM API"].model,
  apiKey: "",
  role: "Generation" as ProviderRole,
};

function ProviderForm({
  onAdd,
  onCancel,
}: {
  onAdd: (provider: ProviderProfile) => void;
  onCancel: () => void;
}) {
  const [form, setForm] = useState(INITIAL_FORM);
  const [showKey, setShowKey] = useState(false);

  const setField = <K extends keyof typeof INITIAL_FORM>(
    key: K,
    value: (typeof INITIAL_FORM)[K],
  ) => setForm((current) => ({ ...current, [key]: value }));

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onAdd({ ...form, id: crypto.randomUUID() });
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="space-y-1.5 text-[11px]">
          <span className="font-medium">Provider</span>
          <select
            value={form.provider}
            onChange={(event) => {
              const provider = event.target.value as ProviderKind;
              const preset = PROVIDER_PRESETS[provider];
              setForm((current) => ({
                ...current,
                provider,
                name: provider === "Custom OpenAI-compatible" ? "Custom provider" : provider,
                baseUrl: preset.baseUrl,
                model: preset.model,
              }));
            }}
            className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
          >
            {PROVIDERS.map((provider) => (
              <option key={provider} value={provider}>{provider}</option>
            ))}
          </select>
        </label>
        <label className="space-y-1.5 text-[11px]">
          <span className="font-medium">Use for</span>
          <select
            value={form.role}
            onChange={(event) => setField("role", event.target.value as ProviderRole)}
            className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
          >
            <option>Generation</option>
            <option>Embeddings</option>
            <option>Both</option>
          </select>
        </label>
      </div>

      <label className="block space-y-1.5 text-[11px]">
        <span className="font-medium">Display name</span>
        <Input
          value={form.name}
          onChange={(event) => setField("name", event.target.value)}
          placeholder="My provider"
          required
        />
      </label>

      <label className="block space-y-1.5 text-[11px]">
        <span className="font-medium">API base URL</span>
        <Input
          type="url"
          value={form.baseUrl}
          onChange={(event) => setField("baseUrl", event.target.value)}
          placeholder="https://api.example.com/v1"
          required
        />
      </label>

      <label className="block space-y-1.5 text-[11px]">
        <span className="font-medium">Model ID</span>
        <Input
          value={form.model}
          onChange={(event) => setField("model", event.target.value)}
          placeholder="provider/model-name"
          required
        />
      </label>

      <div className="space-y-1.5 text-[11px]">
        <label htmlFor="provider-api-key" className="font-medium">API key</label>
        <div className="flex gap-2">
          <Input
            id="provider-api-key"
            type={showKey ? "text" : "password"}
            value={form.apiKey}
            onChange={(event) => setField("apiKey", event.target.value)}
            placeholder={PROVIDER_PRESETS[form.provider].keyHint ? `e.g. ${PROVIDER_PRESETS[form.provider].keyHint}` : "Enter API key"}
            autoComplete="off"
            required
          />
          <Button
            type="button"
            variant="outline"
            onClick={() => setShowKey((visible) => !visible)}
          >
            {showKey ? "Hide" : "Show"}
          </Button>
        </div>
        {PROVIDER_PRESETS[form.provider].keyHint ? (
          <p className="text-[10px] text-muted-foreground">
            Expected format: <span className="font-mono">{PROVIDER_PRESETS[form.provider].keyHint}</span>
          </p>
        ) : null}
      </div>

      <p className="rounded-md border border-border bg-muted/30 px-3 py-2 text-[10.5px] leading-4 text-muted-foreground">
        The key is sent once to the local backend over this connection. It is
        encrypted at rest and never returned to the browser; use HTTPS when the
        backend is exposed beyond your local machine.
      </p>

      <DialogFooter>
        <Button type="button" variant="outline" onClick={onCancel}>Cancel</Button>
        <Button type="submit"><Plus className="size-3.5" /> Add provider</Button>
      </DialogFooter>
    </form>
  );
}

function ModelsWorkspace() {
  const [providers, setProviders] = useState<ApiProviderProfile[]>([]);
  const [addOpen, setAddOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, string>>({});

  useEffect(() => {
    void fetchProviders().then(setProviders).catch((value) => setError(value instanceof Error ? value.message : "Could not load providers")).finally(() => setLoading(false));
  }, []);

  const addProvider = async (provider: ProviderProfile) => {
    try {
      const created = await createProvider({ name: provider.name, kind: provider.provider, baseUrl: provider.baseUrl, model: provider.model, role: provider.role, apiKey: provider.apiKey ?? "" });
      setProviders((current) => [...current, created]);
      setAddOpen(false);
    } catch (value) {
      setError(value instanceof Error ? value.message : "Could not add provider");
    }
  };

  return (
    <Workspace>
      <PageHeader
        title="Models"
        description="Configure API provider profiles for generation and embeddings. Local Ollama embeddings are used by default."
      >
        <Button size="sm" className="h-7 text-[11px]" onClick={() => setAddOpen(true)}>
          <Plus className="size-3.5" /> Add provider
        </Button>
      </PageHeader>

      <PageBody>
        <Panel
          title="API providers"
          description="FreeLLM API, OmniRouter, OpenRouter, NVIDIA NIM, or a compatible endpoint. Remote Embeddings profiles override local Ollama."
        >
          {loading ? <EmptyNote>Loading providers…</EmptyNote> : error ? <p className="text-[11px] text-[var(--term-bad)]">{error}</p> : providers.length === 0 ? (
            <div className="space-y-3">
              <EmptyNote>No providers configured.</EmptyNote>
              <Button variant="outline" size="sm" onClick={() => setAddOpen(true)}>
                <Plus className="size-3.5" /> Add an API provider
              </Button>
            </div>
          ) : (
            <ul className="space-y-2">
              {providers.map((provider) => (
                <li
                  key={provider.id}
                  className="flex flex-wrap items-center gap-3 rounded-md border border-border bg-background px-3 py-2.5"
                >
                  <div className="grid size-8 shrink-0 place-items-center rounded-md border border-border bg-card">
                    <Server className="size-4 text-muted-foreground" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[12px] font-semibold">{provider.name}</p>
                    <p className="truncate font-mono text-[10px] text-muted-foreground">
                      {provider.kind} · {provider.model}
                    </p>
                    <p className="truncate font-mono text-[10px] text-muted-foreground">
                      {provider.baseUrl}
                    </p>
                  </div>
                  <span className="inline-flex items-center gap-1 rounded-full border border-border px-2 py-1 text-[10px] text-muted-foreground">
                    <KeyRound className="size-3" /> Key configured
                  </span>
                  <span className="rounded-full bg-muted px-2 py-1 text-[10px]">{provider.role}</span>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-7 px-2 text-[10px]"
                    disabled={testing === provider.id}
                    onClick={() => {
                      setTesting(provider.id);
                      void testProvider(provider.id).then((result) => setTestResults((current) => ({ ...current, [provider.id]: result.ok ? "Connected" : result.detail ?? "Connection failed" }))).catch((value) => setTestResults((current) => ({ ...current, [provider.id]: value instanceof Error ? value.message : "Connection failed" }))).finally(() => setTesting(null));
                    }}
                  >
                    {testing === provider.id ? <Loader2 className="size-3 animate-spin" /> : "Test"}
                  </Button>
                  {testResults[provider.id] ? <span className="text-[10px] text-[var(--term-ok)]">{testResults[provider.id]}</span> : null}
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Remove ${provider.name}`}
                    onClick={() => void deleteProvider(provider.id).then(() => setProviders((current) => current.filter((item) => item.id !== provider.id))).catch((value) => setError(value instanceof Error ? value.message : "Could not remove provider"))}
                  >
                    <Trash2 className="size-4" />
                  </Button>
                </li>
              ))}
            </ul>
          )}
          {providers.length > 0 ? (
            <p className="mt-3 text-[10.5px] text-muted-foreground">
              Profiles are used by the backend for generation and embedding
              requests when their role matches the active pipeline.
            </p>
          ) : null}
        </Panel>
      </PageBody>

      <Dialog open={addOpen} onOpenChange={setAddOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add API provider</DialogTitle>
            <DialogDescription>
              Enter the endpoint, model ID, and key supplied by your provider.
            </DialogDescription>
          </DialogHeader>
          <ProviderForm onAdd={addProvider} onCancel={() => setAddOpen(false)} />
        </DialogContent>
      </Dialog>
    </Workspace>
  );
}

export default function Models() {
  return <AppShell>{() => <ModelsWorkspace />}</AppShell>;
}
