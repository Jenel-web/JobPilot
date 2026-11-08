/** MOCK DATA for the Applications tracker. Sample rows only (same samples as design/screens/Applications.html). */

import type { JobType, ResumeId, Status } from "../types";

export type EmailState = "Sent ✓" | "Queued" | "Bounced" | "None";

export type TimelineEvent = { date: string; text: string };

export type AppRow = {
  id: string;
  /** Short date shown in the table, e.g. "Nov 12". */
  date: string;
  company: string;
  role: string;
  location: string;
  type: JobType;
  score: number;
  resume: ResumeId;
  email: EmailState;
  status: Status;
  contact: string | null;
  /** Why JobPilot could not apply itself (Needs manual apply tab). */
  manualReason: string | null;
  timeline: TimelineEvent[];
  notes: string;
  emailLine: string | null;
  answers: Array<{ question: string; answer: string }>;
};

const answers = [
  { question: "Available start date", answer: "December 2026" },
  { question: "Hours per week", answer: "40" },
];

export const applications: AppRow[] = [
  {
    id: "acme", date: "Nov 12", company: "Acme PH", role: "Junior Full Stack Dev", location: "Makati", type: "Internship",
    score: 86, resume: "A", email: "Sent ✓", status: "submitted", contact: "Maria Santos", manualReason: null,
    timeline: [
      { date: "Nov 11", text: "Found on Prosple" }, { date: "Nov 11", text: "Scored 86" },
      { date: "Nov 12", text: "Queued, then approved by you" }, { date: "Nov 12", text: "Submitted, email sent to Maria Santos" },
    ],
    notes: "", emailLine: "To Maria Santos, Talent Acquisition Lead · ✓ Sent 2:31 PM", answers,
  },
  {
    id: "appify", date: "Nov 11", company: "Appify", role: "Data Analyst Intern", location: "Taguig", type: "Internship",
    score: 72, resume: "B", email: "Sent ✓", status: "interview", contact: "Liza Ramos", manualReason: null,
    timeline: [
      { date: "Nov 9", text: "Found on Prosple" }, { date: "Nov 9", text: "Scored 72" },
      { date: "Nov 10", text: "Queued, then approved by you" }, { date: "Nov 11", text: "Submitted, email sent to Liza Ramos" },
      { date: "Nov 14", text: "Recruiter replied in Gmail, status set to Interview by you" },
    ],
    notes: "Interview Nov 20, 10 AM, Google Meet", emailLine: "To Liza Ramos, HR Lead · ✓ Sent 2:31 PM", answers,
  },
  {
    id: "kanaya", date: "Nov 11", company: "Kanaya", role: "Mobile Developer Intern", location: "Pasig", type: "Internship",
    score: 58, resume: "B", email: "None", status: "manual", contact: null, manualReason: "Field not found",
    timeline: [{ date: "Nov 11", text: "Found on Prosple" }, { date: "Nov 11", text: "Scored 58" }, { date: "Nov 11", text: "Form field not found, marked manual" }],
    notes: "", emailLine: null, answers: [],
  },
  {
    id: "kumu", date: "Nov 10", company: "Kumu", role: "Web Developer Intern", location: "Remote", type: "Internship",
    score: 84, resume: "A", email: "Queued", status: "failed", contact: "Paolo Reyes", manualReason: null,
    timeline: [
      { date: "Nov 9", text: "Found on Prosple" }, { date: "Nov 9", text: "Scored 84" }, { date: "Nov 10", text: "Approved by you" },
      { date: "Nov 10", text: "Submit not confirmed by Prosple, marked failed (never resubmitted automatically)" },
    ],
    notes: "", emailLine: "To Paolo Reyes, Engineering Manager · Queued (held until the application is confirmed)", answers,
  },
  {
    id: "pulse", date: "Nov 9", company: "Pulse Labs", role: "Frontend Intern", location: "Mandaluyong", type: "Internship",
    score: 68, resume: "A", email: "Sent ✓", status: "rejected", contact: "Ana Cruz", manualReason: null,
    timeline: [{ date: "Nov 8", text: "Found on Prosple" }, { date: "Nov 9", text: "Submitted, email sent to Ana Cruz" }, { date: "Nov 13", text: "Rejection email, status set by you" }],
    notes: "", emailLine: "To Ana Cruz, Recruiter · ✓ Sent 10:12 AM", answers,
  },
  {
    id: "partner", date: "Nov 9", company: "Prosple partner", role: "Mobile Dev, Flutter", location: "Remote", type: "Part-time",
    score: 81, resume: "B", email: "None", status: "manual", contact: null, manualReason: "External site",
    timeline: [{ date: "Nov 9", text: "Found on Prosple" }, { date: "Nov 9", text: "Scored 81" }, { date: "Nov 9", text: "Redirects to an employer site, marked manual" }],
    notes: "", emailLine: null, answers: [],
  },
  {
    id: "taguigtech", date: "Nov 8", company: "Taguig Tech", role: "Junior Developer", location: "Taguig", type: "Full-time",
    score: 80, resume: "A", email: "Sent ✓", status: "submitted", contact: "Rico Lim", manualReason: null,
    timeline: [{ date: "Nov 7", text: "Found on Prosple" }, { date: "Nov 8", text: "Submitted, email sent to Rico Lim" }],
    notes: "", emailLine: "To Rico Lim, Engineering Lead · ✓ Sent 9:45 AM", answers,
  },
  {
    id: "orbit", date: "Nov 8", company: "Orbit Studio", role: "Flutter Intern", location: "Quezon City", type: "Internship",
    score: 77, resume: "B", email: "Sent ✓", status: "submitted", contact: "Mika Dela Cruz", manualReason: null,
    timeline: [{ date: "Nov 7", text: "Found on Prosple" }, { date: "Nov 8", text: "Submitted, email sent to Mika Dela Cruz" }],
    notes: "", emailLine: "To Mika Dela Cruz, Talent Partner · ✓ Sent 9:50 AM", answers,
  },
  {
    id: "lumina", date: "Nov 7", company: "Lumina Health", role: "QA Intern", location: "BGC", type: "Internship",
    score: 61, resume: "A", email: "Bounced", status: "submitted", contact: "Grace Ong", manualReason: null,
    timeline: [{ date: "Nov 6", text: "Found on Prosple" }, { date: "Nov 7", text: "Submitted, email sent to Grace Ong" }, { date: "Nov 7", text: "Email bounced, contact marked invalid" }],
    notes: "", emailLine: "To Grace Ong, HR Officer · ✕ Bounced (mailbox not found). Contact marked invalid.", answers,
  },
  {
    id: "brightside", date: "Nov 7", company: "Brightside PH", role: "Software Engineer Trainee", location: "Ortigas", type: "Full-time",
    score: 64, resume: "A", email: "None", status: "manual", contact: null, manualReason: "CAPTCHA",
    timeline: [{ date: "Nov 7", text: "Found on Prosple" }, { date: "Nov 7", text: "CAPTCHA on the form, marked manual" }],
    notes: "", emailLine: null, answers: [],
  },
  {
    id: "northwind", date: "Nov 6", company: "Northwind Labs", role: "Backend Intern", location: "Makati", type: "Internship",
    score: 74, resume: "A", email: "Sent ✓", status: "submitted", contact: "Leo Garcia", manualReason: null,
    timeline: [{ date: "Nov 5", text: "Found on Prosple" }, { date: "Nov 6", text: "Submitted, email sent to Leo Garcia" }],
    notes: "", emailLine: "To Leo Garcia, Engineering Manager · ✓ Sent 11:05 AM", answers,
  },
  {
    id: "cloudly", date: "Nov 5", company: "Cloudly", role: "Support Engineer Intern", location: "Remote", type: "Internship",
    score: 66, resume: "A", email: "None", status: "failed", contact: null, manualReason: null,
    timeline: [{ date: "Nov 5", text: "Found on Prosple" }, { date: "Nov 5", text: "Page failed to load while filling, marked failed" }],
    notes: "", emailLine: null, answers,
  },
  {
    id: "bytewise", date: "Nov 4", company: "Bytewise", role: "Junior Web Developer", location: "Pasig", type: "Full-time",
    score: 83, resume: "A", email: "Sent ✓", status: "offer", contact: "Nina Flores", manualReason: null,
    timeline: [{ date: "Nov 1", text: "Found on Prosple" }, { date: "Nov 2", text: "Submitted, email sent to Nina Flores" }, { date: "Nov 3", text: "Interview done" }, { date: "Nov 4", text: "Offer received, status set by you" }],
    notes: "Reply by Nov 8.", emailLine: "To Nina Flores, HR Manager · ✓ Sent 3:20 PM", answers,
  },
];

export const STATUS_ORDER: Status[] = ["new", "queued", "approved", "submitted", "manual", "failed", "rejected", "interview", "offer"];
