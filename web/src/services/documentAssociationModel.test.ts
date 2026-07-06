import test from 'node:test';
import assert from 'node:assert/strict';

import { normalizeDocAssociations } from './documentAssociationModel.ts';

test('normalizeDocAssociations accepts paginated empty association response', () => {
  const result = normalizeDocAssociations(
    { items: [], total: 0, page: 1, per_page: 20, total_pages: 0 },
    'doc-current',
  );

  assert.deepEqual(result, { direct: [], indirect: [] });
});

test('normalizeDocAssociations maps paginated association rows to direct associations', () => {
  const result = normalizeDocAssociations(
    {
      items: [
        {
          id: 'assoc-out',
          source_doc_id: 'doc-current',
          target_doc_id: 'doc-target',
          relation_type: 'req_to_tech',
        },
        {
          id: 'assoc-in',
          source_doc_id: 'doc-source',
          target_doc_id: 'doc-current',
          relation_type: 'req_to_case',
        },
      ],
      total: 2,
      page: 1,
      per_page: 20,
      total_pages: 1,
    },
    'doc-current',
  );

  assert.equal(result.direct.length, 2);
  assert.equal(result.direct[0].direction, 'outgoing');
  assert.equal(result.direct[0].document.id, 'doc-target');
  assert.equal(result.direct[1].direction, 'incoming');
  assert.equal(result.direct[1].document.id, 'doc-source');
});

test('normalizeDocAssociations preserves direct and indirect detail response shape', () => {
  const result = normalizeDocAssociations(
    {
      direct: [
        {
          id: 'assoc-1',
          document: { id: 'doc-target', title: '技术方案', doc_type: 'tech_doc' },
          relation_type: 'req_to_tech',
          direction: 'outgoing',
        },
      ],
      indirect: [
        {
          document: { id: 'doc-rule', title: '测试规则', doc_type: 'test_rule' },
          path: ['doc-target', 'doc-rule'],
          depth: 2,
        },
      ],
    },
    'doc-current',
  );

  assert.equal(result.direct[0].document.title, '技术方案');
  assert.equal(result.indirect[0].document.title, '测试规则');
  assert.equal(result.indirect[0].depth, 2);
});
