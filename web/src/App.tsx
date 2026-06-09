import { Suspense, lazy } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { Spin } from 'antd';
import MainLayout from './layouts/MainLayout';

// 路由懒加载
const SystemsPage = lazy(() => import('./pages/Systems'));
const KnowledgePage = lazy(() => import('./pages/Knowledge'));
const DocumentDetailPage = lazy(() => import('./pages/DocumentDetail'));
const WorkbenchPage = lazy(() => import('./pages/Workbench'));
const ExportsPage = lazy(() => import('./pages/Exports'));

const PageLoading = () => (
  <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '50vh' }}>
    <Spin size="large" />
  </div>
);

function App() {
  return (
    <Suspense fallback={<PageLoading />}>
      <Routes>
        <Route path="/" element={<MainLayout />}>
          <Route index element={<Navigate to="/systems" replace />} />
          <Route path="systems" element={<SystemsPage />} />
          <Route path="systems/:systemId/documents" element={<KnowledgePage />} />
          <Route path="documents/:documentId" element={<DocumentDetailPage />} />
          <Route path="batches/:batchId" element={<WorkbenchPage />} />
          <Route path="exports" element={<ExportsPage />} />
        </Route>
      </Routes>
    </Suspense>
  );
}

export default App;
