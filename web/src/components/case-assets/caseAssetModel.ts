import type { CaseTreeBranch, CaseTreeCase, CaseTreeDocument } from '../../types';

export type CaseAssetNodeType = 'root' | 'document' | 'module' | 'branch';

export interface CaseAssetNode {
  key: string;
  type: CaseAssetNodeType;
  title: string;
  count: number;
  children: CaseAssetNode[];
  caseIds: string[];
  directCaseIds: string[];
  meta: {
    documentId?: string;
    moduleName?: string;
    branchPath?: string[];
  };
}

export interface CaseAssetTree {
  root: CaseAssetNode;
  caseMap: Map<string, CaseTreeCase>;
}

interface NormalizeOptions {
  rootTitle?: string;
}

function encodeKeyPart(value: string): string {
  return encodeURIComponent(value);
}

function makeNode(
  key: string,
  type: CaseAssetNodeType,
  title: string,
  meta: CaseAssetNode['meta'] = {},
): CaseAssetNode {
  return {
    key,
    type,
    title,
    count: 0,
    children: [],
    caseIds: [],
    directCaseIds: [],
    meta,
  };
}

function appendUnique(target: string[], ids: string[]): void {
  for (const id of ids) {
    if (!target.includes(id)) {
      target.push(id);
    }
  }
}

function appendCases(
  node: CaseAssetNode,
  cases: CaseTreeCase[],
  caseMap: Map<string, CaseTreeCase>,
  options: { direct?: boolean } = {},
): void {
  const ids = cases.map((item) => item.id);
  for (const item of cases) {
    caseMap.set(item.id, item);
  }
  appendUnique(node.caseIds, ids);
  if (options.direct) {
    appendUnique(node.directCaseIds, ids);
  }
  node.count = node.caseIds.length;
}

function syncCount(node: CaseAssetNode): void {
  node.count = node.caseIds.length;
  for (const child of node.children) {
    syncCount(child);
  }
}

function fallbackBranchesFromCases(cases: CaseTreeCase[]): CaseTreeBranch[] {
  const grouped = new Map<string, { branchPath: string[]; cases: CaseTreeCase[] }>();
  for (const item of cases) {
    const branchPath = item.branch_path?.length ? item.branch_path : ['通用规则'];
    const key = branchPath.join('\u0000');
    const current = grouped.get(key);
    if (current) {
      current.cases.push(item);
    } else {
      grouped.set(key, { branchPath, cases: [item] });
    }
  }

  return Array.from(grouped.values()).map(({ branchPath, cases: branchCases }) => ({
    branch_name: branchPath.join(' / '),
    branch_path: branchPath,
    case_count: branchCases.length,
    cases: branchCases,
  }));
}

function findBranchChild(parent: CaseAssetNode, key: string): CaseAssetNode | undefined {
  return parent.children.find((child) => child.key === key);
}

function addBranchPath(
  moduleNode: CaseAssetNode,
  branch: CaseTreeBranch,
  ancestors: CaseAssetNode[],
  caseMap: Map<string, CaseTreeCase>,
): void {
  const branchPath = branch.branch_path.length ? branch.branch_path : [branch.branch_name || '通用规则'];
  let current = moduleNode;
  const pathSoFar: string[] = [];

  for (const segment of branchPath) {
    pathSoFar.push(segment);
    const key = [
      'branch',
      encodeKeyPart(moduleNode.meta.documentId || ''),
      encodeKeyPart(moduleNode.meta.moduleName || ''),
      ...pathSoFar.map(encodeKeyPart),
    ].join('::');

    let next = findBranchChild(current, key);
    if (!next) {
      next = makeNode(key, 'branch', segment, {
        documentId: moduleNode.meta.documentId,
        moduleName: moduleNode.meta.moduleName,
        branchPath: [...pathSoFar],
      });
      current.children.push(next);
    }

    appendCases(next, branch.cases, caseMap, {
      direct: pathSoFar.length === branchPath.length,
    });
    current = next;
  }

  for (const ancestor of ancestors) {
    appendCases(ancestor, branch.cases, caseMap);
  }
}

