import type { DocAssociations, DocRelationType } from '../types';

type DirectAssociation = DocAssociations['direct'][number];
type IndirectAssociation = DocAssociations['indirect'][number];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function asString(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null;
}

function normalizeDocument(
  value: unknown,
  fallbackId: string,
): DirectAssociation['document'] {
  if (isRecord(value)) {
    const id = asString(value.id) ?? fallbackId;
    return {
      id,
      title: asString(value.title) ?? (id ? `关联文档 ${id.slice(0, 8)}` : '关联文档'),
      doc_type: asString(value.doc_type) ?? 'other',
    };
  }

  return {
    id: fallbackId,
    title: fallbackId ? `关联文档 ${fallbackId.slice(0, 8)}` : '关联文档',
    doc_type: 'other',
  };
}

function normalizeDirectItem(
  item: unknown,
  currentDocumentId: string,
): DirectAssociation | null {
  if (!isRecord(item)) return null;

  const id = asString(item.id);
  const relationType = asString(item.relation_type);
  if (!id || !relationType) return null;

  if (isRecord(item.document)) {
    const document = normalizeDocument(item.document, '');
    if (!document.id) return null;
    return {
      id,
      document,
      relation_type: relationType as DocRelationType,
      direction: item.direction === 'incoming' ? 'incoming' : 'outgoing',
    };
  }

  const sourceId = asString(item.source_doc_id);
  const targetId = asString(item.target_doc_id);
  if (!sourceId || !targetId) return null;

  const isOutgoing = sourceId === currentDocumentId;
  const relatedDocumentId = isOutgoing ? targetId : sourceId;

  return {
    id,
    document: normalizeDocument(null, relatedDocumentId),
    relation_type: relationType as DocRelationType,
    direction: isOutgoing ? 'outgoing' : 'incoming',
  };
}

function normalizeIndirectItem(item: unknown): IndirectAssociation | null {
  if (!isRecord(item)) return null;
  if (!isRecord(item.document)) return null;

  const document = normalizeDocument(item.document, '');
  if (!document.id) return null;

  return {
    document,
    path: Array.isArray(item.path) ? item.path.filter((part): part is string => typeof part === 'string') : [],
    depth: typeof item.depth === 'number' ? item.depth : 0,
  };
}

export function normalizeDocAssociations(
  data: unknown,
  currentDocumentId: string,
): DocAssociations {
  if (!isRecord(data)) {
    return { direct: [], indirect: [] };
  }

  const directSource = Array.isArray(data.direct)
    ? data.direct
    : Array.isArray(data.items)
      ? data.items
      : [];
  const indirectSource = Array.isArray(data.indirect) ? data.indirect : [];

  return {
    direct: directSource
      .map((item) => normalizeDirectItem(item, currentDocumentId))
      .filter((item): item is DirectAssociation => item !== null),
    indirect: indirectSource
      .map(normalizeIndirectItem)
      .filter((item): item is IndirectAssociation => item !== null),
  };
}
