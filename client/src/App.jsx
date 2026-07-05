import { BrowserRouter, Route, Routes } from 'react-router-dom'
import Capture from './pages/Capture.jsx'
import Login from './pages/Login.jsx'
import PostView from './pages/PostView.jsx'
import './app.css'

// M1 vertical-slice routes. Pages redirect to /login when an API call
// returns 401. Later milestones add the five screens: Inbox, Triage,
// Library, Report Editor, Export Preview — and only those five.
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<Capture />} />
        <Route path="/posts/:id" element={<PostView />} />
      </Routes>
    </BrowserRouter>
  )
}
