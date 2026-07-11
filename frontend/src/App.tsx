import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import AuthGate from "./auth/AuthGate";
import Shell from "./layout/Shell";
import { Toaster } from "@/components/ui/sonner";
import DashboardPage from "./pages/DashboardPage";
import ForgotPasswordPage from "./pages/ForgotPasswordPage";
import ResetPasswordPage from "./pages/ResetPasswordPage";
import "./index.css";

/**
 * Route layout:
 *   /forgot-password    — public
 *   /reset-password     — public
 *   /                   — AuthGate → Dashboard (list projects, upload)
 *   /editor             — AuthGate → Editor (waveform, toolbar, panels)
 *   anything else       — redirect to /
 *
 * AuthGate is only wrapped around the two authenticated routes so the
 * password-recovery pages can render for anonymous users.
 */
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/forgot-password" element={<ForgotPasswordPage />} />
        <Route path="/reset-password" element={<ResetPasswordPage />} />
        <Route
          path="/"
          element={
            <AuthGate>
              <DashboardPage />
            </AuthGate>
          }
        />
        <Route
          path="/editor"
          element={
            <AuthGate>
              <Shell />
            </AuthGate>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <Toaster />
    </BrowserRouter>
  );
}
