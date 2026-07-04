import type { BatchStatus, NotificationType } from '../types';

const SEARCH_CONTEXT_KEYS = ['q', 'system_id', 'priority', 'review_status', 'page'] as const;

const NOTIFICATION_REVIEW_STATUS: Record<NotificationType, BatchStatus> = {
  batch_completed: 'pending_review',
  batch_failed: 'failed',
  batch_suspended: 'suspended',
};

function appendIfPresent(params: URLSearchParams, key: string, value: string | null | undefined) {
  if (!value) return;
  params.set(key, value);
}

function appendSearchContext(params: URLSearchParams, sourceParams: URLSearchParams) {
  for (const key of SEARCH_CONTEXT_KEYS) {
    appendIfPresent(params, key, sourceParams.get(key));
  }
}

export function buildKnowledgeBatchUrl(batchId: string, systemId?: string): string {
  const params = new URLSearchParams({ from: 'knowledge' });
  appendIfPresent(params, 'system_id', systemId);
  return `/batches/${encodeURIComponent(batchId)}?${params.toString()}`;
}

export function buildDocumentBatchUrl(
  batchId: string,
  documentId: string,
  sourceParams?: URLSearchParams,
): string {
  const params = new URLSearchParams({
    from: 'document',
    document_id: documentId,
  });

  const sourceFrom = sourceParams?.get('from');
  if (sourceParams && sourceFrom === 'knowledge') {
    params.set('document_from', 'knowledge');
    appendIfPresent(params, 'system_id', sourceParams.get('system_id'));
  }
  if (sourceParams && sourceFrom === 'search') {
    params.set('document_from', 'search');
    appendSearchContext(params, sourceParams);
  }

  return `/batches/${encodeURIComponent(batchId)}?${params.toString()}`;
}

export function getNotificationReviewStatus(type: NotificationType): BatchStatus {
  return NOTIFICATION_REVIEW_STATUS[type];
}

export function buildNotificationBatchUrl(batchId: string, type: NotificationType): string {
  const params = new URLSearchParams({
    from: 'review',
    status: getNotificationReviewStatus(type),
  });
  return `/batches/${encodeURIComponent(batchId)}?${params.toString()}`;
}

export function buildKnowledgeReturnUrl(systemId: string | null): string {
  return systemId ? `/systems/${encodeURIComponent(systemId)}/documents` : '/systems';
}

export function buildDocumentReturnUrl(sourceParams: URLSearchParams): string | null {
  const documentId = sourceParams.get('document_id');
  if (!documentId) return null;

  const params = new URLSearchParams();
  const documentFrom = sourceParams.get('document_from');
  if (documentFrom === 'knowledge') {
    params.set('from', 'knowledge');
    appendIfPresent(params, 'system_id', sourceParams.get('system_id'));
  }
  if (documentFrom === 'search') {
    params.set('from', 'search');
    appendSearchContext(params, sourceParams);
  }

  const query = params.toString();
  return `/documents/${encodeURIComponent(documentId)}${query ? `?${query}` : ''}`;
}
