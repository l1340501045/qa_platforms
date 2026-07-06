import test from 'node:test';
import assert from 'node:assert/strict';

import {
  buildAssociatedDocumentUrl,
  buildDocumentReturnUrl,
  buildNotificationBatchUrl,
  getNotificationReviewStatus,
} from './batchReturn.ts';

test('notification batch url returns to the matching workbench lane', () => {
  assert.equal(
    buildNotificationBatchUrl('batch-1', 'batch_completed'),
    '/batches/batch-1?from=review&status=pending_review',
  );
  assert.equal(
    buildNotificationBatchUrl('batch-2', 'batch_failed'),
    '/batches/batch-2?from=review&status=failed',
  );
  assert.equal(
    buildNotificationBatchUrl('batch-3', 'batch_suspended'),
    '/batches/batch-3?from=review&status=suspended',
  );
});

test('batch completed notification means pending review, not archived completion', () => {
  assert.equal(getNotificationReviewStatus('batch_completed'), 'pending_review');
});

test('associated document url returns to the source document', () => {
  assert.equal(
    buildAssociatedDocumentUrl('target-doc', 'source-doc', new URLSearchParams()),
    '/documents/target-doc?from=document&document_id=source-doc',
  );
});

test('associated document url preserves knowledge origin', () => {
  const params = new URLSearchParams({
    from: 'knowledge',
    system_id: 'system-1',
  });

  assert.equal(
    buildAssociatedDocumentUrl('target-doc', 'source-doc', params),
    '/documents/target-doc?from=document&document_id=source-doc&document_from=knowledge&system_id=system-1',
  );
});

test('associated document url preserves search origin', () => {
  const params = new URLSearchParams({
    from: 'search',
    q: '标题包',
    system_id: 'system-1',
    priority: 'P0',
    review_status: 'pending',
    page: '3',
  });

  assert.equal(
    buildAssociatedDocumentUrl('target-doc', 'source-doc', params),
    '/documents/target-doc?from=document&document_id=source-doc&document_from=search&q=%E6%A0%87%E9%A2%98%E5%8C%85&system_id=system-1&priority=P0&review_status=pending&page=3',
  );
});

test('document return url preserves original knowledge origin', () => {
  const params = new URLSearchParams({
    from: 'document',
    document_id: 'source-doc',
    document_from: 'knowledge',
    system_id: 'system-1',
  });

  assert.equal(
    buildDocumentReturnUrl(params),
    '/documents/source-doc?from=knowledge&system_id=system-1',
  );
});
