/** MOCK DATA: the Review batch queue (9 applications, 6 emails, 3 flagged). Sample data only. */

import type { JobType, ResumeId } from "../types";

/** Where a filled answer came from. "ai" answers are flagged for the user to check. */
export type AnswerSource = "profile" | "bank" | "local" | "ai";

export type FilledAnswer = { question: string; answer: string; source: AnswerSource };

export type Contact = { name: string; title: string; foundVia: string };

export type EmailDraft = { tier: "Personal" | "Short"; subject: string; body: string; factsUsed: string[] };

export type ReviewItem = {
  id: string;
  title: string;
  company: string;
  location: string;
  type: JobType;
  posted: string;
  score: number;
  resume: ResumeId;
  resumeReason: string;
  reasons: string[];
  missing: string[];
  answers: FilledAnswer[];
  /** Null = "No verified contact found". */
  contact: Contact | null;
  email: EmailDraft | null;
};

export const resumeNames: Record<ResumeId, string> = { A: "Web", B: "Mobile" };

/** Answers every form asks; the per-job AI guesses are added on top. */
const common: FilledAnswer[] = [
  { question: "Hours per week", answer: "40", source: "profile" },
  { question: "Phone", answer: "●●●● 1234", source: "local" },
];

const guess = (question: string, answer: string): FilledAnswer => ({ question, answer, source: "ai" });

const personalEmail = (company: string, role: string, project: string): EmailDraft => ({
  tier: "Personal",
  subject: `Interested in the ${role} role at ${company}`,
  body:
    `Hi, I'm a third-year CS student at PUP and I just applied for the ${role} role at ${company}. ` +
    `I recently built ${project}, which is close to the work in the post. ` +
    `Could I ask who is reviewing applications for this role? Thank you for your time.`,
  factsUsed: [`Project: ${project}`, "Third-year CS student at PUP"],
});

const shortEmail = (company: string, role: string): EmailDraft => ({
  tier: "Short",
  subject: `Applied: ${role}`,
  body: `Hi, I applied for the ${role} role at ${company} today and wanted to say I'm very interested. Thank you!`,
  factsUsed: ["Third-year CS student at PUP"],
});

