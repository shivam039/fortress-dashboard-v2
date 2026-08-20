# Fortress Frontend

This is the Next.js frontend for Fortress 95 Pro.

## Stack

- Next.js 16 App Router
- React 19
- TypeScript
- Recharts
- lucide-react

## Local Development

```bash
cd /Users/shivamdixit/Desktop/fortress-dashboard-main/frontend
npm install
npm run dev
```

The app runs at `http://localhost:3000`.

## Backend Connection

The frontend talks to the FastAPI backend through:

- `NEXT_PUBLIC_API_URL`
- `BACKEND_URL`
- fallback: `http://localhost:8000`

For local development, start the backend separately:

```bash
cd /Users/shivamdixit/Desktop/fortress-dashboard-main
source .venv/bin/activate
uvicorn engine.main:app --host 0.0.0.0 --port 8000
```

## Available Routes

- `/login`
- `/dashboard`
- `/screener`
- `/mf-lab`
- `/orders`
- `/commodities`
- `/options`
- `/history`
- `/profile`

## Build

```bash
npm run build
```

## Notes

- The frontend uses a cookie-based auth flow backed by the FastAPI backend.
- The UI is the production path; the old Streamlit UI is retained only as
  legacy reference code in the repository.

