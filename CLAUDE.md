# CLAUDE.md — CompareKaro: Product Comparison & Purchase Agent

## Product Vision

CompareKaro is a **product comparison and purchase agent** that:
1. Takes a product name (or URL) from the user
2. Searches Amazon.in AND Flipkart.com for that product
3. Shows a side-by-side comparison: price, specs, ratings, delivery
4. Asks which platform the user wants to buy from
5. (Future) Opens the product page and assists with purchasing

This is NOT a study app. It is purely a shopping comparison tool.

---

## Tech Stack
- **Backend**: FastAPI, LangGraph, LangChain, OpenAI (gpt-4o-mini), SerpAPI, Supabase, Clerk Auth
- **Frontend**: Next.js 14+ (App Router), Clerk, Tailwind CSS
- **Database**: Supabase (PostgreSQL) — tables: users, conversations, messages

## Project Structure
```
backend/
├── main.py                    # FastAPI app — /api/compare, /api/compare/stream, /api/conversations
├── config.py                  # Settings from .env
├── agent/
│   ├── __init__.py
│   └── compare_agent.py       # ⭐ Core comparison agent (SerpAPI + LangGraph)
├── services/
│   └── ai.py                  # Legacy chat agent (can be removed later)
├── auth/
│   └── clerk.py               # Clerk JWT verification
├── db/
│   └── supabase.py            # Supabase CRUD — users, conversations, messages
├── test_agent.py              # Agent test suite (6 checks)
├── debug_serpapi.py            # SerpAPI debug tool
└── .env

frontend/
├── app/
│   ├── page.tsx               # Main page with Compare mode
│   └── components/
│       ├── CompareView.tsx     # Compare UI — input, progress, results
│       └── MessageContent.tsx  # Markdown renderer
├── lib/
│   └── api.ts                 # API client — compareProductsStream, etc.
└── .env.local                 # NEXT_PUBLIC_API_URL=http://localhost:8000
```

---

## ⚠️ CRITICAL BUG — FIX THIS FIRST

### Problem
The comparison agent returns "No products found on either platform" for EVERY query.

### Root Cause
`agent/compare_agent.py` uses SerpAPI's `google_shopping` engine with queries like `"iPhone 15 amazon.in"`,
then post-filters results checking if "amazon" or "flipkart" appears in the `source` or `link` fields.

**This fails because:**
- Google Shopping in India does NOT reliably include Amazon.in or Flipkart as sources
- Shopping results use Google redirect URLs, not direct store links
- The post-filter finds zero matches → falls back → but fallback also returns irrelevant results

### The Fix — Switch from Google Shopping to Google Web Search with site: operator

Replace the `_search_shopping()` function in `agent/compare_agent.py` with this approach:

```python
def _search_shopping(query: str, source_filter: str) -> list[ProductInfo]:
    """
    Search for products on a specific platform using Google Web Search
    with site: operator. This works reliably for Indian e-commerce.
    """
    from serpapi import GoogleSearch

    domain = "amazon.in" if source_filter == "amazon" else "flipkart.com"
    search_query = f"site:{domain} {query} price"

    try:
        search = GoogleSearch({
            "engine": "google",           # ← Regular Google, NOT google_shopping
            "q": search_query,
            "location": "India",
            "gl": "in",
            "hl": "en",
            "api_key": _serpapi_key(),
            "num": 5,
        })
        data = search.get_dict()

        products: list[ProductInfo] = []
        for item in data.get("organic_results", []):
            title = item.get("title", "")
            link = item.get("link", "")
            snippet = item.get("snippet", "")

            # Extract price from snippet or rich_snippet
            price = "See link"
            extracted_price = None

            # Try rich snippet first
            rich = item.get("rich_snippet", {})
            top = rich.get("top", {})
            if "detected_extensions" in top:
                ext = top["detected_extensions"]
                if "price" in ext:
                    price = ext["price"]

            # Try to find price pattern in snippet (₹XX,XXX or Rs. XX,XXX)
            if price == "See link":
                import re
                price_match = re.search(r'[₹₨][\s]?[\d,]+(?:\.\d{2})?|Rs\.?\s*[\d,]+', snippet)
                if price_match:
                    price = price_match.group(0)

            # Try extracted_price from rich snippet
            if "price" in item:
                price = item["price"]

            products.append(ProductInfo(
                name=title,
                price=price,
                extracted_price=extracted_price,
                rating=None,
                rating_count="",
                source=source_filter,
                url=link,
                image=item.get("thumbnail", ""),
                specs={},
                delivery="",
            ))

            if len(products) >= 5:
                break

        return products

    except Exception as e:
        print(f"[SerpAPI] {source_filter} search error: {e}")
        return []
```

**Key changes:**
1. Uses `engine: "google"` instead of `engine: "google_shopping"`
2. Uses `site:amazon.in` / `site:flipkart.com` in the query — this guarantees results from the right platform
3. Parses `organic_results` instead of `shopping_results`
4. Extracts prices from snippets using regex
5. No post-filtering needed — results are already from the correct site

### Also update `_search_product_url()` similarly
When user provides a URL, search Google for that URL and extract info from organic results.
The current implementation is fine for this.

### Validation After Fix
```bash
python -c "
from agent.compare_agent import _search_shopping
a = _search_shopping('iPhone 15', 'amazon')
f = _search_shopping('iPhone 15', 'flipkart')
print(f'Amazon: {len(a)} results')
for p in a[:2]: print(f'  {p[\"name\"][:60]} — {p[\"price\"]} — {p[\"url\"][:50]}')
print(f'Flipkart: {len(f)} results')
for p in f[:2]: print(f'  {p[\"name\"][:60]} — {p[\"price\"]} — {p[\"url\"][:50]}')
"
```
Should print 3-5 results per platform with actual Amazon.in and Flipkart.com URLs.

