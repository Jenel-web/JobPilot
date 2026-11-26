import { ShellProvider } from "@/components/shell/ShellProvider";
import { Sidebar } from "@/components/shell/Sidebar";
import { StoppedBanner } from "@/components/shell/StoppedBanner";
import { TopBar } from "@/components/shell/TopBar";
import { ToastProvider } from "@/components/ui/Toast";

/**
 * The app shell shared by every screen except Onboarding: top bar, sidebar,
 * and a scrolling main area (design/screens/Patterns.html).
 */
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <ToastProvider>
      <ShellProvider>
        <div className="flex h-screen min-w-[1280px] flex-col overflow-hidden">
          <TopBar />
          <div className="flex min-h-0 flex-1">
            <Sidebar />
            <main className="flex min-w-0 flex-1 flex-col gap-[18px] overflow-y-auto px-7 py-6">
              <StoppedBanner />
              {children}
            </main>
          </div>
        </div>
      </ShellProvider>
    </ToastProvider>
  );
}
