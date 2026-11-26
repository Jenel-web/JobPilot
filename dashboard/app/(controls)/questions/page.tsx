import { Suspense } from "react";
import { QuestionsScreen } from "@/components/questions/QuestionsScreen";
import { PageHeader } from "@/components/ui/PageHeader";

export const metadata = { title: "Questions · JobPilot" };

/** Questions: Waiting | Wordings | Answered. The screen reads ?tab= and ?id=, so it sits in a Suspense boundary. */
export default function QuestionsPage() {
  return (
    <Suspense fallback={<PageHeader title="Questions" subtitle="Loading…" />}>
      <QuestionsScreen />
    </Suspense>
  );
}