export function normalizeCaseTreeDocuments(
  documents: CaseTreeDocument[],
  options: NormalizeOptions = {},
): CaseAssetTree {
  const caseMap = new Map<string, CaseTreeCase>();
  const root = makeNode('root', 'root', options.rootTitle || '全部用例');

  for (const document of documents) {
    const docNode = makeNode(`doc::${encodeKeyPart(document.document_id)}`, 'document', document.document_title, {
      documentId: document.document_id,
    });
    root.children.push(docNode);

    for (const module of document.modules) {
      const moduleNode = makeNode(
        `module::${encodeKeyPart(document.document_id)}::${encodeKeyPart(module.module_name)}`,
        'module',
        module.module_name,
        {
          documentId: document.document_id,
          moduleName: module.module_name,
        },
      );
      docNode.children.push(moduleNode);

      appendCases(moduleNode, module.cases, caseMap);
      appendCases(docNode, module.cases, caseMap);
      appendCases(root, module.cases, caseMap);

      const branches = module.branches?.length ? module.branches : fallbackBranchesFromCases(module.cases);
      if (branches.length === 0) {
        appendCases(moduleNode, module.cases, caseMap, { direct: true });
      }

      for (const branch of branches) {
        addBranchPath(moduleNode, branch, [moduleNode, docNode, root], caseMap);
      }
    }
  }

  syncCount(root);
  return { root, caseMap };
}

export function findCaseAssetNode(root: CaseAssetNode, nodeKey: string): CaseAssetNode | undefined {
  if (root.key === nodeKey) return root;
  for (const child of root.children) {
    const found = findCaseAssetNode(child, nodeKey);
    if (found) return found;
  }
  return undefined;
}

export function getCasesForNode(nodeKey: string, tree: CaseAssetTree): CaseTreeCase[] {
  const node = findCaseAssetNode(tree.root, nodeKey);
  if (!node) return [];
  return node.caseIds.map((id) => tree.caseMap.get(id)).filter((item): item is CaseTreeCase => Boolean(item));
}

export function findCaseAssetNodeKeyForCase(root: CaseAssetNode, caseId: string): string | null {
  let matchKey: string | null = null;

  function visit(node: CaseAssetNode): void {
    if (!node.caseIds.includes(caseId)) return;
    matchKey = node.key;
    for (const child of node.children) {
      visit(child);
    }
  }

  visit(root);
  return matchKey;
}

function cloneNode(node: CaseAssetNode, children: CaseAssetNode[]): CaseAssetNode {
  return {
    ...node,
    children,
    caseIds: [...node.caseIds],
    directCaseIds: [...node.directCaseIds],
    meta: {
      ...node.meta,
      branchPath: node.meta.branchPath ? [...node.meta.branchPath] : undefined,
    },
  };
}

export function filterCaseAssetTree(
  root: CaseAssetNode,
  keyword: string,
  caseMap: ReadonlyMap<string, CaseTreeCase>,
): CaseAssetNode | null {
  const normalizedKeyword = keyword.trim().toLocaleLowerCase();
  if (!normalizedKeyword) return root;

  const titleMatches = root.title.toLocaleLowerCase().includes(normalizedKeyword);
  if (titleMatches) {
    return root;
  }

  const filteredChildren = root.children
    .map((child) => filterCaseAssetTree(child, keyword, caseMap))
    .filter((child): child is CaseAssetNode => Boolean(child));

  const directCaseMatches = root.directCaseIds.some((id) =>
    caseMap.get(id)?.title.toLocaleLowerCase().includes(normalizedKeyword),
  );

  if (directCaseMatches || filteredChildren.length > 0) {
    return cloneNode(root, filteredChildren);
  }

  return null;
}

export function collectCaseAssetKeys(root: CaseAssetNode): string[] {
  return [root.key, ...root.children.flatMap(collectCaseAssetKeys)];
}

export function getDefaultExpandedKeys(root: CaseAssetNode, maxDepth = 1): string[] {
  const keys: string[] = [];

  function visit(node: CaseAssetNode, depth: number): void {
    if (node.children.length > 0 && depth <= maxDepth) {
      keys.push(node.key);
    }
    for (const child of node.children) {
      visit(child, depth + 1);
    }
  }

  visit(root, 0);
  return keys;
}
