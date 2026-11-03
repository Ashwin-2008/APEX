import { Navigate, Route, Routes } from 'react-router-dom'
import { AppLayout } from './layouts/AppLayout'
import { DashboardPage, MistakesPage, ProgressPage, ProfilePage, ResearchPage } from './pages/Pages'
import { ProjectReviewHome } from './pages/ProjectReviewPage'
import { ResearchLabPage } from './pages/ResearchLabPage'
import { LiveProjectReviewPage } from './pages/LiveProjectReviewPage'
import { LoginPage } from './pages/LoginPage'
import { WorkspaceDashboardPage } from './pages/WorkspaceDashboardPage'
import { ActivityFeedPage } from './pages/ActivityFeedPage'
import { SettingsPage } from './pages/SettingsPage'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<AppLayout />}>
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/projects" element={<WorkspaceDashboardPage />} />
        <Route path="/progress" element={<ProgressPage />} />
        <Route path="/mistakes" element={<MistakesPage />} />
        <Route path="/activity" element={<ActivityFeedPage />} />
        <Route path="/profile" element={<ProfilePage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/research" element={<ResearchPage mode="overview" />} />
        <Route path="/research/formula" element={<ResearchPage mode="formula" />} />
        <Route path="/research/evaluation" element={<ResearchPage mode="evaluation" />} />
        <Route path="/project-review" element={<LiveProjectReviewPage />} />
        <Route path="/project-review/report" element={<ProjectReviewHome />} />
        <Route path="/project-review/research-lab" element={<ResearchLabPage />} />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Route>
    </Routes>
  )
}
