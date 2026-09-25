import { useEffect } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import ProtectedRoute from './components/ProtectedRoute'
import ChatPage from './pages/ChatPage'
import KnowledgeListPage from './pages/KnowledgeListPage'
import KnowledgeSpacePage from './pages/KnowledgeSpacePage'
import KnowledgeImportPage from './pages/KnowledgeImportPage'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import SettingsPage from './pages/SettingsPage'
import DatasetCreatePage from './pages/ml/DatasetCreatePage'
import DatasetDetailPage from './pages/ml/DatasetDetailPage'
import DatasetListPage from './pages/ml/DatasetListPage'
import EvalCreatePage from './pages/ml/EvalCreatePage'
import EvalDetailPage from './pages/ml/EvalDetailPage'
import EvalDimensionCreatePage from './pages/ml/EvalDimensionCreatePage'
import EvalListPage from './pages/ml/EvalListPage'
import LeaderboardDetailPage from './pages/ml/LeaderboardDetailPage'
import ModelFilesPage from './pages/ml/ModelFilesPage'
import ModelImportPage from './pages/ml/ModelImportPage'
import ModelListPage from './pages/ml/ModelListPage'
import TuneCreatePage from './pages/ml/TuneCreatePage'
import TuneListPage from './pages/ml/TuneListPage'
import TuneOutputPage from './pages/ml/TuneOutputPage'
import { useAuthStore } from './store/auth'

export default function App() {
  const fetchMe = useAuthStore((s) => s.fetchMe)

  useEffect(() => {
    fetchMe()
  }, [fetchMe])

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />

        <Route element={<ProtectedRoute />}>
          <Route element={<Layout />}>
            <Route path="/" element={<KnowledgeListPage />} />
            <Route path="/knowledge/:spaceId" element={<KnowledgeSpacePage />} />
            <Route path="/knowledge/:spaceId/import" element={<KnowledgeImportPage />} />
            <Route path="/chat" element={<ChatPage />} />
            <Route path="/ml/datasets" element={<DatasetListPage />} />
            <Route path="/ml/datasets/new" element={<DatasetCreatePage />} />
            <Route path="/ml/datasets/:id" element={<DatasetDetailPage />} />
            <Route path="/ml/models" element={<ModelListPage />} />
            <Route path="/ml/models/import" element={<ModelImportPage />} />
            <Route path="/ml/models/:id/files" element={<ModelFilesPage />} />
            <Route path="/ml/tune" element={<TuneListPage />} />
            <Route path="/ml/tune/new" element={<TuneCreatePage />} />
            <Route path="/ml/tune/output/:taskId" element={<TuneOutputPage />} />
            <Route path="/ml/eval" element={<EvalListPage />} />
            <Route path="/ml/eval/new" element={<EvalCreatePage />} />
            <Route path="/ml/eval/dimension/new" element={<EvalDimensionCreatePage />} />
            <Route path="/ml/eval/dimension/:dimensionId" element={<EvalDimensionCreatePage />} />
            <Route path="/ml/leaderboard/:leaderboardId" element={<LeaderboardDetailPage />} />
            <Route path="/ml/eval/:taskId" element={<EvalDetailPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Route>
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
