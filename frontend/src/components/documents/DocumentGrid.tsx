import { DocumentCard } from "@/components/documents/DocumentCard";
import type { KnowledgeDocument } from "@/api/types";
import { motion } from "framer-motion";
import type { ReactNode } from "react";

export function DocumentGrid({
  documents,
  selectedId,
  onOpen,
  onSync,
  onIndex,
  onCopyPath,
  onRemoveDocument,
  onClearChunks,
  empty,
}: {
  documents: KnowledgeDocument[];
  selectedId: string | null;
  onOpen: (doc: KnowledgeDocument) => void;
  onSync: (doc: KnowledgeDocument) => void;
  onIndex: (doc: KnowledgeDocument) => void;
  onCopyPath: (doc: KnowledgeDocument) => void;
  onRemoveDocument?: (doc: KnowledgeDocument) => void;
  onClearChunks?: (doc: KnowledgeDocument) => void;
  empty: ReactNode;
}) {
  if (documents.length === 0) return <>{empty}</>;

  return (
    <div className="grid gap-2.5 sm:grid-cols-2 2xl:grid-cols-3">
      {documents.map((doc, index) => (
        <motion.div
          key={doc.id}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.2, delay: Math.min(index * 0.02, 0.16) }}
        >
          <DocumentCard
            doc={doc}
            selected={doc.id === selectedId}
            onOpen={onOpen}
            onSync={onSync}
            onIndex={onIndex}
            onCopyPath={onCopyPath}
            onRemoveDocument={onRemoveDocument}
            onClearChunks={onClearChunks}
          />
        </motion.div>
      ))}
    </div>
  );
}