// Sorted by score, highest first.
export const reviewQueue: ReviewItem[] = [
  {
    id: "acme",
    title: "Junior Full Stack Developer",
    company: "Acme PH",
    location: "Makati",
    type: "Internship",
    posted: "3 days ago",
    score: 86,
    resume: "A",
    resumeReason: "the post mentions React.",
    reasons: ["Uses React and Spring Boot, both in your projects.", "Internship, junior level and in Metro Manila."],
    missing: ["Docker", "AWS"],
    answers: [{ question: "Available start date", answer: "December 2026", source: "bank" }, ...common],
    contact: { name: "Maria Santos", title: "Talent Acquisition Lead", foundVia: "Google search → LinkedIn profile title" },
    email: personalEmail("Acme PH", "Junior Full Stack Developer", "a Pag-IBIG savings tracker in React"),
  },
  {
    id: "kumu",
    title: "Web Developer Intern",
    company: "Kumu",
    location: "Remote",
    type: "Internship",
    posted: "1 day ago",
    score: 80,
    resume: "A",
    resumeReason: "the stack is JavaScript and React.",
    reasons: ["React and TypeScript match your web projects.", "Remote internships are in your preferences."],
    missing: ["GraphQL"],
    answers: [{ question: "Expected monthly salary", answer: "USD 600", source: "bank" }, ...common],
    contact: { name: "Paolo Reyes", title: "Engineering Manager", foundVia: "Google search → company team page" },
    email: personalEmail("Kumu", "Web Developer Intern", "a movie booking site in React"),
  },
  {
    id: "pulse",
    title: "Frontend Developer",
    company: "Pulse Labs",
    location: "Mandaluyong",
    type: "Full-time",
    posted: "5 days ago",
    score: 76,
    resume: "A",
    resumeReason: "the role is web frontend.",
    reasons: ["Strong overlap with React and CSS.", "Full-time is slightly above your usual level."],
    missing: ["Testing experience", "Figma"],
    answers: [guess("Available start date", "January 2027"), ...common],
    contact: { name: "Ana Cruz", title: "Recruiter", foundVia: "Google search → LinkedIn profile title" },
    email: shortEmail("Pulse Labs", "Frontend Developer"),
  },
  {
    id: "appify",
    title: "Data Analyst Intern",
    company: "Appify",
    location: "Taguig",
    type: "Internship",
    posted: "2 days ago",
    score: 72,
    resume: "A",
    resumeReason: "Python and SQL appear in Resume A's skills.",
    reasons: ["SQL and Python match your coursework.", "No data projects yet, so the match is partial."],
    missing: ["Tableau", "Statistics"],
    answers: [
      guess("Expected monthly salary", "PHP 18,000"),
      guess("Available start date", "December 2026"),
      ...common,
    ],
    contact: { name: "Liza Ramos", title: "HR Lead", foundVia: "Google search → LinkedIn profile title" },
    email: shortEmail("Appify", "Data Analyst Intern"),
  },
  {
    id: "taguigtech",
    title: "Junior Developer",
    company: "Taguig Tech",
    location: "Taguig",
    type: "Part-time",
    posted: "4 days ago",
    score: 68,
    resume: "A",
    resumeReason: "the stack is Java and web.",
    reasons: ["Java matches your coursework.", "Part-time hours fit your class schedule."],
    missing: ["Spring Security"],
    answers: [{ question: "Available start date", answer: "December 2026", source: "bank" }, ...common],
    contact: null,
    email: null,
  },
  {
    id: "orbit",
    title: "Flutter Developer Intern",
    company: "Orbit Studio",
    location: "Quezon City",
    type: "Internship",
    posted: "1 day ago",
    score: 66,
    resume: "B",
    resumeReason: "Flutter is the main skill asked for.",
    reasons: ["Flutter is the core of your mobile resume.", "The studio ships mobile apps only."],
    missing: ["Firebase"],
    answers: [guess("Do you have your own laptop?", "Yes"), ...common],
    contact: { name: "Mika Dela Cruz", title: "Talent Partner", foundVia: "Google search → LinkedIn profile title" },
    email: shortEmail("Orbit Studio", "Flutter Developer Intern"),
  },
  {
    id: "brightside",
    title: "Software Engineer Trainee",
    company: "Brightside PH",
    location: "Ortigas",
    type: "Full-time",
    posted: "6 days ago",
    score: 64,
    resume: "A",
    resumeReason: "the trainee program is general software.",
    reasons: ["Training program suits a fresh graduate."],
    missing: ["C#", "Azure"],
    answers: [{ question: "Available start date", answer: "June 2027", source: "bank" }, ...common],
    contact: null,
    email: null,
  },
  {
    id: "lumina",
    title: "QA Intern",
    company: "Lumina Health",
    location: "BGC",
    type: "Internship",
    posted: "3 days ago",
    score: 61,
    resume: "A",
    resumeReason: "the role is closest to web projects.",
    reasons: ["Testing is a stretch, but web knowledge helps."],
    missing: ["Selenium", "Test plans"],
    answers: [{ question: "Available start date", answer: "December 2026", source: "bank" }, ...common],
    contact: null,
    email: null,
  },
  {
    id: "kanaya",
    title: "Mobile Developer Intern",
    company: "Kanaya",
    location: "Pasig",
    type: "Internship",
    posted: "2 days ago",
    score: 60,
    resume: "B",
    resumeReason: "the post asks for Flutter or Kotlin.",
    reasons: ["Flutter matches Resume B.", "Small team, so less guidance."],
    missing: ["Kotlin"],
    answers: [{ question: "Available start date", answer: "December 2026", source: "bank" }, ...common],
    contact: { name: "James Tan", title: "Hiring Manager", foundVia: "Google search → company team page" },
    email: shortEmail("Kanaya", "Mobile Developer Intern"),
  },
];

/** Jobs that start the mock session already approved (so "Submit approved (5)" matches the mockup). */
export const initiallyApproved: string[] = ["acme", "kumu", "taguigtech", "brightside", "lumina"];
