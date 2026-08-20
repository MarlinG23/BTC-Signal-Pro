import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { LiveDataProvider } from "./context/LiveDataContext";
import { AppLayout } from "./layout/AppLayout";
import { LivePage } from "./pages/LivePage";
import { IndicatorsPage } from "./pages/IndicatorsPage";
import { HistoryPage } from "./pages/HistoryPage";
import { NewsPage } from "./pages/NewsPage";
import { ResearchPage } from "./pages/ResearchPage";

export default function App() {
  return (
    <BrowserRouter>
      <LiveDataProvider>
        <Routes>
          <Route element={<AppLayout />}>
            <Route path="/" element={<LivePage />} />
            <Route path="/indicators" element={<IndicatorsPage />} />
            <Route path="/history" element={<HistoryPage />} />
            <Route path="/news" element={<NewsPage />} />
            <Route path="/research" element={<ResearchPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </LiveDataProvider>
    </BrowserRouter>
  );
}
