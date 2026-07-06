import type { Priority, ReviewStatus } from '../types';

interface SearchReturnState {
  q?: string;
  systemId?: string;
  priority?: Priority;
  reviewStatus?: ReviewStatus;
  page?: number;
}

interface SearchBatchUrlOptions {
  caseId?: string;
}

function appendIfPresent(params: URLSearchParams, key: string, value: string | number | undefined | null) {
  if (value === undefined || value === null || value === '') return;
  params.set(key, String(value));
}

export function buildSearchReturnParams(source: URLSearchParams | SearchReturnState): URLSearchParams {
  const params = new URLSearchParams({ from: 'search' });

  if (source instanceof URLSearchParams) {
    appendIfPresent(params, 'q', source.get('q'));
    appendIfPresent(params, 'system_id', source.get('system_id'));
    appendIfPresent(params, 'priority', source.get('priority'));
    appendIfPresent(params, 'review_status', source.get('review_status'));
    appendIfPresent(params, 'page', source.get('page'));
    return params;
  }

  appendIfPresent(params, 'q', source.q?.trim());
  appendIfPresent(params, 'system_id', source.systemId);
  appendIfPresent(params, 'priority', source.priority);
  appendIfPresent(params, 'review_status', source.reviewStatus);
  appendIfPresent(params, 'page', source.page && source.page > 1 ? source.page : undefined);
  return params;
}

export function buildSearchReturnUrl(source: URLSearchParams | SearchReturnState): string {
  const params = buildSearchReturnParams(source);
  params.delete('from');
  const query = params.toString();
  return query ? `/search?${query}` : '/search';
}

export function buildSearchDocumentUrl(documentId: string, source: URLSearchParams | SearchReturnState): string {
  return `/documents/${encodeURIComponent(documentId)}?${buildSearchReturnParams(source).toString()}`;
}

export function buildSearchBatchUrl(
  batchId: string,
  source: URLSearchParams | SearchReturnState,
  options: SearchBatchUrlOptions = {},
): string {
  const params = buildSearchReturnParams(source);
  appendIfPresent(params, 'case_id', options.caseId);
  return `/batches/${encodeURIComponent(batchId)}?${params.toString()}`;
}
