import { Navigate, Route, Routes } from 'react-router-dom'
import { AppLayout } from './layouts/AppLayout'
import { DashboardPage, LoginPage, MistakesPage, PracticePage, ProgressPage, ProfilePage, ResearchPage } from './pages/Pages'
import { ProjectReviewHome } from './pages/ProjectReviewPage'
import { ResearchLabPage } from './pages/ResearchLabPage'

export default function App() {
  return <Routes>
    <Route path="/login" element={<LoginPage />} />
    <Route element={<AppLayout />}>
    <Route path="/" element={<Navigate to="/dashboard" replace />} />
    <Route path="/dashboard" element={<DashboardPage />} />
    <Route path="/practice" element={<PracticePage />} />
    <Route path="/progress" element={<ProgressPage />} />
    <Route path="/mistakes" element={<MistakesPage />} />
    <Route path="/profile" element={<ProfilePage />} />
    <Route path="/research" element={<ResearchPage mode="overview" />} />
    <Route path="/research/formula" element={<ResearchPage mode="formula" />} />
    <Route path="/research/evaluation" element={<ResearchPage mode="evaluation" />} />
    <Route path="/project-review" element={<ProjectReviewHome />} />
    <Route path="/project-review/research-lab" element={<ResearchLabPage />} />
    <Route path="*" element={<Navigate to="/dashboard" replace />} />
  </Route></Routes>
}
