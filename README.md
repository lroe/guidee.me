# Guidee

### The agentic AI tutor that teaches your notes the way you wrote them.

![Guidee lesson player showing a Hindi guidelet with an illustration, chapter outline, and tutor chat](docs/screenshots/main-page.jpeg)

Guidee turns notes, diagrams, quizzes, audio, video, and interactive games into **guidelets** — interactive textbooks taught by an agentic AI tutor. The creator owns the course structure; the AI brings it to life, one step at a time.

> **Status:** The hosted version at `guidee.me` is currently offline. You can run the project locally with the setup instructions below.

---

## Why we built this

Guidee started with a simple college habit: uploading notes to ChatGPT and asking it to tutor you. Studying that way is fun and active — you can keep asking questions until something finally clicks.

But two problems kept showing up:

1. **The AI might skip parts of the notes.** Important concepts got glossed over, and there was no guarantee the whole syllabus would be covered.
2. **The AI never showed the diagrams.** Images, figures, and videos in the notes were invisible to the tutor, so visual explanations were lost.

So we built the version of that experience we actually wanted: one where a human decides what is taught, in what order, with which diagram, and with which question — and an agentic AI tutor handles the teaching.

## The guidelet

A **guidelet** is an interactive textbook. Creators insert information, images, diagrams, audio, video, quizzes, and interactive games. The AI then teaches the material conversationally:

- It explains every concept the creator included — nothing gets skipped.
- It shows the creator's diagrams, images, and videos at the exact position they were placed.
- It asks the creator's questions at the right moment and responds to the learner's answers.
- It answers free-form learner questions using the full lesson as context.
- It remembers where the learner stopped and resumes from there.

The result is a course where **humans have total control of the structure**, while the AI handles the moment-to-moment teaching.

## What makes the tutor agentic?

A guidelet is not a PDF with a chat box bolted on. The tutor runs a stateful teaching loop:

1. **Observe** the learner's state — current chapter, step, prior chat, and question attempts.
2. **Decide** the next pedagogical action — explain content, present media, ask a question, or answer a learner question.
3. **Act** — generate a conversational explanation, display an image or video, or ask the next authored question.
4. **Evaluate** — grade multiple-choice and short-answer responses, give feedback, and offer hints.
5. **Update state** — advance the lesson, record XP, and persist progress for the next session.

Along the way, an intent classifier separates content questions from media requests ("show me that diagram again"), and lesson-aware retrieval keeps answers grounded in the creator's material. That observe → decide → act → evaluate → update loop is what makes Guidee's tutor **agentic** rather than a stateless chatbot.

## Features

- **Creator-defined courses** — build guidelets chapter by chapter with a lightweight authoring format.
- **Agentic AI tutor** — a stateful tutor that teaches the authored flow and answers questions with full lesson context.
- **Media in the right place** — images, diagrams, audio, and video appear exactly where the creator inserted them, and can be replayed on request.
- **Built-in understanding checks** — multiple-choice and short-answer questions, with AI evaluation, hints, and explanations.
- **Interactive games** — embed custom HTML/CSS/JS games directly inside a chapter.
- **Progress that persists** — chapter progress, chat history, and question attempts are saved per learner.
- **XP, streaks, and a growing tree** — learning activity earns XP, builds a monthly tree, and is preserved in a grove history.
- **Certificates** — learners receive a certificate after completing a guidelet.
- **Notebook** — save tutor explanations, add personal comments, and jump back to the original context.
- **Creator Studio** — upload assets, manage chapters, attach notes, preview lessons, and publish guidelets.
- **Semantic library search** — find guidelets by meaning, with a keyword fallback.
- **Community** — reviews, ratings, creator profiles, and following other learners.
- **Light and dark themes** — for comfortable reading and studying.

## See it in action

![A Python guidelet explaining problem-solving strategies next to a creator-uploaded diagram](docs/screenshots/lesson-page.jpeg)

*A chapter from "Algorithmic thinking with Python": the tutor explains problem-solving strategies alongside the diagram the creator placed, then waits for the learner to continue.*

## How a chapter is authored

Creators write a chapter in a simple script format. Guidee's parser turns it into typed steps (`CONTENT`, `MEDIA`, `QUESTION_MCQ`, `QUESTION_SA`, `INTERACTIVE_GAME`) that the tutor walks through in order.

```text
Problem-solving is about choosing the right strategy for the problem in front of you.

[IMAGE: description="A diagram comparing trial and error, heuristics, means-ends analysis, and backtracking" id="strategy-diagram"]

[QUESTION: Which strategy breaks a large goal into smaller sub-goals?
OPTIONS: A) Trial and error B) Heuristics C) Means-ends analysis D) Backtracking
ANSWER: C]

[QUESTION_SA: Why is it useful to know more than one problem-solving strategy?
KEYWORDS: adaptability, efficiency
REASON: Different problems need different approaches, and knowing several strategies helps you choose the quickest, most effective path.]
```

Media, questions, and games are placed by the creator, so the course structure never depends on the model's mood.

## Tech stack

| Layer | Built with |
| --- | --- |
| Web app | Python, Flask, Jinja2 |
| Data | SQLAlchemy, PostgreSQL (SQLite fallback), Alembic migrations |
| AI | Google Gemini (`gemini-2.0-flash`, `gemini-1.5-flash`) and `text-embedding-004` |
| Media | Cloudinary (images, audio, video, PDFs) |
| Frontend | Vanilla JavaScript and CSS, responsive themes |
| Auth | Google OAuth via Authlib, Flask-Login |

## Run it locally

```bash
git clone https://github.com/lroe/ultron.git
cd ultron
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file:

```dotenv
SECRET_KEY=change-me

# PostgreSQL, or omit to use a local SQLite database
DATABASE_URL=postgresql://user:password@localhost:5432/guidee

# AI
GEMINI_API_KEY=your-gemini-api-key

# Google OAuth
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret

# Cloudinary media storage
CLOUDINARY_CLOUD_NAME=your-cloud-name
CLOUDINARY_API_KEY=your-api-key
CLOUDINARY_API_SECRET=your-api-secret

# Optional: comma-separated guidelet IDs to feature on the explore page
FEATURED_GUIDELET_IDS=
```

Apply the database migrations and start the app:

```bash
flask db upgrade
flask run
```

The app runs at `http://localhost:5000`. Configure the Google OAuth callback for your local domain as well (the callback route is `/auth/callback/google`).

## Project structure

```text
app.py                 Flask app, data models, routes, and the agentic tutor loop
templates/             Jinja templates for the library, player, creator studio, and more
static/                CSS, JavaScript, images, and local uploads
migrations/            Alembic database migrations
docs/screenshots/      Product screenshots used in this README
requirements.txt       Python dependencies
```

