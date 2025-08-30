import os
import textwrap
from typing import Dict, List, Tuple

import requests
import streamlit as st

# -----------------------------
# Setup & Config
# -----------------------------
TMDB_API_KEY = st.secrets.get("TMDB_API_KEY") or os.environ.get("TMDB_API_KEY", "")
BASE = "https://api.themoviedb.org/3"
HEADERS = {"Authorization": f"Bearer {TMDB_API_KEY}"} if TMDB_API_KEY and len(TMDB_API_KEY) > 40 else None

# Tip: You can use either a "v4" Bearer token (preferred) via Authorization header
# or a classic api_key query string. This app auto-detects based on token length.

def tmdb_get(path: str, params: Dict = None):
    """Helper for TMDb GET with either v4 Bearer or api_key fallback."""
    params = params or {}
    if HEADERS:
        # v4 auth
        resp = requests.get(f"{BASE}{path}", params=params, headers=HEADERS, timeout=20)
    else:
        # fallback to v3 api_key in query
        if not TMDB_API_KEY:
            raise RuntimeError("No TMDB_API_KEY provided. Set st.secrets['TMDB_API_KEY'] or env var TMDB_API_KEY.")
        params = {"api_key": TMDB_API_KEY, **params}
        resp = requests.get(f"{BASE}{path}", params=params, timeout=20)
    resp.raise_for_status()
    return resp.json()

# -----------------------------
# Mood → Keyword names (human friendly)
# Later we resolve names → TMDb keyword IDs via API
# -----------------------------
MOOD_MAP: Dict[str, List[str]] = {
    "Feel-Good": ["friendship", "family", "happy ending", "optimism"],
    "Heartbreaking": ["tragedy", "death", "illness", "doomed romance"],
    "Melancholic": ["nostalgia", "memory", "bittersweet", "loneliness"],
    "Wholesome": ["kindness", "friendship", "animals", "found family"],
    "Cathartic": ["redemption", "forgiveness", "trauma", "self discovery"],
    "Lost / Loneliness": ["isolation", "loneliness", "solitude"],
    "Escapist": ["fantasy world", "imagination", "parallel universe", "adventure"],
    "Hopeful": ["inspiration", "overcoming obstacles", "resilience"],
    "Dark & Gritty": ["neo-noir", "urban decay", "crime", "violence"],
    "Weirdcore / Surreal": ["surrealism", "dream", "hallucination", "absurd"],
    "Trippy": ["psychedelic", "drugs", "hallucination", "acid"],
    "Uplifting": ["sports", "inspiration", "success", "mentor"],
    "Sentimental": ["memory", "nostalgia", "family", "childhood"],
    "Poetic": ["poetry", "dream", "visual metaphor", "art"],
    "Slow Burn": ["psychological", "tension", "atmosphere", "slow burn"],
    "Cozy": ["small town", "friendship", "community", "slice of life"],
    "Bittersweet Romance": ["romance", "tragedy", "love affair", "forbidden love"],
    "Coming of Age": ["coming of age", "teenager", "youth", "self discovery"],
    "Existential": ["philosophy", "existentialism", "death", "meaning of life"],
    "Dreamlike": ["dream", "fantasy", "surrealism", "vision"],
    "Eerie / Haunting": ["ghost", "haunted house", "supernatural", "mystery"],
    "Nostalgic": ["retro", "nostalgia", "childhood", "memory"],
    "Hope in Darkness": ["war", "survival", "courage", "resistance"],
    "Liberating": ["freedom", "rebellion", "escape", "self discovery"],
    "Chaotic Energy": ["crime spree", "gang", "anarchy", "violence"],
}

# -----------------------------
# Keyword ID resolution & caching
# -----------------------------
from functools import lru_cache

@lru_cache(maxsize=2048)
def search_keyword_id(keyword_name: str) -> int | None:
    """Find the best matching TMDb keyword ID for a given keyword name.
    Returns None if not found.
    """
    data = tmdb_get("/search/keyword", {"query": keyword_name})
    results = data.get("results", [])
    if not results:
        return None
    # Simple heuristic: prefer exact (case-insensitive) name match; else first
    exact = next((r for r in results if r.get("name", "").lower() == keyword_name.lower()), None)
    return (exact or results[0]).get("id")

@lru_cache(maxsize=512)
def resolve_mood_to_keyword_ids(mood: str) -> List[int]:
    names = MOOD_MAP.get(mood, [])
    ids: List[int] = []
    for n in names:
        kid = search_keyword_id(n)
        if kid:
            ids.append(kid)
    return ids

# -----------------------------
# Discover movies with keyword logic
# -----------------------------

def discover_movies(
    keyword_ids: List[int],
    require_all: bool = True,
    language: str = "en-US",
    region: str = "CH",
    vote_count_gte: int = 200,
    year_min: int = 1950,
    year_max: int = 2025,
    page: int = 1,
    sort_by: str = "vote_average.desc",
) -> Dict:
    if not keyword_ids:
        return {"results": []}

    # AND = comma separated, OR = pipe separated
    if require_all:
        kw_param = ",".join(str(k) for k in keyword_ids)
    else:
        kw_param = "|".join(str(k) for k in keyword_ids)

    params = {
        "with_keywords": kw_param,
        "include_adult": "false",
        "language": language,
        "region": region,
        "sort_by": sort_by,  # note: use popularity.desc for broader results
        "vote_count.gte": vote_count_gte,
        "page": page,
        "primary_release_date.gte": f"{year_min}-01-01",
        "primary_release_date.lte": f"{year_max}-12-31",
    }
    return tmdb_get("/discover/movie", params)

