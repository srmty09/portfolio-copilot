import logging

import yfinance as yf
from langchain_core.documents import Document
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings

from app.core.config import settings

logger = logging.getLogger(__name__)

NEWS_ITEMS_PER_TICKER = 4
NEWS_SUMMARY_MAX_CHARS = 400

# Small hardcoded knowledge base the agent can cite when explaining risk concepts.
# Combined at query time with fresh per-ticker news (see _fetch_news_documents).
DOCUMENTS = [
    "Diversification reduces portfolio risk by spreading capital across assets that do not move in "
    "perfect lockstep. A portfolio concentrated in a single stock or sector carries idiosyncratic risk "
    "that a diversified portfolio largely avoids, since losses in one holding can be offset by gains or "
    "stability in others.",
    "Value at Risk (VaR) estimates the maximum expected loss of a portfolio over a given time horizon at "
    "a chosen confidence level. A 95 percent one-month VaR of 10 percent means there is roughly a 5 "
    "percent chance the portfolio loses more than 10 percent of its value over the next month, assuming "
    "historical patterns hold.",
    "Market volatility measures how much an asset's price fluctuates over time and is commonly estimated "
    "from the standard deviation of historical returns. High-volatility stocks can produce larger gains "
    "but also larger drawdowns, so investors with a low risk tolerance often prefer lower-volatility "
    "holdings.",
    "Correlation between holdings determines how much true diversification a portfolio has. Two stocks "
    "in the same sector often move together and rise or fall for the same reasons, so combining them adds "
    "less diversification benefit than combining assets from unrelated sectors or asset classes.",
]

_embeddings = None


def _get_embeddings() -> HuggingFaceEmbeddings:
    # The embedding model is the expensive, static part (downloads once, loads into
    # memory) so it's cached; the document set below is cheap and rebuilt per call
    # since it depends on which tickers are being analyzed right now.
    global _embeddings
    if _embeddings is None:
        logger.info("Loading embedding model '%s'", settings.EMBEDDING_MODEL)
        _embeddings = HuggingFaceEmbeddings(model_name=settings.EMBEDDING_MODEL)
    return _embeddings


def _fetch_news_documents(tickers: list[str]) -> list[Document]:
    documents = []
    for ticker in tickers:
        try:
            items = yf.Ticker(ticker).news or []
        except Exception:
            logger.warning("Failed to fetch news for %s", ticker, exc_info=True)
            continue

        fetched = 0
        for item in items:
            if fetched >= NEWS_ITEMS_PER_TICKER:
                break
            content = item.get("content", {})
            title = content.get("title")
            if not title:
                continue
            summary = (content.get("summary") or "")[:NEWS_SUMMARY_MAX_CHARS]
            text = f"Recent news about {ticker}: {title}."
            if summary:
                text += " " + summary
            documents.append(Document(page_content=text))
            fetched += 1
        logger.info("Fetched %d news item(s) for %s", fetched, ticker)
    return documents


def retrieve(query: str, tickers: list[str] | None = None, k: int = 3) -> list[str]:
    logger.info("RAG retrieve: query=%r tickers=%s k=%d", query, tickers, k)
    documents = [Document(page_content=text) for text in DOCUMENTS]
    if tickers:
        documents.extend(_fetch_news_documents(tickers))

    store = FAISS.from_documents(documents, _get_embeddings())
    results = store.similarity_search(query, k=k)
    logger.info("RAG retrieve: returned %d chunks (corpus size %d)", len(results), len(documents))
    return [doc.page_content for doc in results]
