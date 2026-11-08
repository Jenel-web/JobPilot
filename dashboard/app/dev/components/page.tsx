import { ToastProvider } from "@/components/ui/Toast";
import { ComponentsDemo } from "./ComponentsDemo";

export const metadata = { title: "Components · JobPilot" };

/** Dev-only page: all shared components, to compare with design/screens/Components.html. */
export default function ComponentsPage() {
  return (
    <ToastProvider>
      <div className="min-h-screen px-16 py-14">
        <ComponentsDemo />
      </div>
    </ToastProvider>
  );
}