@lru_cache(maxsize=1024)
def get_watch_providers(movie_id: int, watch_region: str = "CH") -> List[str]:
    """Return a human-readable list of watch providers for a given movie in a region."""
    try:
        data = tmdb_get(f"/movie/{movie_id}/watch/providers")
    except Exception:
        return []
    results = data.get("results", {})
    entry = results.get(watch_region, {})
    providers = []
    for k in ("flatrate", "rent", "buy", "ads", "free"):
        for prov in entry.get(k, []) or []:
            providers.append(prov.get("provider_name"))
    # deduplicate while preserving order
    seen = set()
    out = []
    for p in providers:
        if p and p not in seen:
            out.append(p)
            seen.add(p)
    return out

# -----------------------------
# UI
# -----------------------------
st.set_page_config(page_title="Nanogenre Recommender", page_icon="🎬", layout="wide")

st.title("🎬 Nanogenre Recommender (TMDb)")

with st.sidebar:
    st.header("🔑 API Key")
    if not TMDB_API_KEY:
        st.error("Bitte TMDB_API_KEY als Streamlit Secret oder Umgebungsvariable setzen.")
    else:
        st.success("TMDb Key erkannt.")

    st.header("⚙️ Filter")
    mood = st.selectbox("Mood / Emotion", sorted(MOOD_MAP.keys()))

    # Let user fine-tune keyword selection per mood
    default_keywords = MOOD_MAP.get(mood, [])
    selected_keyword_names = st.multiselect(
        "Keywords für dieses Mood",
        options=default_keywords,
        default=default_keywords,
        help="Du kannst Keywords entfernen/hinzufügen, bevor die IDs aufgelöst werden.",
    )

    require_all = st.toggle("Alle Keywords erforderlich (AND)", value=True, help="Wenn aus, genügt irgendeines (OR)")

    colA, colB = st.columns(2)
    with colA:
        year_min = st.number_input("Jahr von", 1900, 2025, 1990)
    with colB:
        year_max = st.number_input("Jahr bis", 1900, 2025, 2025)

    min_votes = st.slider("Min. Anzahl Stimmen (Qualitätsfilter)", 0, 2000, 200, step=50)
    sort_by = st.selectbox("Sortierung", [
        "vote_average.desc",
        "popularity.desc",
        "primary_release_date.desc",
        "revenue.desc",
    ], index=0)

    region = st.text_input("Region (ISO 3166-1)", value="CH")
    language = st.text_input("Sprache (ISO Code)", value="de-CH")

    st.caption("Tipp: Für breitere Resultate 'popularity.desc' wählen oder Min-Stimmen senken.")

# Resolve keyword IDs for chosen names (fresh per selection)
resolved_ids: List[int] = []
for name in selected_keyword_names:
    kid = search_keyword_id(name)
    if kid:
        resolved_ids.append(kid)

with st.expander("🔎 Debug: Aufgelöste Keyword-IDs"):
    st.write({name: search_keyword_id(name) for name in selected_keyword_names})

# Fetch results
if st.button("🔍 Filme finden", type="primary"):
    try:
        data = discover_movies(
            keyword_ids=resolved_ids,
            require_all=require_all,
            language=language,
            region=region,
            vote_count_gte=min_votes,
            year_min=year_min,
            year_max=year_max,
            page=1,
            sort_by=sort_by,
        )
        results = data.get("results", [])
        total = data.get("total_results", 0)
        st.subheader(f"Ergebnisse: {len(results)} von {total}")

        if not results:
            st.info("Keine Treffer mit diesen Filtern. Versuche 'OR'-Suche, min. Stimmen senken oder 'popularity.desc'.")
        else:
            # Display grid of posters
            num_cols = 5
            rows = (len(results) + num_cols - 1) // num_cols
            idx = 0
            for _ in range(rows):
                cols = st.columns(num_cols)
                for c in cols:
                    if idx >= len(results):
                        break
                    m = results[idx]
                    idx += 1
                    title = m.get("title") or m.get("name")
                    year = (m.get("release_date") or "")[:4]
                    rating = m.get("vote_average")
                    overview = m.get("overview") or ""
                    poster = m.get("poster_path")
                    tmdb_url = f"https://www.themoviedb.org/movie/{m.get('id')}"
                    letterboxd_search = f"https://letterboxd.com/search/{title.replace(' ', '%20')}" if title else None

                    with c:
                        if poster:
                            st.image(f"https://image.tmdb.org/t/p/w342{poster}", use_container_width=True)
                        st.markdown(f"**{title}** ({year})")
                        st.caption(f"TMDb: {rating:.1f} ⭐")
                        st.write(textwrap.shorten(overview, width=140, placeholder=" …"))

                        providers = get_watch_providers(m.get("id"), watch_region=region)
                        if providers:
                            st.caption("Verfügbar bei: " + ", ".join(providers[:6]))

                        link_col1, link_col2 = st.columns(2)
                        with link_col1:
                            st.link_button("TMDb", tmdb_url, use_container_width=True)
                        with link_col2:
                            if letterboxd_search:
                                st.link_button("Letterboxd", letterboxd_search, use_container_width=True)
    except Exception as e:
        st.error(f"Fehler bei der Abfrage: {e}")

st.markdown("---")
st.caption(
    "Hinweis: Keyword-Namen werden dynamisch in TMDb-Keyword-IDs aufgelöst. "
    "'Alle Keywords' entspricht AND, ansonsten OR. Watch-Provider stammen aus TMDb (JustWatch)."
)