### Test queries that must work after the fix:
- "iPhone 15"
- "OnePlus 12"  
- "boAt Rockerz 450"
- "keychron mechanical keyboard"
- "Samsung Galaxy S24"
- "Sony WH-1000XM5"

---

## Known Issues (Fix After Critical Bug)

### 1. Tavily Deprecation Warning
**File**: `services/ai.py`
**Fix**: `pip install -U langchain-tavily`, then change import to `from langchain_tavily import TavilySearch`

### 2. DEV_MODE Auth Bypass
**File**: `main.py` → `_get_email()` function
**Need**: When `DEV_MODE=true` in .env and no Authorization header, return `"dev@localhost.test"` instead of 401.
**Important**: Remove before deploying to production.

### 3. Legacy StudyBuddy Code
**Files**: `services/ai.py` — this is the old chat/study assistant.
**Status**: Keep for now as backward compatibility but the primary feature is comparison.
**Future**: Remove entirely once comparison is stable and purchase flow is added.

---

## Agent Architecture

### Compare Agent Graph (`agent/compare_agent.py`)
```
parse_input → [route]
                ├─ URLs detected    → extract_from_urls ─┐
                └─ Natural language → search_products    ─┤
                                                          ▼
                                               compare_products → format_output → END
```

**Nodes:**
- `parse_input`: Detect URLs vs text. If text, use LLM to extract clean product name.
- `search_products`: Call `_search_shopping(query, "amazon")` + `_search_shopping(query, "flipkart")`
- `extract_from_urls`: Lookup URL via SerpAPI, fill in the missing platform by searching
- `compare_products`: Send both product lists to GPT → generates markdown comparison table + analysis
- `format_output`: Combine header + analysis + product links into final markdown

### Streaming Flow
The `compare_products_stream()` function runs parse + search synchronously (fast), 
then streams the LLM synthesis token-by-token via OpenAI SDK for real-time UX.

Progress indicators sent as SSE chunks:
```
🔍 Searching Amazon & Flipkart...
🔎 Searching for: **iPhone 15**
✅ Found 5 Amazon & 4 Flipkart results. Generating comparison...
[streamed markdown comparison]
```

---

## API Endpoints

| Method | Path | Auth | Body | Description |
|--------|------|------|------|-------------|
| GET | `/health` | No | — | Health check |
| POST | `/api/compare` | Yes | `{"query": "..."}` | Compare (non-streaming) |
| POST | `/api/compare/stream` | Yes | `{"query": "..."}` | Compare (SSE streaming) |
| POST | `/api/ask` | Yes | `{"question": "..."}` | Legacy chat (kept for compat) |
| POST | `/api/ask/stream` | Yes | `{"question": "..."}` | Legacy chat streaming |
| GET | `/api/conversations` | Yes | — | List conversations |
| GET | `/api/conversations/{id}/messages` | Yes | — | Get messages |

**SSE Protocol** (same for both ask and compare streaming):
```
data: {"content": "chunk of text"}
data: {"done": true, "conversation_id": "uuid"}
```

---

## Database Schema (Supabase)

```sql
create table public.users (
  id uuid primary key default gen_random_uuid(),
  email text not null unique,
  created_at timestamptz not null default now()
);

create table public.conversations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users(id) on delete cascade,
  created_at timestamptz not null default now()
);

create table public.messages (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.conversations(id) on delete cascade,
  question text not null,
  answer text not null,
  created_at timestamptz not null default now()
);
```
Compare queries stored as: `question = "[Compare] iPhone 15"`

---

## Environment Variables (.env)

```
# Required
OPENAI_API_KEY=sk-...
SERPAPI_API_KEY=...

# Supabase
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJ...

# Clerk Auth
CLERK_SECRET_KEY=sk_...
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_...

# Optional
TAVILY_API_KEY=tvly-...          # Only for legacy chat mode
DEV_MODE=true                    # Skip auth for local dev
```

---

## Future Roadmap (Do NOT implement yet — context only)

### Phase 2: Purchase Flow
After comparison, agent asks: "Which one would you like to buy?"
If user picks Amazon → agent opens amazon.in product page → assists with add to cart → user confirms.
This will likely need:
- Playwright/browser automation on backend
- A new LangGraph subgraph for purchase flow
- User permission/confirmation step before any purchase action

### Phase 3: More Platforms
Add Croma, Reliance Digital, Tata CLiQ for electronics.
Add Myntra, Ajio for fashion.
The `_search_shopping()` function is already parameterized by source — just add more domains.

### Phase 4: Price Tracking
Save comparison results, track price changes over time, alert user when price drops.

---

## Testing Commands

```bash
# Debug SerpAPI (see raw results)
python debug_serpapi.py

# Test agent pipeline
python test_agent.py

# Start backend
uvicorn main:app --reload --port 8000

# Quick compare test (with DEV_MODE=true)
curl -X POST http://localhost:8000/api/compare \
  -H "Content-Type: application/json" \
  -d '{"query": "iPhone 15"}'

# Streaming test
curl -N -X POST http://localhost:8000/api/compare/stream \
  -H "Content-Type: application/json" \
  -d '{"query": "Samsung Galaxy S24"}'

# Frontend
cd frontend && npm run dev
```

---

## Code Conventions
- Python: type hints, `str | None` style, no Optional
- LangGraph: TypedDict for state, pure functions for nodes
- Frontend: React functional components, Tailwind, CSS variables for theming
- Async: `asyncio.Queue` + `run_in_executor` to wrap sync generators into SSE
- Error handling: always catch SerpAPI/OpenAI exceptions, return graceful fallbacks