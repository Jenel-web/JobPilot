import { ControlsSidebar } from "@/components/shell/ControlsSidebar";
import { ControlsTopBar } from "@/components/shell/ControlsTopBar";
import { EngineDownBanner } from "@/components/shell/EngineDownBanner";
import { EngineProvider } from "@/components/shell/EngineProvider";
import { ToastProvider } from "@/components/ui/Toast";

/**
 * The v0 controls page shell: top bar, the 4-item sidebar and a scrolling main area
 * (design/screens/Fill.html, AnswerBank.html, History.html, Questions.html).
 * Every screen inside reads live data from the engine API; nothing here uses mock data.
 */
export default function ControlsLayout({ children }: { children: React.ReactNode }) {
  return (
    <ToastProvider>
      <EngineProvider>
        <div className="flex h-screen min-w-[1280px] flex-col overflow-hidden">
          <ControlsTopBar />
          <div className="flex min-h-0 flex-1">
            <ControlsSidebar />
            <main className="flex min-w-0 flex-1 flex-col gap-4 overflow-y-auto px-7 py-6">
              <EngineDownBanner />
              {children}
            </main>
          </div>
        </div>
      </EngineProvider>
    </ToastProvider>
  );
}
