"""Creates (or updates) the Azure AI Search index for clinical notes, configured
for hybrid search: keyword search over `text` plus vector search over
`content_vector` (text-embedding-3-small, 1536 dims), combined at query time
with RRF — not a vector-only index, since clinical vocabulary/abbreviations
vary too much for embeddings alone to be reliable.

Usage:
    python scripts/create_search_index.py
"""
import os

from azure.core.credentials import AzureKeyCredential
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    SearchableField,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SimpleField,
    VectorSearch,
    VectorSearchProfile,
)
from dotenv import load_dotenv

load_dotenv()

EMBEDDING_DIMENSIONS = 1536


def main():
    endpoint = os.environ["AZURE_SEARCH_ENDPOINT"]
    # Index management needs the admin key — the app-facing AZURE_SEARCH_API_KEY
    # is a read-only query key and can't create/update indexes.
    key = os.environ["AZURE_SEARCH_ADMIN_KEY"]
    index_name = os.environ.get("AZURE_SEARCH_INDEX_NAME", "clinical-notes")

    client = SearchIndexClient(endpoint=endpoint, credential=AzureKeyCredential(key))

    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True),
        SimpleField(name="subject_id", type=SearchFieldDataType.Int32, filterable=True, facetable=True),
        SimpleField(name="hadm_id", type=SearchFieldDataType.Int32, filterable=True, facetable=True),
        SimpleField(name="note_type", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="charttime", type=SearchFieldDataType.DateTimeOffset, filterable=True, sortable=True),
        SearchableField(name="text", type=SearchFieldDataType.String),
        SearchField(
            name="content_vector",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=EMBEDDING_DIMENSIONS,
            vector_search_profile_name="default-vector-profile",
        ),
    ]

    vector_search = VectorSearch(
        algorithms=[HnswAlgorithmConfiguration(name="default-hnsw")],
        profiles=[VectorSearchProfile(name="default-vector-profile", algorithm_configuration_name="default-hnsw")],
    )

    index = SearchIndex(name=index_name, fields=fields, vector_search=vector_search)
    client.create_or_update_index(index)
    print(f"Index '{index_name}' created/updated at {endpoint}")


if __name__ == "__main__":
    main()
