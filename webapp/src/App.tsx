import { Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/layout/Layout';
import PipelineListPage from './pages/PipelineListPage';
import PipelineDesignerPage from './pages/PipelineDesignerPage';
import MonitorDashboardPage from './pages/MonitorDashboardPage';
import WorkItemListPage from './pages/WorkItemListPage';
import WorkItemDetailPage from './pages/WorkItemDetailPage';
import DefinitionListPage from './pages/DefinitionListPage';
import PluginMarketplacePage from './pages/PluginMarketplacePage';

function App() {
  return (
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<Navigate to="/pipelines" replace />} />
        <Route path="pipelines" element={<PipelineListPage />} />
        <Route path="pipelines/:id/designer" element={<PipelineDesignerPage />} />
        <Route path="monitor" element={<MonitorDashboardPage />} />
        <Route path="work-items" element={<WorkItemListPage />} />
        <Route path="work-items/:id" element={<WorkItemDetailPage />} />
        <Route path="definitions" element={<DefinitionListPage />} />
        <Route path="plugins" element={<PluginMarketplacePage />} />
      </Route>
    </Routes>
  );
}

export default App;
