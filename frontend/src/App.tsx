import { Route, Routes } from 'react-router-dom';
import { Layout } from './components/Layout';

// Pages are owned by other agents at their contract paths. Referenced here only.
import { ProjectsPage } from './pages/ProjectsPage';
import { ProjectDetailPage } from './pages/ProjectDetailPage';
import { TranscriptPage } from './pages/TranscriptPage';
import { ApprovalsPage } from './pages/ApprovalsPage';
import { NotFoundPage } from './pages/NotFoundPage';

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<ProjectsPage />} />
        <Route path="projects/:projectId" element={<ProjectDetailPage />} />
        <Route path="meetings/:meetingId" element={<TranscriptPage />} />
        <Route path="approvals" element={<ApprovalsPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}

export default App;
