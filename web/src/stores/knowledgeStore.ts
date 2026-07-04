/**
 * Knowledge Store — 系统 + 文档状态管理
 * 对齐契约：page/per_page 分页，resp.data 已由拦截器解包
 */
import { create } from 'zustand';
import type {
  System,
  SystemDetail,
  Document,
  DocumentDetail,
  DocType,
  PaginatedData,
  PaginationParams,
  UploadResult,
} from '../types';
import { listSystems, getSystem, createSystem, updateSystem, deleteSystem } from '../services/systemApi';
import { listDocuments, getDocument, batchUploadDocuments, updateDocumentType } from '../services/documentApi';
import type { DocumentFilterParams } from '../services/documentApi';
import type { CreateSystemRequest, UpdateSystemRequest } from '../types';

interface KnowledgeState {
  // 系统列表
  systems: System[];
  systemsTotal: number;
  systemsPage: number;
  systemsPerPage: number;
  systemsTotalPages: number;
  systemsLoading: boolean;

  // 当前选中系统
  currentSystem: SystemDetail | null;

  // 文档列表
  documents: Document[];
  documentsTotal: number;
  documentsPage: number;
  documentsPerPage: number;
  documentsTotalPages: number;
  documentsLoading: boolean;

  // 当前文档
  currentDocument: DocumentDetail | null;

  // 上传状态
  uploadResult: UploadResult | null;
  isUploading: boolean;

  // Actions
  fetchSystems: (params?: PaginationParams) => Promise<void>;
  fetchCurrentSystem: (systemId: string) => Promise<void>;
  createSystem: (data: CreateSystemRequest) => Promise<System>;
  updateSystem: (id: string, data: UpdateSystemRequest) => Promise<void>;
  deleteSystem: (id: string) => Promise<void>;
  fetchDocuments: (systemId: string, params?: DocumentFilterParams) => Promise<void>;
  fetchDocument: (documentId: string) => Promise<void>;
  updateDocumentType: (documentId: string, docType: DocType) => Promise<DocumentDetail>;
  uploadDocuments: (systemId: string, files: File[], docType?: DocType) => Promise<UploadResult>;
  clearUploadResult: () => void;
  clearCurrentSystem: () => void;
}

export const useKnowledgeStore = create<KnowledgeState>((set, get) => ({
  systems: [],
  systemsTotal: 0,
  systemsPage: 1,
  systemsPerPage: 20,
  systemsTotalPages: 0,
  systemsLoading: false,

  currentSystem: null,

  documents: [],
  documentsTotal: 0,
  documentsPage: 1,
  documentsPerPage: 20,
  documentsTotalPages: 0,
  documentsLoading: false,

  currentDocument: null,

  uploadResult: null,
  isUploading: false,

  fetchSystems: async (params?: PaginationParams) => {
    set({ systemsLoading: true });
    try {
      const data: PaginatedData<System> = await listSystems(params);
      set({
        systems: data.items,
        systemsTotal: data.total,
        systemsPage: data.page,
        systemsPerPage: data.per_page,
        systemsTotalPages: data.total_pages,
      });
    } finally {
      set({ systemsLoading: false });
    }
  },

  fetchCurrentSystem: async (systemId: string) => {
    const system = await getSystem(systemId);
    set({ currentSystem: system });
  },

  createSystem: async (data: CreateSystemRequest) => {
    const system = await createSystem(data);
    // 刷新列表
    const { systemsPage, systemsPerPage } = get();
    await get().fetchSystems({ page: systemsPage, per_page: systemsPerPage });
    return system;
  },

  updateSystem: async (id: string, data: UpdateSystemRequest) => {
    await updateSystem(id, data);
    const { systemsPage, systemsPerPage } = get();
    await get().fetchSystems({ page: systemsPage, per_page: systemsPerPage });
  },

  deleteSystem: async (id: string) => {
    await deleteSystem(id);
    const { systemsPage, systemsPerPage } = get();
    await get().fetchSystems({ page: systemsPage, per_page: systemsPerPage });
  },

  fetchDocuments: async (systemId: string, params?: DocumentFilterParams) => {
    set({ documentsLoading: true });
    try {
      const data: PaginatedData<Document> = await listDocuments(systemId, params);
      set({
        documents: data.items,
        documentsTotal: data.total,
        documentsPage: data.page,
        documentsPerPage: data.per_page,
        documentsTotalPages: data.total_pages,
      });
    } finally {
      set({ documentsLoading: false });
    }
  },

  fetchDocument: async (documentId: string) => {
    const doc = await getDocument(documentId);
    set({ currentDocument: doc });
  },

  updateDocumentType: async (documentId: string, docType: DocType) => {
    const doc = await updateDocumentType(documentId, docType);
    set((state) => ({
      currentDocument: state.currentDocument?.id === documentId ? doc : state.currentDocument,
      documents: state.documents.map((item) => (item.id === documentId ? { ...item, doc_type: doc.doc_type } : item)),
    }));
    return doc;
  },

  uploadDocuments: async (systemId: string, files: File[], docType: DocType = 'prd') => {
    set({ isUploading: true });
    try {
      const result = await batchUploadDocuments(systemId, files, docType);
      set({ uploadResult: result });
      return result;
    } finally {
      set({ isUploading: false });
    }
  },

  clearUploadResult: () => set({ uploadResult: null }),
  clearCurrentSystem: () => set({ currentSystem: null }),
}));
