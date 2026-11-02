import { AppShell } from "@/components/AppShell";
import { Chat } from "@/components/Chat";

export default function KnowledgeOS() {
  return (
    <AppShell>
      {() => <main className="flex min-w-0 flex-1 flex-col"><Chat /></main>}
    </AppShell>
  );
}
