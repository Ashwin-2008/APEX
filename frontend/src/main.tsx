import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import './styles/index.css'
import { StudentProvider } from './context/StudentContext'
import { ThemeProvider } from './context/ThemeContext'
import { ProjectProvider } from './context/ProjectContext'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <ThemeProvider>
        <StudentProvider>
          <ProjectProvider>
            <App />
          </ProjectProvider>
        </StudentProvider>
      </ThemeProvider>
    </BrowserRouter>
  </React.StrictMode>,
)
