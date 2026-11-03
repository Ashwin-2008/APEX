import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { createStudent, getStudent } from '../api/students'
import type { Student } from '../types/entities'

interface StudentContextValue {
  student: Student | null
  ready: boolean
  restoreError: string
  enter: (name: string) => Promise<void>
  reconnect: (id: number) => Promise<void>
  leave: () => void
}
const StudentContext = createContext<StudentContextValue | null>(null)
const STORAGE_KEY = 'mistiq.development.studentId'

export function StudentProvider({ children }: { children: ReactNode }) {
  const [student, setStudent] = useState<Student | null>(null)
  const [ready, setReady] = useState(false)
  const [restoreError, setRestoreError] = useState('')
  useEffect(() => {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (!saved) { setReady(true); return }
    getStudent(Number(saved)).then(setStudent).catch(() => {
      localStorage.removeItem(STORAGE_KEY)
      setRestoreError('ApexIQ could not restore your student profile. Check that the backend is running, then reconnect with your student ID.')
    }).finally(() => setReady(true))
  }, [])

  const attach = (next: Student) => {
    localStorage.setItem(STORAGE_KEY, String(next.id))
    setStudent(next)
  }
  const value = useMemo<StudentContextValue>(() => ({
    student, ready,
    restoreError,
    enter: async (name) => { const next = await createStudent(name); setRestoreError(''); attach(next) },
    reconnect: async (id) => { const next = await getStudent(id); setRestoreError(''); attach(next) },
    leave: () => { localStorage.removeItem(STORAGE_KEY); setStudent(null) },
  }), [student, ready, restoreError])
  return <StudentContext.Provider value={value}>{children}</StudentContext.Provider>
}

export function useStudent() {
  const value = useContext(StudentContext)
  if (!value) throw new Error('useStudent must be used inside StudentProvider')
  return value
}
